"""Is the NVIDIA driver actually usable right now? Explains *why not* in plain words.

The most common failure on Arch/CachyOS: pacman updates nvidia-utils (user-space libraries)
while the old kernel module stays loaded until reboot. Then NVML, nvidia-smi and Vulkan
all fail at once ("Driver/library version mismatch", vkEnumeratePhysicalDevices failed).
"""
from __future__ import annotations

import glob
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..core import runner

log = logging.getLogger(__name__)

PROC_VERSION = Path("/proc/driver/nvidia/version")


class Health(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"            # updated, not rebooted
    NOT_LOADED = "not_loaded"        # kernel module missing
    NOUVEAU = "nouveau"              # open-source nouveau driver in use
    NO_DEVICE = "no_device"          # driver loaded, no GPU visible
    ERROR = "error"                  # anything else nvidia-smi reports
    UNKNOWN = "unknown"              # no NVIDIA tools at all


@dataclass
class DriverHealth:
    state: Health
    title: str
    detail: str = ""
    fix: list[str] = field(default_factory=list)
    kernel_version: str | None = None
    userspace_version: str | None = None
    smi_message: str = ""
    can_reboot_fix: bool = False

    @property
    def ok(self) -> bool:
        return self.state == Health.OK


def parse_kernel_version(text: str) -> str | None:
    m = re.search(r"Kernel Module(?:\s+for\s+\S+)?\s+(\d+\.\d+(?:\.\d+)?)", text)
    return m.group(1) if m else None


def kernel_module_version(proc_text: str | None = None) -> str | None:
    if proc_text is None:
        try:
            proc_text = PROC_VERSION.read_text()
        except OSError:
            return None
    return parse_kernel_version(proc_text)


def userspace_version(pacman_out: str | None = None) -> str | None:
    """Version of the installed user-space driver (nvidia-utils), without the pkgrel."""
    if pacman_out is None:
        r = runner.run(["pacman", "-Q", "nvidia-utils"], timeout=5, quiet=True)
        pacman_out = r.out if r.ok else ""
    m = re.search(r"nvidia-utils\S*\s+(?:\d+:)?(\d+\.\d+(?:\.\d+)?)", pacman_out)
    if m:
        return m.group(1)
    libs = sorted(glob.glob("/usr/lib/libnvidia-ml.so.*.*")) + sorted(glob.glob("/usr/lib64/libnvidia-ml.so.*.*"))
    for lib in libs:
        mm = re.search(r"libnvidia-ml\.so\.(\d+\.\d+(?:\.\d+)?)$", lib)
        if mm:
            return mm.group(1)
    return None


def module_loaded(name: str) -> bool:
    return Path(f"/sys/module/{name}").exists()


def diagnose(smi_result: runner.Result | None = None, kernel_text: str | None = None,
             pacman_out: str | None = None, nouveau: bool | None = None) -> DriverHealth:
    """All arguments are injectable for tests; by default everything is read from the system."""
    kv = kernel_module_version(kernel_text)
    uv = userspace_version(pacman_out)
    if nouveau is None:
        nouveau = module_loaded("nouveau")
    if smi_result is None:
        smi_result = runner.run(["nvidia-smi", "-L"], timeout=8, quiet=True)
    msg = (smi_result.out + " " + smi_result.err).strip()
    low = msg.lower()
    base = dict(kernel_version=kv, userspace_version=uv, smi_message=msg)

    mismatch = (kv and uv and kv != uv) or "version mismatch" in low
    if mismatch:
        return DriverHealth(
            Health.MISMATCH, "NVIDIA driver updated — restart required",
            f"The driver files on disk are version {uv or '?'}, but the kernel is still running the old "
            f"driver {kv or '?'}. Until you restart, nvidia-smi, NVML and Vulkan can't talk to the GPU "
            "(games may not start, Smooth Motion and DLSS won't work).",
            ["Restart the computer. That loads the new driver and fixes it.",
             "If it still fails after a restart, reinstall the driver for your kernel: sudo chwd -a, then restart."],
            can_reboot_fix=True, **base)
    if nouveau and kv is None:
        return DriverHealth(
            Health.NOUVEAU, "The open-source 'nouveau' driver is in use",
            "NVIDIA's own driver isn't loaded, so tuning, DLSS, Smooth Motion and NVML are unavailable.",
            ["Install the NVIDIA driver: sudo chwd -a", "Restart the computer."], **base)
    if kv is None:
        if runner.which("nvidia-smi") is None and uv is None:
            return DriverHealth(Health.UNKNOWN, "No NVIDIA driver installed",
                                "Neither the NVIDIA kernel module nor nvidia-utils was found.",
                                ["Install the driver: sudo chwd -a", "Restart the computer."], **base)
        return DriverHealth(
            Health.NOT_LOADED, "NVIDIA kernel module isn't loaded",
            "The driver is installed but its kernel module didn't load. Common causes: the module wasn't "
            "rebuilt for a new kernel, Secure Boot blocked it, or nouveau grabbed the GPU first.",
            ["Restart once (a kernel update may be pending).",
             "Check the module: sudo modprobe nvidia, then journalctl -k -b | grep -i nvrm",
             "Reinstall for the current kernel: sudo chwd -a"], can_reboot_fix=True, **base)
    if smi_result.ok:
        return DriverHealth(Health.OK, f"Driver {kv} loaded and responding", **base)
    if "no devices were found" in low:
        return DriverHealth(Health.NO_DEVICE, "Driver loaded, but no GPU is visible",
                            "The GPU may have fallen off the bus or be disabled (laptop hybrid mode / BIOS).",
                            ["Check: journalctl -k -b | grep -i -E 'nvrm|xid'", "Restart the computer."], **base)
    if smi_result.code == 127:
        return DriverHealth(Health.OK, f"Driver {kv} loaded (nvidia-smi not installed)", **base)
    return DriverHealth(Health.ERROR, "nvidia-smi reports an error",
                        msg or f"nvidia-smi exited with code {smi_result.code} and printed nothing.",
                        ["Restart the computer.", "Check: journalctl -k -b | grep -i nvrm"], **base)


def mock_health() -> DriverHealth:
    return DriverHealth(Health.OK, "Driver 580.95.05 loaded and responding", kernel_version="580.95.05",
                        userspace_version="580.95.05")
