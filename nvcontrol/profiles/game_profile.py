"""Per-game profiles and the Steam launch-option builder."""
from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass, field, fields

ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
DLSS_PRESETS = ["default", "render_preset_latest"] + [f"render_preset_{c}" for c in "abcdefghijklmno"]
GAMESCOPE_FILTERS = ["", "fsr", "nis", "linear", "pixel"]


@dataclass
class GameProfile:
    appid: str = ""
    name: str = ""
    proton: str | None = None             # compat tool internal name; None = leave Steam's choice
    # NVIDIA / Proton
    enable_nvapi: bool = False            # PROTON_ENABLE_NVAPI=1
    smooth_motion: bool = False           # NVPRESENT_ENABLE_SMOOTH_MOTION=1
    ngx_updater: bool = False             # PROTON_ENABLE_NGX_UPDATER=1
    dlss_sr_override: bool = False
    dlss_sr_preset: str = "default"
    dlss_sr_mode: str = "app"              # app | dlaa | custom
    dlss_sr_ratio: int = 67                # render scale % for custom
    dlss_rr_override: bool = False
    dlss_rr_preset: str = "default"
    dlss_fg_override: bool = False
    dlss_indicator: bool = False
    shader_cache_gb: int = 0              # 0 = driver default
    # Performance
    mangohud: bool = False
    mangohud_preset: str = "Standard"
    fps_limit: int = 0
    gamemode: bool = False
    gamescope: bool = False
    gs_width: int = 0
    gs_height: int = 0
    gs_render_width: int = 0
    gs_render_height: int = 0
    gs_refresh: int = 0
    gs_fullscreen: bool = True
    gs_filter: str = ""
    gs_hdr: bool = False
    # Free-form
    extra_env: dict[str, str] = field(default_factory=dict)
    game_args: str = ""
    gpu_profile: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GameProfile":
        known = {f.name for f in fields(cls)}
        p = cls(**{k: v for k, v in d.items() if k in known})
        p.validate()
        return p

    def validate(self) -> None:
        if self.appid and not str(self.appid).isdigit():
            raise ValueError("appid must be numeric")
        for attr in ("dlss_sr_preset", "dlss_rr_preset"):
            if getattr(self, attr) not in DLSS_PRESETS:
                setattr(self, attr, "default")
        if self.dlss_sr_mode not in ("app", "dlaa", "custom"):
            self.dlss_sr_mode = "app"
        self.dlss_sr_ratio = max(33, min(100, int(self.dlss_sr_ratio or 67)))
        if self.gs_filter not in GAMESCOPE_FILTERS:
            self.gs_filter = ""
        for attr in ("fps_limit", "gs_width", "gs_height", "gs_render_width", "gs_render_height",
                     "gs_refresh", "shader_cache_gb"):
            v = int(getattr(self, attr) or 0)
            setattr(self, attr, max(0, min(v, 16384)))
        self.extra_env = {str(k): str(v) for k, v in (self.extra_env or {}).items()}


@dataclass
class BuildResult:
    options: str
    env: dict[str, str]
    wrappers: list[str]
    warnings: list[str]
    mangohud_changes: dict | None   # MangoHud config to write for this profile, if any


def build_launch_options(p: GameProfile, smooth_motion_allowed: bool,
                         mangohud_config_path: str | None = None) -> BuildResult:
    """Produce the exact Steam launch option string for a profile.

    Steam runs launch options through /bin/sh, so every value is shell-quoted.
    """
    p.validate()
    warn: list[str] = []
    env: dict[str, str] = {}

    if p.enable_nvapi:
        env["PROTON_ENABLE_NVAPI"] = "1"
    if p.ngx_updater:
        env["PROTON_ENABLE_NGX_UPDATER"] = "1"
    any_dlss = p.dlss_sr_override or p.dlss_rr_override or p.dlss_fg_override or p.dlss_sr_mode != "app"
    if p.dlss_sr_override:
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE"] = "on"
        if p.dlss_sr_preset != "default":
            env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION"] = p.dlss_sr_preset
    if p.dlss_sr_mode == "dlaa":
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE"] = "dlaa"
    elif p.dlss_sr_mode == "custom":
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE"] = "custom"
        env["DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_SCALING_RATIO"] = str(p.dlss_sr_ratio)
    if p.dlss_rr_override:
        env["DXVK_NVAPI_DRS_NGX_DLSS_RR_OVERRIDE"] = "on"
        if p.dlss_rr_preset != "default":
            env["DXVK_NVAPI_DRS_NGX_DLSS_RR_OVERRIDE_RENDER_PRESET_SELECTION"] = p.dlss_rr_preset
    if p.dlss_fg_override:
        env["DXVK_NVAPI_DRS_NGX_DLSS_FG_OVERRIDE"] = "on"
    if p.dlss_indicator:
        env["DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS"] = "DLSSIndicator=1024,DLSSGIndicator=2"
    if any_dlss and not p.ngx_updater:
        warn.append("DLSS overrides only take effect if the game's DLSS version supports the chosen preset; "
                    "enable the NGX updater if the indicator shows an old version.")

    if p.smooth_motion:
        if smooth_motion_allowed:
            env["NVPRESENT_ENABLE_SMOOTH_MOTION"] = "1"
            if p.dlss_fg_override:
                warn.append("Smooth Motion and DLSS Frame Generation compete — NVIDIA advises not to use both.")
        else:
            warn.append("Smooth Motion skipped: this GPU/driver combination does not support it.")

    if p.shader_cache_gb:
        env["__GL_SHADER_DISK_CACHE_SIZE"] = str(p.shader_cache_gb * 1024 ** 3)
        env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] = "1"

    use_mh_wrapper = (p.mangohud or (p.fps_limit and not p.gamescope)) and not p.gamescope
    mh_changes = None
    if p.mangohud or (p.fps_limit and not p.gamescope):
        from ..integrations.mangohud import PRESETS
        mh_changes = dict(PRESETS.get(p.mangohud_preset, PRESETS["Standard"]))
        mh_changes["fps_limit"] = str(p.fps_limit) if p.fps_limit else False
        mh_changes["no_display"] = False if p.mangohud else None
        if mangohud_config_path:
            env["MANGOHUD_CONFIGFILE"] = mangohud_config_path

    for k, v in p.extra_env.items():
        if not ENV_KEY_RE.match(k):
            warn.append(f"Ignored invalid environment variable name {k!r}")
            continue
        if k.startswith("LD_"):
            warn.append(f"{k} changes how the game loads libraries — make sure you trust this value.")
        env[k] = v

    wrappers: list[str] = []
    if p.gamemode:
        wrappers.append("gamemoderun")
    if p.gamescope:
        gs = ["gamescope"]
        if p.gs_width and p.gs_height:
            gs += ["-W", str(p.gs_width), "-H", str(p.gs_height)]
        if p.gs_render_width and p.gs_render_height:
            gs += ["-w", str(p.gs_render_width), "-h", str(p.gs_render_height)]
        if p.gs_refresh:
            gs += ["-r", str(p.gs_refresh)]
        if p.fps_limit:
            gs += ["--framerate-limit", str(p.fps_limit)]
        if p.gs_fullscreen:
            gs.append("-f")
        if p.gs_filter:
            gs += ["-F", p.gs_filter]
        if p.gs_hdr:
            gs.append("--hdr-enabled")
        if p.mangohud:
            gs.append("--mangoapp")   # MangoHud inside gamescope must use mangoapp
        gs.append("--")
        wrappers.extend(gs)
    elif use_mh_wrapper:
        wrappers.append("mangohud")

    parts = [f"{k}={shlex.quote(v)}" for k, v in env.items()]
    parts += [shlex.quote(w) if w != "--" else "--" for w in wrappers]
    parts.append("%command%")
    if p.game_args.strip():
        try:
            parts += [shlex.quote(a) for a in shlex.split(p.game_args)]
        except ValueError as e:
            warn.append(f"Game arguments ignored (unbalanced quotes: {e})")
    opts = " ".join(parts)
    if opts == "%command%":
        opts = ""
    return BuildResult(opts, env, wrappers, warn, mh_changes)
