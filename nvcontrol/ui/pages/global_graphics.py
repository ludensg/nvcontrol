"""GLOBAL GRAPHICS — mirrors the NVIDIA App 'Graphics ▸ Global settings' list, row by row."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QPlainTextEdit, QSpinBox,
                               QWidget)

from ...capabilities.features import Status
from ...core import runner
from ...integrations import display as D
from ...integrations import globalenv as G
from ..async_util import run_async
from ..widgets import HudPanel, StatusBadge, button, label
from .base import Page

log = logging.getLogger("nvcontrol.global")

PRESET_LABELS = {"app": "Use the 3D application setting", "render_preset_latest": "Latest"} | {
    f"render_preset_{c}": f"Preset {c.upper()}" for c in "abcdefghijklmno"}

# (title, attribute, kind, options, mechanism)
SECTIONS = [
    ("DLSS & RTX  ·  PROTON GAMES", [
        ("DLSS Override — Model presets (Super Resolution)", "dlss_sr_preset", "combo", G.DLSS_PRESETS,
         "DXVK-NVAPI driver setting"),
        ("DLSS Override — Model presets (Ray Reconstruction)", "dlss_rr_preset", "combo", G.DLSS_PRESETS,
         "DXVK-NVAPI driver setting"),
        ("DLSS Override — Super Resolution mode", "dlss_sr_mode", "srmode", ["app", "dlaa", "custom"],
         "DXVK-NVAPI NGX_DLSS_SR_MODE"),
        ("DLSS Override — Frame Generation", "dlss_fg_override", "bool", None, "DXVK-NVAPI NGX_DLSS_FG_OVERRIDE"),
        ("DLSS Override — Multi Frame Generation", "dlss_mfg_count", "mfg", ["app", "2x", "3x", "4x"],
         "DXVK-NVAPI NGX_DLSSG_MULTI_FRAME_COUNT · RTX 50"),
        ("Update DLSS in games (NGX updater)", "ngx_updater", "bool", None, "PROTON_ENABLE_NGX_UPDATER"),
        ("DLSS on-screen indicator", "dlss_indicator", "bool", None, "DXVK-NVAPI NGX debug options"),
        ("Smooth Motion", "smooth_motion", "smooth", None, "NVPRESENT_ENABLE_SMOOTH_MOTION · all Vulkan apps"),
    ]),
    ("LATENCY · SYNC · FRAME RATE", [
        ("Low latency mode", "low_latency", "combo", ["off", "on", "ultra"],
         "OpenGL __GL_MaxFramesAllowed + DXVK maxFrameLatency"),
        ("Vertical sync", "vsync", "combo", ["app", "off", "on"], "OpenGL __GL_SYNC_TO_VBLANK + DXVK syncInterval"),
        ("Max frame rate", "max_fps", "fps", None, "DXVK maxFrameRate + VKD3D_FRAME_RATE (Direct3D games)"),
        ("Triple buffering", "triple_buffering", "combo", ["app", "off", "on"], "DXVK numBackBuffers"),
    ]),
    ("IMAGE QUALITY", [
        ("Anisotropic filtering", "anisotropic", "combo", ["app", "off", "2x", "4x", "8x", "16x"],
         "OpenGL __GL_LOG_MAX_ANISO + DXVK samplerAnisotropy"),
        ("Texture filtering — Negative LOD bias", "negative_lod", "combo", ["allow", "clamp"],
         "DXVK clampNegativeLodBias"),
        ("Threaded optimization", "threaded_optimization", "combo", ["auto", "on", "off"],
         "OpenGL __GL_THREADED_OPTIMIZATIONS"),
        ("Shader cache size", "shader_cache", "combo", ["default", "10gb", "100gb", "unlimited"],
         "NVIDIA driver cache __GL_SHADER_DISK_CACHE_SIZE (OpenGL + Vulkan)"),
    ]),
]

NICE = {"app": "Use the 3D application setting", "off": "Off", "on": "On", "ultra": "Ultra", "auto": "Auto",
        "allow": "Allow", "clamp": "Clamp", "default": "Driver default", "10gb": "10 GB", "100gb": "100 GB",
        "unlimited": "Unlimited", "dlaa": "DLAA", "custom": "Custom render scale", "2x": "2x", "4x": "4x",
        "8x": "8x", "16x": "16x", "3x": "3x"}

WINDOWS_ONLY = [
    ("Image scaling (NIS)", "Per game: GAME PROFILES ▸ Gamescope ▸ filter 'nis' or 'fsr'"),
    ("DSR — Factors / smoothness", "Gamescope can render at a higher internal resolution"),
    ("Background application max frame rate", "—"),
    ("CUDA — Sysmem fallback policy", "—"),
    ("CUDA — GPUs / OpenGL rendering GPU / GPU assignment", "Single-GPU desktop: nothing to assign. "
                                                             "Laptops: __NV_PRIME_RENDER_OFFLOAD=1 per game"),
    ("OpenGL GDI compatibility", "GDI doesn't exist on Linux"),
    ("Vulkan/OpenGL present method", "The Wayland compositor (KWin) presents frames"),
    ("Virtual reality — VRSS / pre-rendered frames", "SteamVR settings"),
    ("RTX Dynamic Vibrance", "Static per-monitor Digital Vibrance on the DISPLAY page"),
    ("RTX HDR", "Gamescope HDR / native HDR games (DISPLAY ▸ HDR)"),
    ("Ambient occlusion · MFAA · Transparency / gamma-correct AA", "—"),
    ("Antialiasing — FXAA / Mode (driver-forced)", "X11 only via nvidia-settings; in-game AA otherwise"),
    ("Texture filtering — Quality / Trilinear / Anisotropic sample optimization", "—"),
    ("PhysX processor", "GPU PhysX isn't available to Proton games"),
]


class GlobalGraphicsPage(Page):
    nav_key = "nav.global"
    kicker = "// 05 · NVIDIA APP ▸ GLOBAL SETTINGS"
    subtitle = ("The NVIDIA App's global driver settings, one row each. On Linux they become a session "
                "environment file and a DXVK config that apply to every game started after your next login. "
                "Game Profiles still override them per game. Rows that don't exist on Linux are listed at the "
                "bottom with the closest alternative.")

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        self.g = G.GlobalGraphics.load()
        self.widgets: dict[str, QWidget] = {}
        self.rows_status: dict[str, StatusBadge] = {}
        for title, rows in SECTIONS:
            p = HudPanel(title, "DRIVER SETTINGS")
            grid = QGridLayout()
            grid.setColumnStretch(0, 1)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(6)
            for r, (name, attr, kind, opts, mech) in enumerate(rows):
                self._row(grid, r, name, attr, kind, opts, mech)
            p.add(grid)
            self.lay.addWidget(p)

        # immediate (non-environment) rows
        ip = HudPanel("Applied immediately", "HARDWARE · DISPLAY")
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        self.pm = QComboBox()
        self.pm.addItem("Normal (adaptive)", "normal")
        self.pm.addItem("Prefer maximum performance", "max")
        self.pm_btn = button("APPLY", None, self._apply_power_mode)
        self._fixed_row(grid, 0, "Power management mode", "NVML clock lock (root helper). Lasts until reboot. "
                        "Save it as a startup profile on GPU TUNING to keep it", self.pm, self.pm_btn)
        self.mt = QComboBox()
        self.mt.addItem("G-SYNC Compatible (VRR, fullscreen apps)", "automatic")
        self.mt.addItem("G-SYNC Compatible (VRR always)", "always")
        self.mt.addItem("Fixed refresh", "never")
        self.mt_btn = button("APPLY", None, self._apply_monitor_tech)
        self._fixed_row(grid, 1, "Monitor technology", "KWin VRR policy, all monitors", self.mt, self.mt_btn)
        ip.add(grid)
        self.lay.addWidget(ip)

        # preview + apply
        ap = HudPanel("Apply globally", "COMMIT")
        self.notes = label("", "Warn", wrap=True)
        ap.add(self.notes)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("Mono")
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(200)
        ap.add(self.preview)
        self.pending = label("", "Muted", wrap=True)
        ap.add(self.pending)
        r = QHBoxLayout()
        r.addWidget(button("OPEN CONFIG FOLDER", None,
                           lambda: runner.launch_detached(["xdg-open", str(G.env_path().parent)])))
        r.addStretch(1)
        r.addWidget(button("RESTORE DEFAULTS", "Danger", self._reset))
        r.addWidget(button("APPLY GLOBALLY", "Primary", self._apply))
        ap.add(r)
        self.lay.addWidget(ap)

        wp = HudPanel("Not available on Linux", "WINDOWS-ONLY · ALTERNATIVES")
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for i, (name, alt) in enumerate(WINDOWS_ONLY):
            grid.addWidget(StatusBadge(Status.WINDOWS_ONLY), i, 0)
            grid.addWidget(label(name), i, 1)
            grid.addWidget(label(alt, "Faint", wrap=True), i, 2)
        grid.setColumnStretch(2, 1)
        wp.add(grid)
        self.lay.addWidget(wp)
        self.lay.addStretch(1)
        self.on_caps()

    # ------------------------------------------------------------------ building
    def _row(self, grid: QGridLayout, r: int, name: str, attr: str, kind: str, opts, mech: str):
        col = QWidget()
        cl = QHBoxLayout(col)
        cl.setContentsMargins(0, 4, 0, 4)
        t = label(name)
        t.setStyleSheet("font-weight: 600;")
        cl.addWidget(t)
        cl.addWidget(label(mech, "Faint"), 1)
        grid.addWidget(col, r, 0)
        badge = StatusBadge(Status.OPERATIONAL)
        self.rows_status[attr] = badge
        grid.addWidget(badge, r, 1)
        val = getattr(self.g, attr)
        if kind in ("bool", "smooth"):
            w = QCheckBox("On")
            w.setChecked(bool(val))
            w.toggled.connect(self._changed)
        elif kind == "fps":
            w = QSpinBox()
            w.setRange(0, 1000)
            w.setSpecialValueText("Off")
            w.setSuffix(" FPS")
            w.setValue(int(val))
            w.valueChanged.connect(self._changed)
        elif kind == "srmode":
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            cb = QComboBox()
            for o in opts:
                cb.addItem(NICE.get(o, o), o)
            cb.setCurrentIndex(max(0, cb.findData(val)))
            sp = QSpinBox()
            sp.setRange(33, 100)
            sp.setSuffix(" %")
            sp.setValue(self.g.dlss_sr_ratio)
            sp.setEnabled(val == "custom")
            cb.currentIndexChanged.connect(lambda _: (sp.setEnabled(cb.currentData() == "custom"), self._changed()))
            sp.valueChanged.connect(self._changed)
            hl.addWidget(cb, 1)
            hl.addWidget(sp)
            w.combo, w.spin = cb, sp
        else:
            w = QComboBox()
            for o in opts:
                w.addItem(PRESET_LABELS.get(o) or NICE.get(o, o), o)
            w.setCurrentIndex(max(0, w.findData(val)))
            w.currentIndexChanged.connect(self._changed)
        w.setMinimumWidth(260)
        w.kind = kind
        self.widgets[attr] = w
        grid.addWidget(w, r, 2)

    def _fixed_row(self, grid, r, name, mech, w, btn):
        col = QWidget()
        cl = QHBoxLayout(col)
        cl.setContentsMargins(0, 4, 0, 4)
        t = label(name)
        t.setStyleSheet("font-weight: 600;")
        cl.addWidget(t)
        cl.addWidget(label(mech, "Faint", wrap=True), 1)
        grid.addWidget(col, r, 0)
        w.setMinimumWidth(260)
        grid.addWidget(w, r, 1)
        grid.addWidget(btn, r, 2)

    # ------------------------------------------------------------------ state
    def _collect(self) -> G.GlobalGraphics:
        g = self.g
        for attr, w in self.widgets.items():
            if w.kind in ("bool", "smooth"):
                setattr(g, attr, w.isChecked() and w.isEnabled())
            elif w.kind == "fps":
                setattr(g, attr, w.value())
            elif w.kind == "srmode":
                g.dlss_sr_mode = w.combo.currentData()
                g.dlss_sr_ratio = w.spin.value()
            else:
                v = w.currentData()
                setattr(g, attr, v if w.isEnabled() else "app")
        return g

    def _flags(self) -> tuple[bool, bool, bool]:
        sm = self.ctx.feature("smooth_motion")
        gpu = self.ctx.gpu
        mfg = bool(gpu and (gpu.rtx_series == 50 or gpu.arch == "Blackwell"))
        rtx = bool(gpu and gpu.is_rtx)
        return bool(sm and sm.status == Status.PER_GAME), mfg, rtx

    def on_caps(self):
        sm_ok, mfg_ok, rtx = self._flags()
        for attr, w in self.widgets.items():
            ok = True
            if attr.startswith(("dlss", "ngx")) and not rtx:
                ok = False
            if attr == "smooth_motion" and not sm_ok:
                ok = False
            if attr == "dlss_mfg_count" and not mfg_ok:
                ok = False
            if attr == "dlss_fg_override":
                f = self.ctx.feature("dlss_fg")
                ok = ok and bool(f and f.status != Status.UNSUPPORTED)
            w.setEnabled(ok)
            self.rows_status[attr].set_status(Status.OPERATIONAL if ok else Status.UNSUPPORTED)
            if not ok:
                tip = {"smooth_motion": (self.ctx.feature("smooth_motion").detail
                                         if self.ctx.feature("smooth_motion") else ""),
                       "dlss_mfg_count": "Multi Frame Generation needs a GeForce RTX 50 GPU."}.get(
                    attr, "Not supported by this GPU.")
                w.setToolTip(tip)
                self.rows_status[attr].setToolTip(tip)
        lk = self.ctx.feature("clock_lock")
        on = bool(lk and lk.status == Status.OPERATIONAL)
        self.pm.setEnabled(on)
        self.pm_btn.setEnabled(on)
        kde = self.ctx.sysinfo.is_kde and self.ctx.sysinfo.has("kscreen") and bool(self.ctx.sysinfo.displays)
        self.mt.setEnabled(kde)
        self.mt_btn.setEnabled(kde)
        if kde and self.ctx.sysinfo.displays[0].vrr_policy:
            self.mt.setCurrentIndex(max(0, self.mt.findData(self.ctx.sysinfo.displays[0].vrr_policy)))
        self._changed()

    def _changed(self, *_):
        g = self._collect()
        sm_ok, mfg_ok, _ = self._flags()
        env, dx, notes = G.build(g, sm_ok, mfg_ok)
        txt = f"# {G.env_path()}\n" + (G.render_env(env) if env else "(not written: nothing set)\n")
        txt += f"\n# {G.dxvk_path()}\n" + (G.render_dxvk(dx) if dx else "(not written: nothing set)\n")
        self.preview.setPlainText(txt)
        self.notes.setText("\n".join("⚠ " + n for n in notes))
        live = G.active_env()
        pend = any(live.get(k) != v for k, v in env.items()) or any(
            k not in env for k in live if k in ("NVPRESENT_ENABLE_SMOOTH_MOTION", "DXVK_CONFIG_FILE"))
        on_disk = G.env_path().exists()
        self.pending.setText(
            ("Saved to disk. " if on_disk else "") +
            ("Log out and back in for the session to pick up changes, then restart Steam." if pend or not on_disk
             else "The current session already uses these values."))

    # ------------------------------------------------------------------ actions
    def _apply(self):
        g = self._collect()
        sm_ok, mfg_ok, _ = self._flags()
        env, dx, notes = G.build(g, sm_ok, mfg_ok)
        if g.smooth_motion and sm_ok and not self.confirm(
                "Global Smooth Motion", "Smooth Motion will apply to every Vulkan application, not only games. "
                "Enable it globally anyway?"):
            return
        try:
            backups = G.write(env, dx)
            g.save()
        except (OSError, ValueError) as e:
            self.error("Global graphics", str(e))
            return
        log.info("global graphics applied: env=%s dxvk=%s backups=%s", env, dx, backups)
        self.main.toast("Global graphics saved. Log out and back in to apply to every game.", 12000)
        self._changed()

    def _reset(self):
        if not self.confirm("Restore defaults", "Remove all NV//CONTROL global graphics settings? (Files are backed "
                                                "up first. Applies after your next login.)"):
            return
        G.reset()
        self.g = G.GlobalGraphics()
        for attr, w in self.widgets.items():
            v = getattr(self.g, attr)
            if w.kind in ("bool", "smooth"):
                w.setChecked(bool(v))
            elif w.kind == "fps":
                w.setValue(int(v))
            elif w.kind == "srmode":
                w.combo.setCurrentIndex(0)
            else:
                w.setCurrentIndex(max(0, w.findData(v)))
        self.main.toast("Global graphics reset to driver defaults")
        self._changed()

    def _apply_power_mode(self):
        gpu = self.ctx.gpu_index
        if self.pm.currentData() == "normal":
            fn, msg = (lambda: self.ctx.helper.reset_clocks(gpu)), "Power management: normal (adaptive)"
        else:
            clocks = self.ctx.caps.supported_gpu_clocks
            if not clocks:
                self.error("Power management mode", "The driver reports no clock list.")
                return
            hi = max(clocks)
            lo = min((c for c in clocks if c >= hi * 0.7), default=hi)
            fn, msg = (lambda: self.ctx.helper.lock_clocks(gpu, lo, hi)), f"Prefer maximum performance ({lo}–{hi} MHz)"

        def done(res, exc):
            if exc or not res.ok:
                self.error("Power management mode", str(exc) if exc else res.error)
            else:
                self.main.toast(msg)
            self.ctx.refresh_caps()
        run_async(fn, done)

    def _apply_monitor_tech(self):
        pol = self.mt.currentData()
        outs = [o.name for o in self.ctx.sysinfo.displays]

        def job():
            if self.ctx.mock:
                log.info("[mock] vrrpolicy %s on %s", pol, outs)
                return []
            return [f"{n}: {r.err.strip()}" for n in outs if not (r := D.kscreen_set(n, "vrrpolicy", pol)).ok]

        def done(errs, exc):
            if exc or errs:
                self.error("Monitor technology", str(exc) if exc else "\n".join(errs))
            else:
                self.main.toast(f"VRR policy '{pol}' on {len(outs)} monitor(s)")
        run_async(job, done)
