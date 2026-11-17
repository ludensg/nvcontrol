"""Mock GPU for development, demos and automated tests (NVCONTROL_MOCK=1 or --mock)."""
from __future__ import annotations

import math
import random
import time

from .base import GpuBackend
from .models import GpuInfo, OffsetRange, PowerLimits, Telemetry, TuningCaps


class MockBackend(GpuBackend):
    name = "mock"
    source = "Simulated GPU (mock mode — no hardware is touched)"

    def __init__(self, name: str = "NVIDIA GeForce RTX 4080 SUPER", driver: str = "580.95.05",
                 arch: str = "Ada Lovelace", vram_mb: int = 16376, fans: int = 2):
        self._info = GpuInfo(
            index=0, name=name, uuid="GPU-00000000-mock-0000-0000-000000000000",
            arch=arch, vram_total_mb=vram_mb, driver_version=driver, cuda_version="13.0",
            pci_bus_id="00000000:01:00.0", vbios="95.03.3C.00.00", open_kernel_module=True,
            fan_count=fans,
        )
        # State that the mock helper mutates
        self.power_limit = 320.0
        self.gpc_offset = 0
        self.mem_offset = 0
        self.fan_manual: int | None = None
        self.locked: tuple[int, int] | None = None
        self._t0 = time.time()
        self._rng = random.Random(42)

    def available(self) -> bool:
        return True

    def gpus(self) -> list[GpuInfo]:
        return [self._info]

    def telemetry(self, index: int) -> Telemetry:
        t = time.time() - self._t0
        load = 0.5 + 0.45 * math.sin(t / 7.0) + self._rng.uniform(-0.05, 0.05)
        load = max(0.02, min(1.0, load))
        temp = 38 + 38 * load + 2 * math.sin(t / 3)
        clock = 210 + (2610 + self.gpc_offset - 210) * min(1, load * 1.3)
        if self.locked:
            clock = max(self.locked[0], min(self.locked[1], clock))
        fan = self.fan_manual if self.fan_manual is not None else (0 if temp < 50 else 30 + (temp - 50) * 1.5)
        power = min(self.power_limit, 18 + 300 * load)
        return Telemetry(
            temp_c=round(temp, 1), util_gpu=round(load * 100), util_mem=round(load * 60),
            vram_used_mb=1800 + 9000 * load, vram_total_mb=self._info.vram_total_mb,
            clock_gpu_mhz=round(clock), clock_mem_mhz=round(405 + (11501 - 405) * min(1, load * 2)),
            clock_gpu_max_mhz=3105, clock_mem_max_mhz=11501,
            power_w=round(power, 1), power_limit_w=self.power_limit,
            fan_pct=round(min(100, fan)), pstate="P0" if load > 0.3 else "P8",
            throttle=["SW power cap"] if power >= self.power_limit - 1 else [],
            timestamp=time.time(),
        )

    def tuning_caps(self, index: int) -> TuningCaps:
        return TuningCaps(
            power=PowerLimits(125.0, 352.0, 320.0, self.power_limit),
            gpc_offset=OffsetRange(-1000, 1000, self.gpc_offset),
            mem_offset=OffsetRange(-2000, 6000, self.mem_offset),
            fan_count=self._info.fan_count, fan_min_pct=30, fan_max_pct=100,
            supports_clock_lock=True,
            supported_gpu_clocks=list(range(210, 3106, 15)),
        )
