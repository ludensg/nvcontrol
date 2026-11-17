"""nvidia-smi backend — fallback when the NVML Python bindings are missing."""
from __future__ import annotations

import time

from ..core import runner
from .base import GpuBackend
from .models import GpuInfo, PowerLimits, Telemetry, TuningCaps, guess_arch_from_name
from .nvml_backend import open_kernel_module

FIELDS = [
    "index", "name", "uuid", "driver_version", "memory.total", "memory.used",
    "temperature.gpu", "utilization.gpu", "utilization.memory", "clocks.gr",
    "clocks.mem", "clocks.max.gr", "clocks.max.mem", "power.draw",
    "power.limit", "power.min_limit", "power.max_limit", "power.default_limit",
    "fan.speed", "pstate", "pci.bus_id", "vbios_version",
]


def _num(v: str) -> float | None:
    v = v.strip()
    if not v or v.startswith("[") or v in ("N/A", "Not Supported"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_csv(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(", ")]
        if len(parts) != len(FIELDS):
            continue
        rows.append(dict(zip(FIELDS, parts)))
    return rows


class SmiBackend(GpuBackend):
    name = "nvidia-smi"
    source = "nvidia-smi (NVML bindings not installed — install python-nvidia-ml-py)"

    def __init__(self):
        self._rows: list[dict[str, str]] = []
        self._ok = runner.which("nvidia-smi") is not None and bool(self._query())
        self._cuda = None
        if self._ok:
            r = runner.run(["nvidia-smi"], timeout=5)
            for tok in r.out.split("CUDA Version:")[1:2]:
                self._cuda = tok.split()[0].strip("|")

    def _query(self) -> list[dict[str, str]]:
        r = runner.run(["nvidia-smi", f"--query-gpu={','.join(FIELDS)}",
                        "--format=csv,noheader,nounits"], timeout=5)
        self._rows = parse_csv(r.out) if r.ok else []
        return self._rows

    def available(self) -> bool:
        return self._ok

    def gpus(self) -> list[GpuInfo]:
        okm = open_kernel_module()
        out = []
        for r in self._rows or self._query():
            out.append(GpuInfo(
                index=int(r["index"]), name=r["name"], uuid=r["uuid"],
                arch=guess_arch_from_name(r["name"]),
                vram_total_mb=int(_num(r["memory.total"]) or 0) or None,
                driver_version=r["driver_version"], cuda_version=self._cuda,
                pci_bus_id=r["pci.bus_id"], vbios=r["vbios_version"],
                open_kernel_module=okm,
                fan_count=1 if _num(r["fan.speed"]) is not None else 0,
            ))
        return out

    def telemetry(self, index: int) -> Telemetry:
        rows = self._query()
        t = Telemetry(timestamp=time.time())
        if index >= len(rows):
            return t
        r = rows[index]
        t.temp_c = _num(r["temperature.gpu"])
        t.util_gpu = _num(r["utilization.gpu"])
        t.util_mem = _num(r["utilization.memory"])
        t.vram_used_mb = _num(r["memory.used"])
        t.vram_total_mb = _num(r["memory.total"])
        t.clock_gpu_mhz = _num(r["clocks.gr"])
        t.clock_mem_mhz = _num(r["clocks.mem"])
        t.clock_gpu_max_mhz = _num(r["clocks.max.gr"])
        t.clock_mem_max_mhz = _num(r["clocks.max.mem"])
        t.power_w = _num(r["power.draw"])
        t.power_limit_w = _num(r["power.limit"])
        t.fan_pct = _num(r["fan.speed"])
        t.pstate = r["pstate"] if r["pstate"].startswith("P") else None
        return t

    def tuning_caps(self, index: int) -> TuningCaps:
        caps = TuningCaps()
        rows = self._rows or self._query()
        if index < len(rows):
            r = rows[index]
            vals = [_num(r[k]) for k in ("power.min_limit", "power.max_limit",
                                         "power.default_limit", "power.limit")]
            if all(v is not None for v in vals):
                caps.power = PowerLimits(*vals)  # type: ignore[arg-type]
            caps.fan_count = 1 if _num(r["fan.speed"]) is not None else 0
            arch = guess_arch_from_name(r["name"])
            caps.supports_clock_lock = arch in ("Volta", "Turing", "Ampere", "Ada Lovelace", "Hopper", "Blackwell")
        # Clock offsets are only readable via NVML; leave None so the UI explains why.
        return caps
