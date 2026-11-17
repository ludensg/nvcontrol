"""Registry of external tools NV//CONTROL integrates with or launches."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core import runner


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    binaries: tuple[str, ...]
    packages: tuple[str, ...]
    repo: str               # extra | multilib | cachyos | aur | pypi | system
    description: str
    launch: tuple[str, ...] | None = None
    category: str = "gaming"
    recommended: bool = True
    note: str = ""

    @property
    def installable(self) -> bool:
        """Only official / CachyOS repo packages are offered for automatic install."""
        return self.repo in ("extra", "multilib", "cachyos")


TOOLS: list[Tool] = [
    Tool("nvidia-utils", "NVIDIA driver utilities", ("nvidia-smi",), ("nvidia-utils",), "extra",
         "nvidia-smi and libnvidia-ml (NVML). Provided by your NVIDIA driver package.",
         category="driver", note="On CachyOS installed by chwd together with the driver."),
    Tool("nvml-py", "NVML Python bindings", (), ("python-nvidia-ml-py",), "extra",
         "Fast, direct telemetry and tuning reads through NVML. Without it NV//CONTROL falls back to nvidia-smi.",
         category="driver"),
    Tool("lact", "LACT", ("lact",), ("lact",), "extra",
         "GPU control daemon + GUI: fan curves, power cap, clock offsets, profiles. Requires `systemctl enable --now lactd`.",
         launch=("lact", "gui"), category="tuning"),
    Tool("nvidia-settings", "NVIDIA Settings", ("nvidia-settings",), ("nvidia-settings",), "extra",
         "NVIDIA X Server Settings. Full functionality (vibrance, PowerMizer, color) only on X11.",
         launch=("nvidia-settings",), category="driver"),
    Tool("mangohud", "MangoHud", ("mangohud",), ("mangohud", "lib32-mangohud"), "multilib",
         "Vulkan/OpenGL performance overlay and FPS limiter.", category="performance"),
    Tool("goverlay", "GOverlay", ("goverlay",), ("goverlay",), "extra",
         "Graphical editor for MangoHud / vkBasalt.", launch=("goverlay",), category="performance"),
    Tool("gamescope", "Gamescope", ("gamescope",), ("gamescope",), "extra",
         "Micro-compositor: upscaling (FSR/NIS), resolution spoofing, frame limiting, HDR.",
         category="gaming"),
    Tool("gamemode", "Feral GameMode", ("gamemoderun",), ("gamemode", "lib32-gamemode"), "multilib",
         "Applies CPU governor / scheduling tweaks while games run.", category="gaming", recommended=False),
    Tool("steam", "Steam", ("steam",), ("steam",), "multilib",
         "Steam client (Proton, launch options).", launch=("steam",), category="gaming"),
    Tool("vulkan-tools", "Vulkan tools", ("vulkaninfo",), ("vulkan-tools",), "extra",
         "vulkaninfo for Vulkan diagnostics.", category="diagnostics"),
    Tool("kscreen", "KDE display config", ("kscreen-doctor",), ("kscreen",), "extra",
         "KDE output configuration (resolution, refresh, VRR, HDR, ICC, scale).",
         launch=("systemsettings", "kcm_kscreen"), category="display"),
    Tool("ddcutil", "ddcutil (DDC/CI)", ("ddcutil",), ("ddcutil",), "extra",
         "Changes the monitor's real backlight/contrast over DDC/CI. Needs i2c access (i2c group / i2c-dev).",
         category="display", recommended=False),
    Tool("proton-cachyos", "Proton-CachyOS", (), ("proton-cachyos",), "cachyos",
         "CachyOS-optimised Proton build (system-wide compatibility tool).",
         category="gaming", recommended=False),
    Tool("nvibrant", "nVibrant", ("nvibrant",), (), "pypi",
         "Digital Vibrance on Wayland through nvidia-modeset. Not in official repos.",
         category="display", recommended=False,
         note="Install with:  pipx install nvibrant   (or an AUR package). Must match your driver version."),
    Tool("protonup-qt", "ProtonUp-Qt", ("protonup-qt",), ("protonup-qt",), "aur",
         "Installs/updates GE-Proton and other compatibility tools.", launch=("protonup-qt",),
         category="gaming", recommended=False, note="AUR package; install with your AUR helper (paru/yay)."),
]

TOOLS_BY_ID = {t.id: t for t in TOOLS}


@dataclass
class ToolState:
    tool: Tool
    installed: bool
    path: str | None = None
    detail: str = ""
    extra: dict = field(default_factory=dict)


def installed_packages() -> set[str]:
    r = runner.run(["pacman", "-Qq"], timeout=10)
    return set(r.out.split()) if r.ok else set()


def nvml_py_available() -> bool:
    try:
        import pynvml  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def detect_tools(pkgs: set[str] | None = None) -> dict[str, ToolState]:
    pkgs = installed_packages() if pkgs is None else pkgs
    out: dict[str, ToolState] = {}
    for t in TOOLS:
        path = None
        for b in t.binaries:
            path = runner.which(b)
            if path:
                break
        if t.id == "nvml-py":
            inst = nvml_py_available()
        elif t.binaries:
            inst = path is not None
        else:
            inst = all(p in pkgs for p in t.packages)
        out[t.id] = ToolState(t, inst, path)
    return out


def install_command(packages: list[str]) -> list[str]:
    """The exact privileged command shown to the user before running it."""
    clean = [p for p in packages if p and all(c.isalnum() or c in "-_.+" for c in p)]
    return ["pkexec", "pacman", "-S", "--needed", "--noconfirm", *clean]


def launch_tool(tool_id: str) -> bool:
    t = TOOLS_BY_ID.get(tool_id)
    if not t or not t.launch:
        return False
    if tool_id == "lact" and runner.which("lact"):
        return runner.launch_detached(["lact", "gui"])
    return runner.launch_detached(list(t.launch))
