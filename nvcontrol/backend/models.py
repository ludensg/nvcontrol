"""Plain data types shared by all GPU backends."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# NVML architecture IDs -> names
ARCH_NAMES = {
    2: "Kepler", 3: "Maxwell", 4: "Pascal", 5: "Volta", 6: "Turing",
    7: "Ampere", 8: "Ada Lovelace", 9: "Hopper", 10: "Blackwell",
}
# Order used for "at least this generation" checks
ARCH_ORDER = ["Kepler", "Maxwell", "Pascal", "Volta", "Turing",
              "Ampere", "Ada Lovelace", "Hopper", "Blackwell"]


def arch_rank(arch: str | None) -> int:
    if not arch:
        return -1
    try:
        return ARCH_ORDER.index(arch)
    except ValueError:
        return -1


def guess_arch_from_name(name: str) -> str | None:
    """Fallback when NVML is unavailable (nvidia-smi only)."""
    n = name.upper()
    m = re.search(r"RTX\s*(?:PRO\s*)?(\d{2})(\d{2})", n)
    if m:
        series = int(m.group(1))
        return {20: "Turing", 30: "Ampere", 40: "Ada Lovelace", 50: "Blackwell"}.get(series)
    if re.search(r"GTX\s*16\d\d", n):
        return "Turing"
    if re.search(r"GTX\s*10\d\d", n):
        return "Pascal"
    if re.search(r"GTX\s*9\d\d", n):
        return "Maxwell"
    return None


def rtx_series(name: str) -> int | None:
    """Return 20/30/40/50 for GeForce RTX cards, else None."""
    m = re.search(r"RTX\s*(\d{2})\d{2}", name.upper())
    return int(m.group(1)) if m else None


def parse_driver_version(v: str | None) -> tuple[int, ...]:
    if not v:
        return ()
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts)


@dataclass
class GpuInfo:
    index: int
    name: str
    uuid: str = ""
    arch: str | None = None
    vram_total_mb: int | None = None
    driver_version: str = ""
    cuda_version: str | None = None
    pci_bus_id: str = ""
    vbios: str | None = None
    open_kernel_module: bool | None = None
    fan_count: int = 0

    @property
    def is_rtx(self) -> bool:
        return rtx_series(self.name) is not None or "RTX" in self.name.upper()

    @property
    def rtx_series(self) -> int | None:
        return rtx_series(self.name)


@dataclass
class Telemetry:
    temp_c: float | None = None
    util_gpu: float | None = None
    util_mem: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    clock_gpu_mhz: float | None = None
    clock_mem_mhz: float | None = None
    clock_gpu_max_mhz: float | None = None
    clock_mem_max_mhz: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    fan_pct: float | None = None
    pstate: str | None = None
    throttle: list[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class PowerLimits:
    min_w: float
    max_w: float
    default_w: float
    current_w: float

    @property
    def adjustable(self) -> bool:
        return self.max_w - self.min_w >= 1.0


@dataclass
class OffsetRange:
    min_mhz: int
    max_mhz: int
    current_mhz: int

    @property
    def adjustable(self) -> bool:
        return self.max_mhz > self.min_mhz


@dataclass
class TuningCaps:
    """What the driver *reports* as adjustable. Writing still needs root (helper)."""
    power: PowerLimits | None = None
    gpc_offset: OffsetRange | None = None
    mem_offset: OffsetRange | None = None
    fan_count: int = 0
    fan_min_pct: int | None = None
    fan_max_pct: int | None = None
    supports_clock_lock: bool = False
    supported_gpu_clocks: list[int] = field(default_factory=list)
