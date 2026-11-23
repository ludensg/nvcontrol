"""Feature discovery: an honest matrix of what works on *this* machine.

Every entry states its status, the mechanism that controls it, and requirements.
Facts are taken from NVIDIA's Linux driver README / gaming guide, dxvk-nvapi docs,
LACT docs and KDE tooling — see docs/CAPABILITY_AUDIT.md for sources.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..backend.models import GpuInfo, TuningCaps, arch_rank, parse_driver_version
from .system import SystemInfo


class Status(str, Enum):
    OPERATIONAL = "Operational"
    NEEDS_CONFIG = "Needs configuration"
    EXTERNAL = "Via external app"
    PER_GAME = "Per-game"
    UNSUPPORTED = "Unsupported here"
    WINDOWS_ONLY = "Windows-only"


@dataclass
class Feature:
    id: str
    name: str
    category: str
    status: Status
    mechanism: str
    requirement: str = ""
    detail: str = ""
    scope: str = ""   # global | per-game | per-display | session

    @property
    def actionable(self) -> bool:
        return self.status in (Status.OPERATIONAL, Status.PER_GAME, Status.EXTERNAL)


SMOOTH_MOTION_RTX50_MIN = (575,)
SMOOTH_MOTION_RTX40_MIN = (580, 82, 7)


def smooth_motion_status(gpu: GpuInfo | None) -> tuple[Status, str]:
    if gpu is None:
        return Status.UNSUPPORTED, "No NVIDIA GPU detected."
    drv = parse_driver_version(gpu.driver_version)
    series = gpu.rtx_series
    if series == 50 or gpu.arch == "Blackwell":
        if drv >= SMOOTH_MOTION_RTX50_MIN:
            return Status.PER_GAME, "RTX 50 + driver ≥ 575: set per game (Vulkan / DXVK / VKD3D-Proton titles)."
        return Status.UNSUPPORTED, f"RTX 50 needs driver 575 or newer (installed: {gpu.driver_version})."
    if series == 40 or gpu.arch == "Ada Lovelace":
        if drv >= SMOOTH_MOTION_RTX40_MIN:
            return Status.PER_GAME, "RTX 40 + driver ≥ 580.82.07: set per game (Vulkan / DXVK / VKD3D-Proton titles)."
        return Status.UNSUPPORTED, f"RTX 40 needs driver 580.82.07 or newer (installed: {gpu.driver_version})."
    return Status.UNSUPPORTED, "NVIDIA Smooth Motion requires a GeForce RTX 40 or 50 series GPU."


def build_matrix(sysinfo: SystemInfo, gpu: GpuInfo | None, caps: TuningCaps,
                 backend_name: str) -> list[Feature]:
    F: list[Feature] = []
    add = F.append
    helper_ok = sysinfo.helper_installed and sysinfo.pkexec
    helper_msg = "" if helper_ok else "Privileged helper not installed (run install.sh) or pkexec missing."
    rank = arch_rank(gpu.arch if gpu else None)
    rtx = gpu.rtx_series if gpu else None

    # ---------------- Monitoring
    if backend_name in ("nvml", "mock"):
        add(Feature("telemetry", "Live telemetry", "Monitoring", Status.OPERATIONAL, "NVML",
                    detail="Temperature, load, clocks, VRAM, power, fan.", scope="global"))
    elif backend_name == "nvidia-smi":
        add(Feature("telemetry", "Live telemetry", "Monitoring", Status.OPERATIONAL, "nvidia-smi",
                    detail="Install python-nvidia-ml-py for faster polling and clock-offset readout.", scope="global"))
    else:
        add(Feature("telemetry", "Live telemetry", "Monitoring", Status.UNSUPPORTED, "—",
                    detail="No NVIDIA driver interface reachable (is the nvidia module loaded?).", scope="global"))

    # ---------------- Tuning
    p = caps.power
    if p and p.adjustable:
        add(Feature("power_limit", "Power limit", "GPU Tuning",
                    Status.OPERATIONAL if helper_ok else Status.NEEDS_CONFIG, "NVML / nvidia-smi -pl (root)",
                    f"Range {p.min_w:.0f}–{p.max_w:.0f} W (driver-enforced)", helper_msg, "global"))
    else:
        add(Feature("power_limit", "Power limit", "GPU Tuning", Status.UNSUPPORTED, "NVML",
                    detail="The driver does not expose an adjustable power limit (common on laptops; "
                           "use Dynamic Boost / power profiles instead).", scope="global"))

    for key, rng, label in (("gpc_offset", caps.gpc_offset, "GPU clock offset"),
                            ("mem_offset", caps.mem_offset, "Memory clock offset")):
        if rng and rng.adjustable:
            add(Feature(key, label, "GPU Tuning", Status.OPERATIONAL if helper_ok else Status.NEEDS_CONFIG,
                        "NVML VF offset (root)", f"{rng.min_mhz:+d} … {rng.max_mhz:+d} MHz",
                        helper_msg or "Works on Wayland and X11 (no Coolbits needed with NVML).", "global"))
        elif backend_name == "nvidia-smi":
            add(Feature(key, label, "GPU Tuning", Status.NEEDS_CONFIG, "NVML",
                        detail="Install python-nvidia-ml-py to read/write offsets.", scope="global"))
        else:
            add(Feature(key, label, "GPU Tuning", Status.UNSUPPORTED, "NVML",
                        detail="Driver reports no adjustable offset range for this GPU.", scope="global"))

    if caps.supports_clock_lock:
        add(Feature("clock_lock", "GPU clock locking", "GPU Tuning",
                    Status.OPERATIONAL if helper_ok else Status.NEEDS_CONFIG,
                    "nvidia-smi --lock-gpu-clocks (root)", "Volta or newer", helper_msg, "global"))
    else:
        add(Feature("clock_lock", "GPU clock locking", "GPU Tuning", Status.UNSUPPORTED, "nvidia-smi",
                    "Volta or newer", scope="global"))

    if caps.fan_count > 0:
        add(Feature("fan_manual", "Manual fan speed", "GPU Tuning",
                    Status.OPERATIONAL if helper_ok else Status.NEEDS_CONFIG,
                    "NVML nvmlDeviceSetFanSpeed_v2 (root)",
                    f"{caps.fan_count} fan(s), {caps.fan_min_pct or '?'}–{caps.fan_max_pct or 100}%",
                    helper_msg or "Driver minimum is enforced. Reset returns control to the VBIOS curve.", "global"))
        add(Feature("fan_curve", "Custom fan curve", "GPU Tuning",
                    Status.EXTERNAL if sysinfo.has("lact") else Status.NEEDS_CONFIG, "LACT daemon (lactd)",
                    "lact package + lactd service",
                    "A curve needs a daemon that keeps adjusting speed; LACT does this safely."
                    + ("" if sysinfo.lactd_active else " lactd is not running: sudo systemctl enable --now lactd"),
                    "global"))
    else:
        add(Feature("fan_manual", "Fan control", "GPU Tuning", Status.UNSUPPORTED, "NVML",
                    detail="No controllable fans reported (laptops: fans are managed by the EC/firmware).",
                    scope="global"))
    add(Feature("undervolt", "Undervolt / VF curve", "GPU Tuning",
                Status.EXTERNAL if sysinfo.has("lact") else Status.NEEDS_CONFIG, "LACT (indirect)",
                detail="NVIDIA exposes no direct voltage control on Linux. Undervolting is done indirectly: "
                       "positive clock offset + locked max clock (available here) or LACT's VF-curve tooling.",
                scope="global"))
    add(Feature("pstates", "Performance state (P-state)", "GPU Tuning", Status.OPERATIONAL, "NVML (read-only)",
                detail="Current P-state is shown live. PowerMizer 'Prefer maximum performance' is X11-only "
                       "(nvidia-settings GPUPowerMizerMode).", scope="global"))
    add(Feature("persistence", "Startup tuning profile", "GPU Tuning",
                Status.OPERATIONAL if helper_ok else Status.NEEDS_CONFIG, "systemd nvcontrol-apply.service",
                detail="Applied at boot by a root oneshot service with crash-loop protection.", scope="global"))

    # ---------------- Display
    kde = sysinfo.is_kde and sysinfo.has("kscreen")
    if kde:
        for fid, name in (("resolution", "Resolution & refresh rate"), ("scaling", "Scaling"),
                          ("arrangement", "Multi-monitor arrangement")):
            add(Feature(fid, name, "Display", Status.OPERATIONAL, "kscreen-doctor (KWin)", scope="per-display"))
        add(Feature("vrr", "Adaptive Sync / VRR (G-SYNC Compatible)", "Display", Status.OPERATIONAL,
                    "KWin VRR policy", detail="'Automatic' = fullscreen apps only. Native G-SYNC module monitors "
                    "also work through the same path on Wayland.", scope="per-display"))
        add(Feature("hdr", "HDR output", "Display", Status.OPERATIONAL, "KWin HDR (Plasma 6)",
                    detail="Requires an HDR-capable display and a recent driver; HDR is not the same as brightness.",
                    scope="per-display"))
        add(Feature("icc", "ICC color profiles", "Display", Status.OPERATIONAL, "KWin color management",
                    detail="Plasma ≥ 6.1.", scope="per-display"))
        add(Feature("sw_brightness", "Brightness (compositor)", "Display", Status.OPERATIONAL,
                    "KWin output brightness", detail="Software dimming in the compositor — not the backlight.",
                    scope="per-display"))
        add(Feature("color_temp", "Color temperature", "Display", Status.EXTERNAL, "KDE Night Light",
                    scope="session"))
    elif sysinfo.is_x11:
        add(Feature("resolution", "Resolution & refresh rate", "Display", Status.OPERATIONAL, "xrandr",
                    scope="per-display"))
        add(Feature("vrr", "G-SYNC / G-SYNC Compatible", "Display",
                    Status.EXTERNAL if sysinfo.has("nvidia-settings") else Status.NEEDS_CONFIG, "nvidia-settings",
                    scope="per-display"))
    else:
        add(Feature("resolution", "Resolution & refresh rate", "Display", Status.EXTERNAL,
                    "Your compositor's display settings", detail="Non-KDE Wayland: use your desktop's tool.",
                    scope="per-display"))

    if sysinfo.is_x11 and sysinfo.has("nvidia-settings"):
        add(Feature("vibrance", "Digital Vibrance", "Display", Status.OPERATIONAL,
                    "nvidia-settings DigitalVibrance (driver-native)", scope="per-display"))
        add(Feature("gamma", "Gamma / brightness / contrast (color correction)", "Display", Status.EXTERNAL,
                    "nvidia-settings color correction (X11)", scope="per-display"))
    elif sysinfo.is_wayland:
        add(Feature("vibrance", "Digital Vibrance", "Display",
                    Status.OPERATIONAL if sysinfo.has("nvibrant") else Status.NEEDS_CONFIG,
                    "nvibrant (nvidia-modeset, driver-native)",
                    detail="No KWin/NVIDIA API for vibrance on Wayland; nVibrant talks to nvidia-modeset directly. "
                           "Install: pipx install nvibrant", scope="per-display"))
        add(Feature("gamma", "Gamma / contrast", "Display", Status.UNSUPPORTED, "—",
                    detail="No driver or KWin gamma/contrast control on Wayland. Use an ICC profile, or DDC/CI "
                           "contrast for the monitor itself.", scope="per-display"))
    add(Feature("ddc", "Monitor brightness/contrast (DDC/CI)", "Display",
                Status.OPERATIONAL if sysinfo.has("ddcutil") else Status.NEEDS_CONFIG, "ddcutil",
                detail="Changes the monitor's real luminance. Needs i2c-dev + i2c group membership.",
                scope="per-display"))
    add(Feature("dsr", "DSR / DLDSR", "Display", Status.WINDOWS_ONLY, "—",
                detail="Not exposed by the Linux driver. Gamescope can render at a higher internal resolution "
                       "as a partial alternative.", scope="per-game"))

    # ---------------- RTX / Gaming
    dlss_ok = gpu is not None and (gpu.is_rtx or (rank >= arch_rank("Turing") and "GTX" not in gpu.name.upper()))
    status_dlss = Status.PER_GAME if dlss_ok else Status.UNSUPPORTED
    add(Feature("dlss_sr", "DLSS Super Resolution / DLAA", "RTX", status_dlss, "In-game setting",
                "GeForce RTX + game support; Proton with DXVK-NVAPI",
                "Quality mode / DLAA are chosen in the game's menu.", "per-game"))
    add(Feature("dlss_override", "DLSS preset / model override", "RTX", status_dlss,
                "DXVK-NVAPI DRS env vars (Proton)",
                "Proton with recent DXVK-NVAPI",
                "DXVK_NVAPI_DRS_NGX_DLSS_{SR,RR,FG}_OVERRIDE + *_RENDER_PRESET_SELECTION; optional "
                "PROTON_ENABLE_NGX_UPDATER=1 to fetch newer DLSS snippets. Native Linux games: game-controlled.",
                "per-game"))
    add(Feature("dlss_rr", "DLSS Ray Reconstruction", "RTX", status_dlss, "In-game setting (+ RR override)",
                "RTX + game support", scope="per-game"))
    fg_ok = rtx in (40, 50) or (gpu is not None and gpu.arch in ("Ada Lovelace", "Blackwell"))
    add(Feature("dlss_fg", "DLSS Frame Generation", "RTX", Status.PER_GAME if fg_ok else Status.UNSUPPORTED,
                "In-game setting", "RTX 40/50 + game support",
                "Do not combine with Smooth Motion.", "per-game"))
    mfg_ok = rtx == 50 or (gpu is not None and gpu.arch == "Blackwell")
    add(Feature("dlss_mfg", "DLSS Multi Frame Generation", "RTX", Status.PER_GAME if mfg_ok else Status.UNSUPPORTED,
                "In-game setting", "RTX 50 series", scope="per-game"))
    sm_status, sm_detail = smooth_motion_status(gpu)
    add(Feature("smooth_motion", "NVIDIA Smooth Motion", "RTX", sm_status, "NVPRESENT_ENABLE_SMOOTH_MOTION=1",
                "RTX 50 (575+) / RTX 40 (580.82.07+); Vulkan games and DX11/DX12 games under Proton",
                sm_detail + " Not for games that already use DLSS Frame Generation.", "per-game"))
    add(Feature("reflex", "NVIDIA Reflex", "RTX", Status.PER_GAME if gpu else Status.UNSUPPORTED,
                "In-game setting (DXVK-NVAPI + VK_NV_low_latency2)",
                "Game support; Proton DXVK-NVAPI (PROTON_ENABLE_NVAPI=1 on titles where it is off)", scope="per-game"))
    add(Feature("shader_cache", "Shader cache size", "RTX", Status.PER_GAME, "__GL_SHADER_DISK_CACHE_SIZE",
                detail="Per-game env var; can also be set globally via environment.d.", scope="per-game"))
    add(Feature("fps_limit", "Max frame rate", "Performance",
                Status.PER_GAME if sysinfo.has("mangohud") or sysinfo.has("gamescope") else Status.NEEDS_CONFIG,
                "MangoHud fps_limit / Gamescope -r", detail="No driver-level global FPS cap on Linux.",
                scope="per-game"))
    add(Feature("overlay", "Performance overlay", "Performance",
                Status.OPERATIONAL if sysinfo.has("mangohud") else Status.NEEDS_CONFIG, "MangoHud", scope="per-game"))
    add(Feature("low_latency", "Low Latency Mode (NULL)", "RTX", Status.WINDOWS_ONLY, "—",
                detail="Windows driver feature. Use Reflex in supported games; OpenGL titles can use "
                       "__GL_MaxFramesAllowed=1.", scope="per-game"))
    add(Feature("vsync", "V-Sync", "Performance", Status.PER_GAME, "Game / Gamescope / compositor",
                detail="Under Wayland the compositor presents; use in-game V-Sync or VRR.", scope="per-game"))
    for fid, name, alt in (("rtx_hdr", "RTX HDR", "Gamescope HDR / native HDR games"),
                           ("rtx_vsr", "RTX Video Super Resolution", "—"),
                           ("shadowplay", "Instant Replay / ShadowPlay", "OBS Studio or gpu-screen-recorder (NVENC)"),
                           ("freestyle", "Freestyle filters", "vkBasalt"),
                           ("nis", "NVIDIA Image Scaling (driver)", "Gamescope -F nis"),
                           ("ansel", "Ansel", "—")):
        add(Feature(fid, name, "Windows-only", Status.WINDOWS_ONLY, "—", detail=f"Linux alternative: {alt}",
                    scope="per-game"))
    return F
