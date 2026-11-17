"""Backend interface. Backends only *read*; writes go through the privileged helper."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import GpuInfo, Telemetry, TuningCaps


class GpuBackend(ABC):
    name = "none"
    #: Human readable description of where data comes from.
    source = ""

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def gpus(self) -> list[GpuInfo]: ...

    @abstractmethod
    def telemetry(self, index: int) -> Telemetry: ...

    def tuning_caps(self, index: int) -> TuningCaps:
        return TuningCaps()

    def close(self) -> None:
        pass


class NullBackend(GpuBackend):
    name = "none"
    source = "No NVIDIA driver interface detected"

    def __init__(self, reason: str = ""):
        self.reason = reason

    def available(self) -> bool:
        return False

    def gpus(self) -> list[GpuInfo]:
        return []

    def telemetry(self, index: int) -> Telemetry:
        return Telemetry()
