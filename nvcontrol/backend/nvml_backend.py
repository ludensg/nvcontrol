"""NVML backend (nvidia-ml-py / pynvml). Read-only in the GUI process."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import GpuBackend
from .models import (ARCH_NAMES, GpuInfo, OffsetRange, PowerLimits, Telemetry, ThresholdRange,
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
        caps.supported_mem_clocks = sorted({int(c) for c in mem_clocks})
        t = [self._try(N.nvmlDeviceGetTemperatureThreshold, h, getattr(N, k, -1)) for k in
             ("NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_MIN", "NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_MAX",
              "NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR")]
        if all(v is not None for v in t) and t[1] > t[0]:
            caps.temp_target = ThresholdRange(int(t[0]), int(t[1]), int(t[2]))
        pm = self._try(N.nvmlDeviceGetPersistenceMode, h)
        caps.persistence = None if pm is None else bool(pm)
        arch = self._try(N.nvmlDeviceGetArchitecture, h)
        # Locked clocks: Volta+ per NVML docs
        caps.supports_clock_lock = arch is not None and arch >= 5
        return caps

    def lab_sensors(self, index: int) -> list[tuple[str, str, str]]:
        if not self._ok or index >= len(self._handles):
            return []
        h, T, rows = self._handles[index], self._try, []

        def add(sec, lab, val, fmt="{}"):
            rows.append((sec, lab, "not supported" if val is None else fmt.format(val)))

        for lab, k in (("Slowdown", "SLOWDOWN"), ("Shutdown", "SHUTDOWN"), ("GPU max operating", "GPU_MAX"),
                       ("Memory max operating", "MEM_MAX"), ("Temperature target (current)", "ACOUSTIC_CURR"),
                       ("Temperature target range min", "ACOUSTIC_MIN"),
                       ("Temperature target range max", "ACOUSTIC_MAX")):
            add("THERMAL LIMITS", lab, T(N.nvmlDeviceGetTemperatureThreshold, h,
                                         getattr(N, f"NVML_TEMPERATURE_THRESHOLD_{k}", -1)), "{} °C")
        n = T(N.nvmlDeviceGetNumFans, h, default=0) or 0
        for i in range(n):
            add("FANS", f"Fan {i} speed", T(N.nvmlDeviceGetFanSpeed_v2, h, i), "{} %")
            add("FANS", f"Fan {i} target", T(N.nvmlDeviceGetTargetFanSpeed, h, i), "{} %")
        add("FANS", "Fan RPM (fan 0)", T(N.nvmlDeviceGetFanSpeedRPM, h), "{} rpm")
        mm = T(N.nvmlDeviceGetMinMaxFanSpeed, h)
        add("FANS", "Driver fan range", f"{mm[0]}–{mm[1]} %" if mm else None)
        add("PCIe", "Link (current)", T(lambda: f"Gen {N.nvmlDeviceGetCurrPcieLinkGeneration(h)} "
                                                f"x{N.nvmlDeviceGetCurrPcieLinkWidth(h)}"))
        add("PCIe", "Link (max)", T(lambda: f"Gen {N.nvmlDeviceGetMaxPcieLinkGeneration(h)} "
                                            f"x{N.nvmlDeviceGetMaxPcieLinkWidth(h)}"))
        add("PCIe", "TX throughput", T(N.nvmlDeviceGetPcieThroughput, h, N.NVML_PCIE_UTIL_TX_BYTES),
            "{} KB/s")
        add("PCIe", "RX throughput", T(N.nvmlDeviceGetPcieThroughput, h, N.NVML_PCIE_UTIL_RX_BYTES),
            "{} KB/s")
        bar = T(N.nvmlDeviceGetBAR1MemoryInfo, h)
        add("MEMORY", "BAR1 (Resizable BAR window)", f"{bar.bar1Used / 2**20:.0f} / {bar.bar1Total / 2**20:.0f} MiB"
            if bar else None)
        mems = T(N.nvmlDeviceGetSupportedMemoryClocks, h) or []
        add("MEMORY", "Supported memory clocks", ", ".join(str(m) for m in sorted(mems)) + " MHz" if mems else None)
        enc = T(N.nvmlDeviceGetEncoderUtilization, h)
        dec = T(N.nvmlDeviceGetDecoderUtilization, h)
        add("ENGINES", "NVENC (video encoder)", enc[0] if enc else None, "{} %")
        add("ENGINES", "NVDEC (video decoder)", dec[0] if dec else None, "{} %")
        e = T(N.nvmlDeviceGetTotalEnergyConsumption, h)
        add("POWER", "Energy since driver load", e / 3.6e9 if e is not None else None, "{:.3f} kWh")
        for lab, k in (("Time power-limited", "NVML_PERF_POLICY_POWER"),
                       ("Time thermal-limited", "NVML_PERF_POLICY_THERMAL")):
            v = T(N.nvmlDeviceGetViolationStatus, h, getattr(N, k, -1))
            add("POWER", lab, v.violationTime / 1e9 if v else None, "{:.1f} s")
        ps = T(N.nvmlDeviceGetSupportedPerformanceStates, h) or []
        for p in ps[:6]:
            r = T(N.nvmlDeviceGetMinMaxClockOfPState, h, N.NVML_CLOCK_GRAPHICS, p)
            add("P-STATES", f"P{p} core clock range", f"{r[0]}–{r[1]} MHz" if r else None)
        add("DRIVER", "Persistence mode", {1: "on", 0: "off"}.get(T(N.nvmlDeviceGetPersistenceMode, h)))
        add("DRIVER", "Display active", {1: "yes", 0: "no"}.get(T(N.nvmlDeviceGetDisplayActive, h)))
        add("DRIVER", "Max boost clock", T(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_GRAPHICS), "{} MHz")
        add("DRIVER", "Max memory clock", T(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_MEM), "{} MHz")
        return rows

    def close(self) -> None:
        if self._ok:
            self._try(N.nvmlShutdown)
            self._ok = False
