"""GUI-side client for the privileged helper (pkexec). Mockable for tests/demo."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ..capabilities.system import HELPER_PATH
from ..core import runner

log = logging.getLogger(__name__)

@dataclass
class HelperResult:
    ok: bool
    data: dict
    error: str = ""
    command: str = ""


def describe(args: list[str]) -> str:
    """Exact command shown to the user before authentication."""
    return " ".join(["pkexec", HELPER_PATH, *args])


class HelperClient:
    def __init__(self, path: str = HELPER_PATH):
        self.path = path

    def call(self, args: list[str], timeout: float = 90) -> HelperResult:
        args = [str(a) for a in args]
        cmd = ["pkexec", self.path, *args]
        log.info("helper call: %s", describe(args))
        r = runner.run(cmd, timeout=timeout)
        if r.code in (126, 127) and not r.out:
            log.warning("helper not run (code %d): %s", r.code, r.err.strip())
            return HelperResult(False, {}, "Authentication cancelled or pkexec unavailable.", describe(args))
        try:
            payload = json.loads(r.out.strip().splitlines()[-1]) if r.out.strip() else {}
        except ValueError:
            payload = {}
        if payload.get("ok"):
            log.info("helper ok: %s -> %s", args[0], payload.get("result"))
            return HelperResult(True, payload.get("result", {}), "", describe(args))
        err = payload.get("error") or r.err.strip() or f"exit {r.code}"
        log.error("helper failed: %s -> %s", describe(args), err)
        return HelperResult(False, {}, err, describe(args))

    # convenience wrappers --------------------------------------------------
    def set_power(self, gpu: int, watts: float):
        return self.call(["set-power-limit", "--gpu", gpu, "--watts", f"{watts:.0f}"])

    def reset_power(self, gpu: int):
        return self.call(["reset-power-limit", "--gpu", gpu])

    def set_offsets(self, gpu: int, core: int | None, mem: int | None):
        a = ["set-offsets", "--gpu", gpu]
        if core is not None:
            a += ["--core", int(core)]
        if mem is not None:
            a += ["--mem", int(mem)]
        return self.call(a)

    def lock_clocks(self, gpu: int, lo: int, hi: int):
        return self.call(["lock-clocks", "--gpu", gpu, "--min", int(lo), "--max", int(hi)])

    def reset_clocks(self, gpu: int):
        return self.call(["reset-clocks", "--gpu", gpu])

    def set_fan(self, gpu: int, pct: int):
        return self.call(["set-fan", "--gpu", gpu, "--percent", int(pct)])

    def reset_fan(self, gpu: int):
        return self.call(["reset-fan", "--gpu", gpu])

    def reset_all(self, gpu: int):
        return self.call(["reset-all", "--gpu", gpu])

    def save_startup(self, gpu: int, s: dict):
        a = ["save-startup", "--gpu", gpu]
        for key, flag in (("power_w", "--power"), ("core_offset", "--core"), ("mem_offset", "--mem"),
                          ("lock_min", "--lock-min"), ("lock_max", "--lock-max")):
            if s.get(key) is not None:
                a += [flag, int(s[key])]
        return self.call(a)

    def clear_startup(self):
        return self.call(["clear-startup"])

    # GPU Lab ---------------------------------------------------------------
    def set_fan_one(self, gpu: int, fan: int, pct: int):
        return self.call(["set-fan", "--gpu", gpu, "--percent", int(pct), "--fan", int(fan)])

    def set_temp_target(self, gpu: int, c: int):
        return self.call(["set-temp-target", "--gpu", gpu, "--celsius", int(c)])

    def reset_temp_target(self, gpu: int):
        return self.call(["reset-temp-target", "--gpu", gpu])

    def lock_mem(self, gpu: int, lo: int, hi: int):
        return self.call(["lock-mem-clocks", "--gpu", gpu, "--min", int(lo), "--max", int(hi)])

    def reset_mem(self, gpu: int):
        return self.call(["reset-mem-clocks", "--gpu", gpu])

    def set_persistence(self, gpu: int, on: bool):
        return self.call(["set-persistence", "--gpu", gpu, "--state", "on" if on else "off"])

    def save_fan_curve(self, gpu: int, points: list[list[int]]):
        return self.call(["save-fan-curve", "--gpu", gpu, "--points", json.dumps(points, separators=(",", ":"))])

    def fan_curve(self, on: bool):
        return self.call(["enable-fan-curve" if on else "disable-fan-curve"])

    def apply(self, gpu: int, s: dict, unlock: bool = False, fan_auto: bool = False):
        """One pkexec prompt for a whole batch of settings."""
        a = ["apply", "--gpu", gpu]
        if s.get("power_w") is not None:
            a += ["--power", f"{float(s['power_w']):.0f}"]
        for key, flag in (("core_offset", "--core"), ("mem_offset", "--mem"), ("lock_min", "--lock-min"),
                          ("lock_max", "--lock-max"), ("fan_pct", "--fan")):
            if s.get(key) is not None:
                a += [flag, int(s[key])]
        if unlock:
            a.append("--unlock")
        if fan_auto:
            a.append("--fan-auto")
        return self.call(a)


class MockHelperClient(HelperClient):
    """Applies changes to a MockBackend instead of hardware."""

    def __init__(self, backend):
        super().__init__("/usr/lib/nvcontrol/nvcontrol-helper")
        self.b = backend
        self.startup: dict | None = None

    def call(self, args, timeout=90):
        a = [str(x) for x in args]
        cmd, opts = a[0], {}
        i = 1
        while i < len(a):
            if i + 1 < len(a) and not a[i + 1].startswith("--"):
                opts[a[i]] = a[i + 1]
                i += 2
            else:
                opts[a[i]] = "1"
                i += 1
        caps = self.b.tuning_caps(0)
        log.info("[mock] helper %s %s", cmd, opts)
        try:
            if cmd == "apply":
                if "--power" in opts:
                    w = float(opts["--power"])
                    if not caps.power.min_w <= w <= caps.power.max_w:
                        raise ValueError(f"power {w} outside driver range")
                    self.b.power_limit = w
                if "--core" in opts:
                    self.b.gpc_offset = int(opts["--core"])
                if "--mem" in opts:
                    self.b.mem_offset = int(opts["--mem"])
                if "--unlock" in opts:
                    self.b.locked = None
                if "--lock-min" in opts:
                    self.b.locked = (int(opts["--lock-min"]), int(opts["--lock-max"]))
                if "--fan" in opts:
                    self.b.fan_manual = int(opts["--fan"])
                if "--fan-auto" in opts:
                    self.b.fan_manual = None
            elif cmd == "set-temp-target":
                c = int(opts["--celsius"])
                if not 65 <= c <= 91:
                    raise ValueError(f"temperature target {c} outside driver range [65, 91]")
                self.b.temp_target = c
            elif cmd == "reset-temp-target":
                self.b.temp_target = 83
            elif cmd == "lock-mem-clocks":
                self.b.mem_locked = (int(opts["--min"]), int(opts["--max"]))
            elif cmd == "reset-mem-clocks":
                self.b.mem_locked = None
            elif cmd == "set-persistence":
                self.b.persistence = opts["--state"] == "on"
            elif cmd == "save-fan-curve":
                self.b.fan_curve = json.loads(opts["--points"])
            elif cmd in ("enable-fan-curve", "disable-fan-curve"):
                if cmd == "enable-fan-curve" and not self.b.fan_curve:
                    raise ValueError("save a fan curve first")
                self.b.fan_curve_on = cmd == "enable-fan-curve"
            elif cmd == "set-fan" and "--fan" in opts:
                self.b.fan_per[int(opts["--fan"])] = int(opts["--percent"])
            elif cmd == "set-power-limit":
                w = float(opts["--watts"])
                if not caps.power.min_w <= w <= caps.power.max_w:
                    raise ValueError("outside driver range")
                self.b.power_limit = w
            elif cmd == "reset-power-limit":
                self.b.power_limit = caps.power.default_w
            elif cmd == "set-offsets":
                if "--core" in opts:
                    self.b.gpc_offset = int(opts["--core"])
                if "--mem" in opts:
                    self.b.mem_offset = int(opts["--mem"])
            elif cmd == "lock-clocks":
                self.b.locked = (int(opts["--min"]), int(opts["--max"]))
            elif cmd == "reset-clocks":
                self.b.locked = None
            elif cmd == "set-fan":
                self.b.fan_manual = int(opts["--percent"])
            elif cmd == "reset-fan":
                self.b.fan_manual = None
            elif cmd == "reset-all":
                self.b.power_limit, self.b.gpc_offset, self.b.mem_offset = caps.power.default_w, 0, 0
                self.b.locked, self.b.fan_manual = None, None
            elif cmd == "save-startup":
                self.startup = opts
            elif cmd == "clear-startup":
                self.startup = None
            return HelperResult(True, {"mock": True}, "", describe(a))
        except (ValueError, KeyError) as e:
            return HelperResult(False, {}, str(e), describe(a))
