from __future__ import annotations

import os

from .base import GpuBackend, NullBackend


def get_backend(mock: bool | None = None) -> GpuBackend:
    """NVML first, nvidia-smi second, Null last. Mock when requested."""
    if mock is None:
        mock = os.environ.get("NVCONTROL_MOCK", "") not in ("", "0")
    if mock:
        from .mock import MockBackend
        return MockBackend()
    from .nvml_backend import NvmlBackend
    b = NvmlBackend()
    if b.available():
        return b
    from .smi_backend import SmiBackend
    s = SmiBackend()
    if s.available():
        return s
    return NullBackend("Neither NVML nor nvidia-smi could talk to an NVIDIA driver.")
