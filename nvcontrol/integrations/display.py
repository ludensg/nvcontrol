"""Display configuration: KDE (kscreen-doctor), X11 (xrandr, nvidia-settings),
Wayland vibrance (nvibrant) and real monitor controls (ddcutil / DDC/CI).

Important distinctions surfaced in the UI:
* kscreen brightness  = compositor-side dimming, NOT the monitor backlight
* ddcutil brightness  = the monitor's own luminance over DDC/CI
* nvidia-settings / nvibrant DigitalVibrance = driver-native saturation (display pipeline)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..core import runner

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
VRR_POLICIES = {0: "never", 1: "always", 2: "automatic"}

# libkscreen Output::Capability flags (KF6 / Plasma 6)
CAP_VRR = 0x2
CAP_HDR = 0x8
CAP_ICC = 0x40
CAP_BRIGHTNESS = 0x100


@dataclass
class Mode:
    id: str
    width: int
    height: int
    refresh: float

    @property
    def label(self) -> str:
        return f"{self.width}×{self.height} @ {self.refresh:.2f} Hz"


@dataclass
class Output:
    name: str
    connected: bool = True
    enabled: bool = True
    current_mode: Mode | None = None
    modes: list[Mode] = field(default_factory=list)
    pos: tuple[int, int] = (0, 0)
    scale: float = 1.0
    vrr_policy: str | None = None
    hdr: bool | None = None
    icc_profile: str | None = None
    brightness: int | None = None
    capabilities: int | None = None
    backend: str = "kscreen"

    def can(self, flag: int) -> bool | None:
        return None if self.capabilities is None else bool(self.capabilities & flag)


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


# ---------------------------------------------------------------- KDE / kscreen
def parse_kscreen_json(text: str) -> list[Output]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    outs = []
    for o in data.get("outputs", []):
        modes = []
        for m in o.get("modes", []):
            size = m.get("size", {})
            modes.append(Mode(str(m.get("id")), int(size.get("width", 0)),
                              int(size.get("height", 0)), float(m.get("refreshRate", 0))))
        cur = next((m for m in modes if m.id == str(o.get("currentModeId"))), None)
        pos = o.get("pos", {})
        b = o.get("brightness")
        outs.append(Output(
            name=o.get("name", "?"), connected=bool(o.get("connected", True)),
            enabled=bool(o.get("enabled", True)), current_mode=cur,
            modes=sorted(modes, key=lambda m: (-m.width * m.height, -m.refresh)),
            pos=(int(pos.get("x", 0)), int(pos.get("y", 0))),
            scale=float(o.get("scale", 1.0)),
            vrr_policy=VRR_POLICIES.get(o.get("vrrPolicy")) if "vrrPolicy" in o else None,
            hdr=o.get("hdr") if "hdr" in o else None,
            icc_profile=o.get("iccProfilePath") or None,
            brightness=int(round(b * 100)) if isinstance(b, float) and b <= 1.0 else (int(b) if b is not None else None),
            capabilities=o.get("capabilities"),
        ))
    return outs


def kscreen_outputs() -> list[Output]:
    if not runner.which("kscreen-doctor"):
        return []
    r = runner.run(["kscreen-doctor", "-j"], timeout=6)
    return [o for o in parse_kscreen_json(r.out) if o.connected] if r.ok else []


def kscreen_set(output: str, prop: str, value: str) -> runner.Result:
    """Build and run a single validated kscreen-doctor setting."""
    if not valid_name(output):
        return runner.Result(False, 2, "", "invalid output name")
    if prop == "mode" and not re.fullmatch(r"[0-9]+|\d{3,5}x\d{3,5}@\d{2,3}(\.\d+)?", value):
        return runner.Result(False, 2, "", "invalid mode")
    if prop == "scale":
        try:
            if not 0.5 <= float(value) <= 4.0:
                raise ValueError
        except ValueError:
            return runner.Result(False, 2, "", "invalid scale")
    if prop == "vrrpolicy" and value not in ("never", "always", "automatic"):
        return runner.Result(False, 2, "", "invalid VRR policy")
    if prop == "hdr" and value not in ("enable", "disable"):
        return runner.Result(False, 2, "", "invalid HDR value")
    if prop == "brightness" and not (value.isdigit() and 0 <= int(value) <= 100):
        return runner.Result(False, 2, "", "invalid brightness")
    if prop == "position" and not re.fullmatch(r"-?\d{1,5},-?\d{1,5}", value):
        return runner.Result(False, 2, "", "invalid position")
    if prop == "iccprofile" and (not value.startswith("/") or ".." in value or "\n" in value):
        return runner.Result(False, 2, "", "ICC profile must be an absolute path")
    if prop not in ("mode", "scale", "vrrpolicy", "hdr", "brightness", "position", "iccprofile", "enable", "disable"):
        return runner.Result(False, 2, "", "unsupported property")
    arg = f"output.{output}.{prop}" if prop in ("enable", "disable") else f"output.{output}.{prop}.{value}"
    return runner.run(["kscreen-doctor", arg], timeout=10)


def mode_arg(m: Mode) -> str:
    return m.id


# ---------------------------------------------------------------- X11
def xrandr_outputs() -> list[Output]:
    r = runner.run(["xrandr", "--query"], timeout=5)
    if not r.ok:
        return []
    outs: list[Output] = []
    cur: Output | None = None
    for line in r.out.splitlines():
        m = re.match(r"^(\S+) connected", line)
        if m:
            cur = Output(name=m.group(1), backend="xrandr")
            pm = re.search(r"\d+x\d+\+(-?\d+)\+(-?\d+)", line)
            if pm:
                cur.pos = (int(pm.group(1)), int(pm.group(2)))
            outs.append(cur)
            continue
        if re.match(r"^\S+ disconnected", line):
            cur = None
            continue
        mm = re.match(r"^\s+(\d+)x(\d+)\S*\s+(.*)$", line)
        if cur and mm:
            w, h = int(mm.group(1)), int(mm.group(2))
            for rate in re.finditer(r"(\d+\.\d+)(\*?)(\+?)", mm.group(3)):
                mode = Mode(f"{w}x{h}@{rate.group(1)}", w, h, float(rate.group(1)))
                cur.modes.append(mode)
                if rate.group(2) == "*":
                    cur.current_mode = mode
    return outs


def xrandr_set_mode(output: str, mode: Mode) -> runner.Result:
    if not valid_name(output):
        return runner.Result(False, 2, "", "invalid output")
    return runner.run(["xrandr", "--output", output, "--mode", f"{mode.width}x{mode.height}",
                       "--rate", f"{mode.refresh:.2f}"], timeout=10)


def nvsettings_query(attr: str, target: str | None = None) -> int | None:
    if not re.fullmatch(r"[A-Za-z]+", attr):
        return None
    spec = f"[DPY:{target}]/{attr}" if target else attr
    if target and not valid_name(target):
        return None
    r = runner.run(["nvidia-settings", "-q", spec, "-t"], timeout=5)
    try:
        return int(r.text.splitlines()[0]) if r.ok and r.text else None
    except ValueError:
        return None


def nvsettings_assign(attr: str, value: int, target: str | None = None) -> runner.Result:
    if not re.fullmatch(r"[A-Za-z]+", attr) or (target and not valid_name(target)):
        return runner.Result(False, 2, "", "invalid attribute/target")
    spec = f"[DPY:{target}]/{attr}={int(value)}" if target else f"{attr}={int(value)}"
    return runner.run(["nvidia-settings", "-a", spec], timeout=8)


# ---------------------------------------------------------------- Wayland vibrance
VIBRANCE_MIN, VIBRANCE_MAX = -1024, 1023


def nvibrant_set(values: list[int]) -> runner.Result:
    vals = [str(max(VIBRANCE_MIN, min(VIBRANCE_MAX, int(v)))) for v in values][:8]
    if not vals:
        return runner.Result(False, 2, "", "no values")
    return runner.run(["nvibrant", *vals], timeout=10)


# ---------------------------------------------------------------- DDC/CI
@dataclass
class DdcDisplay:
    number: int
    model: str


def ddc_displays() -> list[DdcDisplay]:
    r = runner.run(["ddcutil", "detect", "--brief"], timeout=15)
    if not r.ok:
        return []
    out, num = [], None
    for line in r.out.splitlines():
        m = re.match(r"^Display (\d+)", line)
        if m:
            num = int(m.group(1))
            continue
        mm = re.match(r"^\s+Monitor:\s+(.*)$", line)
        if mm and num is not None:
            out.append(DdcDisplay(num, mm.group(1).strip()))
            num = None
    return out


def ddc_get(display: int, vcp: int) -> tuple[int, int] | None:
    r = runner.run(["ddcutil", "getvcp", f"{vcp:x}", "--display", str(int(display)), "--brief"], timeout=10)
    m = re.search(r"C (\d+) (\d+)", r.out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def ddc_set(display: int, vcp: int, value: int) -> runner.Result:
    if vcp not in (0x10, 0x12):  # brightness, contrast only
        return runner.Result(False, 2, "", "only brightness/contrast are allowed")
    return runner.run(["ddcutil", "setvcp", f"{vcp:x}", str(max(0, min(100, int(value)))),
                       "--display", str(int(display))], timeout=10)
