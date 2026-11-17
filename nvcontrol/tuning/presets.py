"""Tuning presets, computed from what the detected hardware actually reports."""
from __future__ import annotations

from dataclasses import dataclass

from ..backend.models import TuningCaps

PRESET_NAMES = ["Balanced", "Maximum Performance", "Quiet Operation", "Power Efficient", "Custom"]

DESCRIPTIONS = {
    "Balanced": "Driver defaults: stock power limit, no offsets, automatic fans.",
    "Maximum Performance": "Power limit raised to the board maximum the driver allows. No overclock is applied.",
    "Quiet Operation": "Power limit 80 % of default — lower heat means the stock fan curve spins slower. "
                       "For a custom quiet curve use LACT.",
    "Power Efficient": "Power limit 70 % of default — typically loses far less performance than power.",
    "Custom": "Your own values from the GPU Tuning page.",
}


@dataclass
class TuningSettings:
    power_w: float | None = None
    core_offset: int | None = None
    mem_offset: int | None = None
    lock_min: int | None = None
    lock_max: int | None = None
    fan_pct: int | None = None   # None = automatic

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def preset_settings(name: str, caps: TuningCaps) -> tuple[TuningSettings, list[str]]:
    """Returns settings + notes about what was skipped because hardware lacks it."""
    s, notes = TuningSettings(), []
    p = caps.power
    if not (p and p.adjustable):
        if name not in ("Balanced", "Custom"):
            notes.append("Power limit is not adjustable on this GPU — preset has no effect.")
        return s, notes

    def clamp(w: float) -> float:
        return round(max(p.min_w, min(p.max_w, w)))

    if name == "Balanced":
        s.power_w = p.default_w
        if caps.gpc_offset:
            s.core_offset = 0
        if caps.mem_offset:
            s.mem_offset = 0
    elif name == "Maximum Performance":
        s.power_w = p.max_w
    elif name == "Quiet Operation":
        s.power_w = clamp(p.default_w * 0.8)
    elif name == "Power Efficient":
        s.power_w = clamp(p.default_w * 0.7)
    if s.power_w is not None and s.power_w == p.min_w and name in ("Quiet Operation", "Power Efficient"):
        notes.append(f"Clamped to the driver minimum of {p.min_w:.0f} W.")
    return s, notes
