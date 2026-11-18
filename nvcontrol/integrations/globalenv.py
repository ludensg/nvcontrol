"""Global graphics settings — the Linux counterpart of the NVIDIA App's *Global settings* list.

Windows applies driver profiles to every game. On Linux there's no single switch, so each setting
is translated into the layer that actually controls it:

* ``~/.config/environment.d/90-nvcontrol.conf``: session environment for every app started after
  the next login. NVIDIA OpenGL driver variables (__GL_*), NVIDIA shader cache, DXVK-NVAPI DLSS
  driver settings, Smooth Motion, and DXVK_CONFIG_FILE.
* ``~/.config/nvcontrol/dxvk.conf``: DXVK options for every Direct3D 8–11 game under Proton/Wine.

Per-game Steam launch options (Game Profiles) still override these for one game.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core.config import atomic_write, backup_file, config_dir, load_json, save_json

log = logging.getLogger(__name__)

ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
ENV_VAL = re.compile(r"^[A-Za-z0-9_.,:=/+\-]{0,200}$")
HEADER = "# Managed by NV//CONTROL (Global Graphics). Edit there, or delete this file to reset.\n"


def env_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "environment.d" / "90-nvcontrol.conf"


def dxvk_path() -> Path:
    return config_dir() / "dxvk.conf"


def state_path() -> Path:
    return config_dir() / "global-graphics.json"


DLSS_PRESETS = ["app", "render_preset_latest"] + [f"render_preset_{c}" for c in "abcdefghijklmno"]


@dataclass
class GlobalGraphics:
    """Values use NVIDIA App vocabulary; 'app' means application-controlled (= not set)."""
    # DLSS / RTX
    dlss_sr_preset: str = "app"
    dlss_rr_preset: str = "app"
    dlss_sr_mode: str = "app"          # app | dlaa | custom
    dlss_sr_ratio: int = 67            # % render scale when mode == custom (33-100)
    dlss_fg_override: bool = False
    dlss_mfg_count: str = "app"        # app | 2x | 3x | 4x (RTX 50 only)
    ngx_updater: bool = False
    dlss_indicator: bool = False
    smooth_motion: bool = False
    # latency / sync / frame rate
    low_latency: str = "off"           # off | on | ultra
    vsync: str = "app"                 # app | off | on
    max_fps: int = 0
    triple_buffering: str = "app"      # app | off | on
    # image quality
    anisotropic: str = "app"           # app | off | 2x | 4x | 8x | 16x
    negative_lod: str = "allow"        # allow | clamp
    threaded_optimization: str = "auto"  # auto | on | off
    shader_cache: str = "default"      # default | 10gb | 100gb | unlimited
    extra_env: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "GlobalGraphics":
        raw = load_json(state_path(), {})
        g = cls()
        for k, v in raw.items():
            if hasattr(g, k) and type(v) is type(getattr(g, k)):
                setattr(g, k, v)
        g.dlss_sr_ratio = max(33, min(100, g.dlss_sr_ratio))
        g.max_fps = max(0, min(1000, g.max_fps))
        return g

    def save(self) -> None:
        save_json(state_path(), self.__dict__)


def build(g: GlobalGraphics, smooth_motion_ok: bool, mfg_ok: bool) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Translate settings into (environment, dxvk.conf options, notes)."""
    env: dict[str, str] = {}
    dx: dict[str, str] = {}
    notes: list[str] = []

    # ---- DLSS (DXVK-NVAPI driver settings: Proton games only)
    if g.dlss_sr_preset in DLSS_PRESETS and g.dlss_sr_preset != "app":
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE"] = "on"
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION"] = g.dlss_sr_preset
    if g.dlss_rr_preset in DLSS_PRESETS and g.dlss_rr_preset != "app":
        env["DXVK_NVAPI_DRS_NGX_DLSS_RR_OVERRIDE"] = "on"
        env["DXVK_NVAPI_DRS_NGX_DLSS_RR_OVERRIDE_RENDER_PRESET_SELECTION"] = g.dlss_rr_preset
    if g.dlss_sr_mode == "dlaa":
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE"] = "dlaa"
    elif g.dlss_sr_mode == "custom":
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE"] = "custom"
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_SCALING_RATIO"] = str(max(33, min(100, g.dlss_sr_ratio)))
    if g.dlss_fg_override:
        env["DXVK_NVAPI_DRS_NGX_DLSS_FG_OVERRIDE"] = "on"
    if g.dlss_mfg_count in ("2x", "3x", "4x"):
        if mfg_ok:
            env["DXVK_NVAPI_DRS_NGX_DLSSG_MULTI_FRAME_COUNT"] = {"2x": "1", "3x": "2", "4x": "3"}[g.dlss_mfg_count]
        else:
            notes.append("Multi Frame Generation skipped: needs a GeForce RTX 50 GPU.")
    if g.ngx_updater:
        env["PROTON_ENABLE_NGX_UPDATER"] = "1"
    if g.dlss_indicator:
        env["DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS"] = "DLSSIndicator=1024,DLSSGIndicator=2"
    if g.smooth_motion:
        if smooth_motion_ok:
            env["NVPRESENT_ENABLE_SMOOTH_MOTION"] = "1"
            notes.append("Smooth Motion is on for EVERY Vulkan app (browsers and video players included). "
                         "Per-game is usually the better choice.")
            if g.dlss_fg_override:
                notes.append("Smooth Motion + DLSS Frame Generation compete. NVIDIA advises against using both.")
        else:
            notes.append("Smooth Motion skipped: this GPU/driver doesn't support it.")

    # ---- latency
    if g.low_latency in ("on", "ultra"):
        env["__GL_MaxFramesAllowed"] = "1"
        dx["dxgi.maxFrameLatency"] = "1"
        dx["d3d9.maxFrameLatency"] = "1"
        if g.low_latency == "ultra":
            notes.append("'Ultra' (just-in-time frame submission) is Windows-only; Linux uses the 'On' queue "
                         "depth of 1. Use NVIDIA Reflex in-game for the real thing.")
    # ---- V-Sync
    if g.vsync in ("on", "off"):
        on = g.vsync == "on"
        env["__GL_SYNC_TO_VBLANK"] = "1" if on else "0"
        dx["dxgi.syncInterval"] = "1" if on else "0"
        dx["d3d9.presentInterval"] = "1" if on else "0"
    # ---- frame cap
    if g.max_fps:
        dx["dxgi.maxFrameRate"] = str(g.max_fps)
        dx["d3d9.maxFrameRate"] = str(g.max_fps)
        env["VKD3D_FRAME_RATE"] = str(g.max_fps)
        notes.append("Max frame rate covers Direct3D games under Proton. For native Vulkan/OpenGL games use "
                     "MangoHud's limiter (PERFORMANCE page) or a per-game FPS limit.")
    # ---- triple buffering
    if g.triple_buffering in ("on", "off"):
        n = "3" if g.triple_buffering == "on" else "2"
        dx["dxgi.numBackBuffers"] = n
        dx["d3d9.numBackBuffers"] = n
    # ---- anisotropic filtering
    aniso = {"off": 0, "2x": 2, "4x": 4, "8x": 8, "16x": 16}.get(g.anisotropic)
    if aniso is not None:
        env["__GL_LOG_MAX_ANISO"] = str({0: 0, 2: 1, 4: 2, 8: 3, 16: 4}[aniso])
        dx["d3d11.samplerAnisotropy"] = str(aniso)
        dx["d3d9.samplerAnisotropy"] = str(aniso)
    if g.negative_lod == "clamp":
        dx["d3d11.clampNegativeLodBias"] = "True"
        dx["d3d9.clampNegativeLodBias"] = "True"
    # ---- threaded optimization (OpenGL)
    if g.threaded_optimization in ("on", "off"):
        env["__GL_THREADED_OPTIMIZATIONS"] = "1" if g.threaded_optimization == "on" else "0"
    # ---- shader cache (NVIDIA OpenGL + Vulkan driver cache)
    size = {"10gb": 10 * 1024 ** 3, "100gb": 100 * 1024 ** 3, "unlimited": 1024 ** 4}.get(g.shader_cache)
    if size:
        env["__GL_SHADER_DISK_CACHE_SIZE"] = str(size)
        env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] = "1"

    for k, v in (g.extra_env or {}).items():
        if ENV_KEY.match(k) and ENV_VAL.match(str(v)):
            env[k] = str(v)
        else:
            notes.append(f"Ignored invalid extra variable {k!r}.")
    if dx:
        env["DXVK_CONFIG_FILE"] = str(dxvk_path())
    return env, dx, notes


def render_env(env: dict[str, str]) -> str:
    for k, v in env.items():
        if not ENV_KEY.match(k) or not ENV_VAL.match(v):
            raise ValueError(f"unsafe environment entry {k}={v!r}")
    return HEADER + "".join(f"{k}={v}\n" for k, v in env.items())


def render_dxvk(dx: dict[str, str]) -> str:
    return "# Managed by NV//CONTROL (Global Graphics)\n" + "".join(f"{k} = {v}\n" for k, v in dx.items())


def write(env: dict[str, str], dx: dict[str, str]) -> list[Path]:
    """Write both files (with backups). Empty settings remove the files. Returns backups made."""
    backups = []
    for path, content, has in ((env_path(), render_env(env), bool(env)), (dxvk_path(), render_dxvk(dx), bool(dx))):
        if path.exists():
            b = backup_file(path, "global")
            if b:
                backups.append(b)
        if has:
            atomic_write(path, content)
            log.info("wrote %s (%d entries)", path, content.count("\n") - 1)
        elif path.exists():
            path.unlink()
            log.info("removed %s", path)
    return backups


def reset() -> None:
    for p in (env_path(), dxvk_path()):
        if p.exists():
            backup_file(p, "global")
            p.unlink()
    state_path().unlink(missing_ok=True)


def active_env() -> dict[str, str]:
    """What the *current* session sees (to tell the user a re-login is pending)."""
    return {k: v for k, v in os.environ.items() if k.startswith(("__GL_", "DXVK_", "NVPRESENT", "PROTON_", "VKD3D"))}
