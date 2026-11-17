#!/usr/bin/python3 -I
"""nvcontrol-helper — the ONLY component of NV//CONTROL that runs as root.

Invoked through pkexec (polkit action org.nvcontrol.helper) or by the
nvcontrol-apply systemd unit. It accepts a fixed set of sub-commands with
numeric arguments, validates every value against the limits the NVIDIA driver
itself reports, and never runs a shell. Every call is appended to
/var/log/nvcontrol-helper.log.

It does not, and cannot, exceed driver-enforced limits: NVML rejects values
outside the board's constraints, and we pre-check them too.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

STARTUP_FILE = Path("/etc/nvcontrol/tuning.json")
STATE_DIR = Path("/var/lib/nvcontrol")
PENDING = STATE_DIR / "boot-pending"
LOG = Path("/var/log/nvcontrol-helper.log")

EXIT_OK, EXIT_INVALID, EXIT_NVML, EXIT_UNSUPPORTED = 0, 2, 3, 4


class Invalid(Exception):
    pass


# --------------------------------------------------------------------- validation (pure)
def check_range(name: str, value: float, lo: float, hi: float) -> float:
    if not (lo <= value <= hi):
        raise Invalid(f"{name} {value} outside driver range [{lo}, {hi}]")
    return value


def validate_lock(min_mhz: int, max_mhz: int, supported: list[int]) -> tuple[int, int]:
    if min_mhz > max_mhz:
        raise Invalid("lock min must be <= max")
    if supported:
        lo, hi = min(supported), max(supported)
        check_range("lock min", min_mhz, lo, hi)
        check_range("lock max", max_mhz, lo, hi)
    elif min_mhz < 100 or max_mhz > 5000:
        raise Invalid("clock values implausible")
    return min_mhz, max_mhz


def validate_startup(d: dict) -> dict:
    allowed = {"gpu", "power_w", "core_offset", "mem_offset", "lock_min", "lock_max"}
    extra = set(d) - allowed
    if extra:
        raise Invalid(f"unknown keys {sorted(extra)}")
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise Invalid(f"{k} must be numeric")
        out[k] = int(v) if k != "power_w" else float(v)
    out.setdefault("gpu", 0)
    if not 0 <= out["gpu"] < 16:
        raise Invalid("gpu index out of range")
    return out


def safe_mode_requested(cmdline: str) -> bool:
    return "nvcontrol.safe=1" in cmdline.split()


# --------------------------------------------------------------------- NVML ops
def _nvml():
    try:
        import pynvml as N
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("python-nvidia-ml-py is not installed") from e
    N.nvmlInit()
    return N


def _handle(N, gpu: int):
    if not 0 <= gpu < N.nvmlDeviceGetCount():
        raise Invalid(f"no GPU {gpu}")
    return N.nvmlDeviceGetHandleByIndex(gpu)


def op_set_power(gpu: int, watts: float):
    N = _nvml()
    h = _handle(N, gpu)
    lo, hi = N.nvmlDeviceGetPowerManagementLimitConstraints(h)
    check_range("power limit (W)", watts, lo / 1000, hi / 1000)
    N.nvmlDeviceSetPowerManagementLimit(h, int(watts * 1000))
    return {"power_w": N.nvmlDeviceGetPowerManagementLimit(h) / 1000}


def op_reset_power(gpu: int):
    N = _nvml()
    h = _handle(N, gpu)
    d = N.nvmlDeviceGetPowerManagementDefaultLimit(h)
    N.nvmlDeviceSetPowerManagementLimit(h, d)
    return {"power_w": d / 1000}


def op_set_offsets(gpu: int, core: int | None, mem: int | None):
    N = _nvml()
    h = _handle(N, gpu)
    res = {}
    if core is not None:
        lo, hi = N.nvmlDeviceGetGpcClkMinMaxVfOffset(h)
        check_range("core offset (MHz)", core, lo, hi)
        N.nvmlDeviceSetGpcClkVfOffset(h, int(core))
        res["core_offset"] = N.nvmlDeviceGetGpcClkVfOffset(h)
    if mem is not None:
        lo, hi = N.nvmlDeviceGetMemClkMinMaxVfOffset(h)
        check_range("memory offset (MHz)", mem, lo, hi)
        N.nvmlDeviceSetMemClkVfOffset(h, int(mem))
        res["mem_offset"] = N.nvmlDeviceGetMemClkVfOffset(h)
    return res


def op_lock(gpu: int, lo: int, hi: int):
    N = _nvml()
    h = _handle(N, gpu)
    supported: list[int] = []
    try:
        mems = N.nvmlDeviceGetSupportedMemoryClocks(h)
        supported = list(N.nvmlDeviceGetSupportedGraphicsClocks(h, max(mems)))
    except Exception:  # noqa: BLE001
        pass
    validate_lock(lo, hi, supported)
    N.nvmlDeviceSetGpuLockedClocks(h, int(lo), int(hi))
    return {"locked": [lo, hi]}


def op_reset_clocks(gpu: int):
    N = _nvml()
    h = _handle(N, gpu)
    N.nvmlDeviceResetGpuLockedClocks(h)
    return {"locked": None}


def op_set_fan(gpu: int, pct: int):
    N = _nvml()
    h = _handle(N, gpu)
    n = N.nvmlDeviceGetNumFans(h)
    if n < 1:
        raise Invalid("no controllable fans")
    lo, hi = N.nvmlDeviceGetMinMaxFanSpeed(h)
    check_range("fan speed (%)", pct, lo, hi)
    for i in range(n):
        N.nvmlDeviceSetFanSpeed_v2(h, i, int(pct))
    return {"fan_pct": pct, "fans": n}


def op_reset_fan(gpu: int):
    N = _nvml()
    h = _handle(N, gpu)
    n = N.nvmlDeviceGetNumFans(h)
    for i in range(n):
        N.nvmlDeviceSetDefaultFanSpeed_v2(h, i)
    return {"fan": "auto", "fans": n}


def op_reset_all(gpu: int):
    out = {}
    for name, fn in (("power", op_reset_power), ("clocks", op_reset_clocks), ("fan", op_reset_fan)):
        try:
            out[name] = fn(gpu)
        except Exception as e:  # noqa: BLE001 - keep resetting the rest
            out[name] = f"skipped: {e}"
    try:
        out["offsets"] = op_set_offsets(gpu, 0, 0)
    except Exception as e:  # noqa: BLE001
        out["offsets"] = f"skipped: {e}"
    return out


def apply_settings(s: dict) -> dict:
    gpu = s.get("gpu", 0)
    res = {}
    if "power_w" in s:
        res["power"] = op_set_power(gpu, s["power_w"])
    if "core_offset" in s or "mem_offset" in s:
        res["offsets"] = op_set_offsets(gpu, s.get("core_offset"), s.get("mem_offset"))
    if "lock_min" in s and "lock_max" in s:
        res["lock"] = op_lock(gpu, s["lock_min"], s["lock_max"])
    return res


def op_apply_startup():
    try:
        cmdline = Path("/proc/cmdline").read_text()
    except OSError:
        cmdline = ""
    if safe_mode_requested(cmdline):
        return {"skipped": "nvcontrol.safe=1 on kernel command line"}
    if not STARTUP_FILE.exists():
        return {"skipped": "no startup profile"}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if PENDING.exists():
        return {"skipped": "previous boot did not reach the stable mark — startup tuning disabled. "
                           "Re-save it from NV//CONTROL or run: nvcontrol-helper clear-startup"}
    s = validate_startup(json.loads(STARTUP_FILE.read_text()))
    PENDING.write_text(str(time.time()))
    return apply_settings(s)


def op_mark_stable():
    PENDING.unlink(missing_ok=True)
    return {"stable": True}


def op_save_startup(s: dict):
    s = validate_startup(s)
    STARTUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STARTUP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, STARTUP_FILE)
    PENDING.unlink(missing_ok=True)
    return {"saved": s}


def op_clear_startup():
    STARTUP_FILE.unlink(missing_ok=True)
    PENDING.unlink(missing_ok=True)
    return {"cleared": True}


def op_read_startup():
    if STARTUP_FILE.exists():
        return {"startup": json.loads(STARTUP_FILE.read_text()), "pending": PENDING.exists()}
    return {"startup": None, "pending": PENDING.exists()}


# --------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nvcontrol-helper", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def g(sp):
        sp.add_argument("--gpu", type=int, default=0)
        return sp

    g(sub.add_parser("set-power-limit")).add_argument("--watts", type=float, required=True)
    g(sub.add_parser("reset-power-limit"))
    s = g(sub.add_parser("set-offsets"))
    s.add_argument("--core", type=int)
    s.add_argument("--mem", type=int)
    s = g(sub.add_parser("lock-clocks"))
    s.add_argument("--min", type=int, required=True)
    s.add_argument("--max", type=int, required=True)
    g(sub.add_parser("reset-clocks"))
    g(sub.add_parser("set-fan")).add_argument("--percent", type=int, required=True)
    g(sub.add_parser("reset-fan"))
    g(sub.add_parser("reset-all"))
    s = g(sub.add_parser("save-startup"))
    s.add_argument("--power", type=float)
    s.add_argument("--core", type=int)
    s.add_argument("--mem", type=int)
    s.add_argument("--lock-min", type=int)
    s.add_argument("--lock-max", type=int)
    s = g(sub.add_parser("apply", help="apply several settings in one authenticated call"))
    s.add_argument("--power", type=float)
    s.add_argument("--core", type=int)
    s.add_argument("--mem", type=int)
    s.add_argument("--lock-min", type=int)
    s.add_argument("--lock-max", type=int)
    s.add_argument("--unlock", action="store_true")
    s.add_argument("--fan", type=int)
    s.add_argument("--fan-auto", action="store_true")
    sub.add_parser("clear-startup")
    sub.add_parser("read-startup")
    sub.add_parser("apply-startup")
    sub.add_parser("mark-stable")
    return p


def dispatch(a) -> dict:
    c = a.cmd
    if c == "set-power-limit":
        return op_set_power(a.gpu, a.watts)
    if c == "reset-power-limit":
        return op_reset_power(a.gpu)
    if c == "set-offsets":
        if a.core is None and a.mem is None:
            raise Invalid("nothing to set")
        return op_set_offsets(a.gpu, a.core, a.mem)
    if c == "lock-clocks":
        return op_lock(a.gpu, a.min, a.max)
    if c == "reset-clocks":
        return op_reset_clocks(a.gpu)
    if c == "set-fan":
        return op_set_fan(a.gpu, a.percent)
    if c == "reset-fan":
        return op_reset_fan(a.gpu)
    if c == "reset-all":
        return op_reset_all(a.gpu)
    if c == "save-startup":
        d = {"gpu": a.gpu, "power_w": a.power, "core_offset": a.core, "mem_offset": a.mem,
             "lock_min": a.lock_min, "lock_max": a.lock_max}
        if (a.lock_min is None) != (a.lock_max is None):
            raise Invalid("lock needs both --lock-min and --lock-max")
        return op_save_startup(d)
    if c == "apply":
        if (a.lock_min is None) != (a.lock_max is None):
            raise Invalid("lock needs both --lock-min and --lock-max")
        if a.fan is not None and a.fan_auto:
            raise Invalid("--fan and --fan-auto are mutually exclusive")
        res = {}
        errors = []
        steps = []
        if a.power is not None:
            steps.append(("power", lambda: op_set_power(a.gpu, a.power)))
        if a.core is not None or a.mem is not None:
            steps.append(("offsets", lambda: op_set_offsets(a.gpu, a.core, a.mem)))
        if a.unlock:
            steps.append(("unlock", lambda: op_reset_clocks(a.gpu)))
        if a.lock_min is not None:
            steps.append(("lock", lambda: op_lock(a.gpu, a.lock_min, a.lock_max)))
        if a.fan is not None:
            steps.append(("fan", lambda: op_set_fan(a.gpu, a.fan)))
        if a.fan_auto:
            steps.append(("fan", lambda: op_reset_fan(a.gpu)))
        for name, fn in steps:
            try:
                res[name] = fn()
            except Exception as e:  # noqa: BLE001 - report per-step, continue
                errors.append(f"{name}: {type(e).__name__}: {e}")
        if errors:
            raise Invalid("; ".join(errors) + (f" (applied: {sorted(res)})" if res else ""))
        return res
    if c == "clear-startup":
        return op_clear_startup()
    if c == "read-startup":
        return op_read_startup()
    if c == "apply-startup":
        return op_apply_startup()
    if c == "mark-stable":
        return op_mark_stable()
    raise Invalid(f"unknown command {c}")


def audit(argv: list[str], result: str) -> None:
    try:
        uid = os.environ.get("PKEXEC_UID", str(os.getuid()))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} uid={uid} args={argv} -> {result}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)
    if os.geteuid() != 0 and args.cmd not in ("read-startup",):
        print(json.dumps({"ok": False, "error": "must run as root (via pkexec)"}))
        return EXIT_INVALID
    try:
        res = dispatch(args)
        out, code = {"ok": True, "result": res}, EXIT_OK
    except Invalid as e:
        out, code = {"ok": False, "error": str(e)}, EXIT_INVALID
    except Exception as e:  # noqa: BLE001 - NVMLError_* incl. NotSupported/NoPermission
        name = type(e).__name__
        code = EXIT_UNSUPPORTED if "NotSupported" in name else EXIT_NVML
        out = {"ok": False, "error": f"{name}: {e}"}
    audit(argv, "ok" if out["ok"] else out["error"])
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
