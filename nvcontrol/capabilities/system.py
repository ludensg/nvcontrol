"""System inspection: desktop, session, kernel, Vulkan, displays, packages."""
from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core import runner
from ..integrations import display as disp
from ..integrations.tools import ToolState, detect_tools, installed_packages

HELPER_PATH = "/usr/lib/nvcontrol/nvcontrol-helper"


@dataclass
class SystemInfo:
    distro: str = "Unknown"
    kernel: str = ""
    desktop: str = ""
    session: str = ""           # wayland | x11 | tty
    plasma_version: str | None = None
    vulkan_ok: bool = False
    vulkan_device: str | None = None
    vulkan_api: str | None = None
    nvidia_icd: bool = False
    nvidia_drm_modeset: bool | None = None
    nvidia_drm_fbdev: bool | None = None
    displays: list[disp.Output] = field(default_factory=list)
    packages: set[str] = field(default_factory=set)
    tools: dict[str, ToolState] = field(default_factory=dict)
    helper_installed: bool = False
    pkexec: bool = False
    lactd_active: bool = False

    @property
    def is_wayland(self) -> bool:
        return self.session == "wayland"

    @property
    def is_x11(self) -> bool:
        return self.session == "x11"

    @property
    def is_kde(self) -> bool:
        return "KDE" in self.desktop.upper()

    def has(self, tool_id: str) -> bool:
        t = self.tools.get(tool_id)
        return bool(t and t.installed)


def _os_release() -> str:
    try:
        txt = Path("/etc/os-release").read_text()
        m = re.search(r'^PRETTY_NAME="?([^"\n]+)', txt, re.M)
        return m.group(1) if m else "Linux"
    except OSError:
        return "Linux"


def _param(path: str) -> bool | None:
    try:
        v = Path(path).read_text().strip()
        return v in ("Y", "1")
    except OSError:
        return None


def detect_vulkan() -> tuple[bool, str | None, str | None, bool]:
    icd = any(Path(p).exists() for p in (
        "/usr/share/vulkan/icd.d/nvidia_icd.json", "/etc/vulkan/icd.d/nvidia_icd.json"))
    if not runner.which("vulkaninfo"):
        return icd, None, None, icd
    r = runner.run(["vulkaninfo", "--summary"], timeout=10)
    devs = re.findall(r"deviceName\s*=\s*(.+)", r.out)
    apis = re.findall(r"apiVersion\s*=\s*(\S+)", r.out)
    nv = next((i for i, d in enumerate(devs) if "NVIDIA" in d.upper()), None)
    if nv is not None:
        return True, devs[nv].strip(), apis[nv] if nv < len(apis) else None, icd
    return bool(devs), devs[0].strip() if devs else None, apis[0] if apis else None, icd


def detect(pkgs: set[str] | None = None) -> SystemInfo:
    s = SystemInfo()
    s.distro = _os_release()
    s.kernel = platform.release()
    s.desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "")
    st = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if not st:
        st = "wayland" if os.environ.get("WAYLAND_DISPLAY") else ("x11" if os.environ.get("DISPLAY") else "tty")
    s.session = st
    if runner.which("plasmashell"):
        r = runner.run(["plasmashell", "--version"], timeout=5)
        m = re.search(r"(\d+\.\d+(\.\d+)?)", r.out)
        s.plasma_version = m.group(1) if m else None
    s.vulkan_ok, s.vulkan_device, s.vulkan_api, s.nvidia_icd = detect_vulkan()
    s.nvidia_drm_modeset = _param("/sys/module/nvidia_drm/parameters/modeset")
    s.nvidia_drm_fbdev = _param("/sys/module/nvidia_drm/parameters/fbdev")
    s.packages = installed_packages() if pkgs is None else pkgs
    s.tools = detect_tools(s.packages)
    if s.is_kde and s.has("kscreen"):
        s.displays = disp.kscreen_outputs()
    elif s.is_x11 and runner.which("xrandr"):
        s.displays = disp.xrandr_outputs()
    s.helper_installed = os.access(HELPER_PATH, os.X_OK)
    s.pkexec = runner.which("pkexec") is not None
    if runner.which("systemctl"):
        s.lactd_active = runner.run(["systemctl", "is-active", "--quiet", "lactd"], timeout=4, quiet=True).ok
    return s


def mock_system() -> SystemInfo:
    """Representative CachyOS KDE Wayland machine for --mock mode and tests."""
    from ..integrations.tools import TOOLS, ToolState
    s = SystemInfo(distro="CachyOS Linux (mock)", kernel="6.17.8-2-cachyos", desktop="KDE",
                   session="wayland", plasma_version="6.5.3", vulkan_ok=True,
                   vulkan_device="NVIDIA GeForce RTX 4080 SUPER", vulkan_api="1.4.312",
                   nvidia_icd=True, nvidia_drm_modeset=True, nvidia_drm_fbdev=True,
                   helper_installed=True, pkexec=True, lactd_active=True)
    have = {"nvidia-utils", "nvml-py", "lact", "nvidia-settings", "mangohud", "steam",
            "vulkan-tools", "kscreen", "gamescope", "nvibrant"}
    s.tools = {t.id: ToolState(t, t.id in have, f"/usr/bin/{t.binaries[0]}" if t.binaries and t.id in have else None)
               for t in TOOLS}
    m1 = disp.Mode("1", 2560, 1440, 164.96)
    m2 = disp.Mode("2", 2560, 1440, 143.97)
    m3 = disp.Mode("3", 1920, 1080, 60.0)
    s.displays = [
        disp.Output("DP-1", current_mode=m1, modes=[m1, m2, m3], vrr_policy="automatic",
                    hdr=False, scale=1.0, brightness=100, capabilities=0x1FF),
        disp.Output("HDMI-A-1", current_mode=m3, modes=[m3], pos=(2560, 0), vrr_policy="never",
                    hdr=False, scale=1.0, capabilities=0x3),
    ]
    return s
