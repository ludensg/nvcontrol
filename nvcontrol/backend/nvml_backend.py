"""NVML backend (nvidia-ml-py / pynvml). Read-only in the GUI process."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import GpuBackend
from .models import (ARCH_NAMES, GpuInfo, OffsetRange, PowerLimits, Telemetry,
                     TuningCaps, guess_arch_from_name)

log = logging.getLogger(__name__)

try:  # pragma: no cover - depends on host
    import pynvml as N
except Exception:  # noqa: BLE001
    N = None

THROTTLE_BITS = {
    0x1: "GPU idle", 0x2: "App clocks setting", 0x4: "SW power cap",
    0x8: "HW slowdown", 0x10: "Sync boost", 0x20: "SW thermal",
    0x40: "HW thermal", 0x80: "HW power brake", 0x100: "Display clock",
}


def _s(v):
    return v.decode() if isinstance(v, bytes) else v


def open_kernel_module() -> bool | None:
    try:
        txt = Path("/proc/driver/nvidia/version").read_text()
        return "Open Kernel Module" in txt
    except OSError:
        return None


class NvmlBackend(GpuBackend):
    name = "nvml"
    source = "NVIDIA Management Library (libnvidia-ml)"

    def __init__(self):
        self._ok = False
        self._handles = []
        if N is None:
            return
        try:
            N.nvmlInit()
            count = N.nvmlDeviceGetCount()
            self._handles = [N.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
            self._ok = count > 0
        except Exception as e:  # noqa: BLE001
            log.info("NVML unavailable: %s", e)
            self._ok = False

    def available(self) -> bool:
        return self._ok

    @staticmethod
    def _try(fn, *a, default=None):
        try:
            return fn(*a)
        except Exception:  # noqa: BLE001 - NVMLError_NotSupported etc.
            return default

    def gpus(self) -> list[GpuInfo]:
        out = []
        if not self._ok:
            return out
        drv = _s(self._try(N.nvmlSystemGetDriverVersion, default="")) or ""
        cuda = self._try(N.nvmlSystemGetCudaDriverVersion_v2) or self._try(N.nvmlSystemGetCudaDriverVersion)
        cuda_s = f"{cuda // 1000}.{(cuda % 1000) // 10}" if cuda else None
        okm = open_kernel_module()
        for i, h in enumerate(self._handles):
            name = _s(self._try(N.nvmlDeviceGetName, h, default="NVIDIA GPU"))
            arch_id = self._try(N.nvmlDeviceGetArchitecture, h)
            arch = ARCH_NAMES.get(arch_id) if arch_id is not None else None
            mem = self._try(N.nvmlDeviceGetMemoryInfo, h)
            pci = self._try(N.nvmlDeviceGetPciInfo, h)
            out.append(GpuInfo(
                index=i,
                name=name,
                uuid=_s(self._try(N.nvmlDeviceGetUUID, h, default="")),
                arch=arch or guess_arch_from_name(name),
                vram_total_mb=int(mem.total / 1048576) if mem else None,
                driver_version=drv,
                cuda_version=cuda_s,
                pci_bus_id=_s(pci.busId) if pci else "",
                vbios=_s(self._try(N.nvmlDeviceGetVbiosVersion, h)),
                open_kernel_module=okm,
                fan_count=self._try(N.nvmlDeviceGetNumFans, h, default=0) or 0,
            ))
        return out

    def telemetry(self, index: int) -> Telemetry:
        t = Telemetry(timestamp=time.time())
        if not self._ok or index >= len(self._handles):
            return t
        h = self._handles[index]
        t.temp_c = self._try(N.nvmlDeviceGetTemperature, h, N.NVML_TEMPERATURE_GPU)
        u = self._try(N.nvmlDeviceGetUtilizationRates, h)
        if u:
            t.util_gpu, t.util_mem = float(u.gpu), float(u.memory)
        m = self._try(N.nvmlDeviceGetMemoryInfo, h)
        if m:
            t.vram_used_mb, t.vram_total_mb = m.used / 1048576, m.total / 1048576
        t.clock_gpu_mhz = self._try(N.nvmlDeviceGetClockInfo, h, N.NVML_CLOCK_GRAPHICS)
        t.clock_mem_mhz = self._try(N.nvmlDeviceGetClockInfo, h, N.NVML_CLOCK_MEM)
        t.clock_gpu_max_mhz = self._try(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_GRAPHICS)
        t.clock_mem_max_mhz = self._try(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_MEM)
        p = self._try(N.nvmlDeviceGetPowerUsage, h)
        t.power_w = p / 1000 if p is not None else None
        pl = self._try(N.nvmlDeviceGetEnforcedPowerLimit, h)
        t.power_limit_w = pl / 1000 if pl is not None else None
        t.fan_pct = self._try(N.nvmlDeviceGetFanSpeed, h)
        ps = self._try(N.nvmlDeviceGetPerformanceState, h)
        t.pstate = f"P{ps}" if ps is not None else None
        reasons = self._try(N.nvmlDeviceGetCurrentClocksEventReasons, h)
        if reasons is None:
            reasons = self._try(N.nvmlDeviceGetCurrentClocksThrottleReasons, h)
        if reasons:
            t.throttle = [v for k, v in THROTTLE_BITS.items() if reasons & k]
        return t

    def tuning_caps(self, index: int) -> TuningCaps:
        caps = TuningCaps()
        if not self._ok or index >= len(self._handles):
            return caps
        h = self._handles[index]
        cons = self._try(N.nvmlDeviceGetPowerManagementLimitConstraints, h)
        dflt = self._try(N.nvmlDeviceGetPowerManagementDefaultLimit, h)
        cur = self._try(N.nvmlDeviceGetPowerManagementLimit, h)
        if cons and dflt and cur:
            caps.power = PowerLimits(cons[0] / 1000, cons[1] / 1000, dflt / 1000, cur / 1000)
        g = self._try(N.nvmlDeviceGetGpcClkMinMaxVfOffset, h)
        gc = self._try(N.nvmlDeviceGetGpcClkVfOffset, h)
        if g and gc is not None:
            caps.gpc_offset = OffsetRange(int(g[0]), int(g[1]), int(gc))
        mm = self._try(N.nvmlDeviceGetMemClkMinMaxVfOffset, h)
        mc = self._try(N.nvmlDeviceGetMemClkVfOffset, h)
        if mm and mc is not None:
            caps.mem_offset = OffsetRange(int(mm[0]), int(mm[1]), int(mc))
        caps.fan_count = self._try(N.nvmlDeviceGetNumFans, h, default=0) or 0
        fr = self._try(N.nvmlDeviceGetMinMaxFanSpeed, h)
        if fr:
            caps.fan_min_pct, caps.fan_max_pct = int(fr[0]), int(fr[1])
        mem_clocks = self._try(N.nvmlDeviceGetSupportedMemoryClocks, h) or []
        clocks = (self._try(N.nvmlDeviceGetSupportedGraphicsClocks, h, max(mem_clocks))
                  if mem_clocks else None)
        if clocks:
            caps.supported_gpu_clocks = sorted({int(c) for c in clocks})
        arch = self._try(N.nvmlDeviceGetArchitecture, h)
        # Locked clocks: Volta+ per NVML docs
        caps.supports_clock_lock = arch is not None and arch >= 5
        return caps

    def close(self) -> None:
        if self._ok:
            self._try(N.nvmlShutdown)
            self._ok = False
