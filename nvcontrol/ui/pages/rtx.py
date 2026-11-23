from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QListWidget

from ...capabilities.features import Status
from ...integrations import steam as steam_mod
from ...profiles.game_profile import DLSS_PRESETS
from ..async_util import run_async
from ..widgets import HudPanel, StatusBadge, button, label
from .base import Page

HOWTO = {
    "dlss_sr": "Choose DLSS Quality/Balanced/Performance or DLAA in the game's graphics menu.",
    "dlss_override": "Per game in GAME PROFILES ▸ NVIDIA. Forces a newer DLSS preset (e.g. K/L/M) via DXVK-NVAPI. "
                     "Enable the DLSS indicator to verify it took effect.",
    "dlss_rr": "Enable Ray Reconstruction in the game (path-traced titles). Preset override available per game.",
    "dlss_fg": "Enable Frame Generation in the game. Proton-only override: DLSS FG override.",
    "dlss_mfg": "Select 3×/4× Frame Generation in the game (RTX 50).",
    "smooth_motion": "Per game in GAME PROFILES. Driver frame generation for games without DLSS FG. "
                     "Works with DX11 and DX12 games too: on Linux, Proton runs them on Vulkan (DXVK for DX9–11, "
                     "VKD3D-Proton for DX12). Only OpenGL games (or Proton forced to WineD3D) are left out.",
    "reflex": "Enable Reflex in the game's settings. On Proton, DXVK-NVAPI provides it; set "
              "PROTON_ENABLE_NVAPI=1 in the profile if the game doesn't show the option.",
    "shader_cache": "Per game: raise the NVIDIA shader disk cache for large titles to reduce stutter.",
}


class RtxPage(Page):
    nav_key = "nav.rtx"
    kicker = "· RTX FEATURES"
    subtitle = "What controls each RTX feature on Linux, and how to turn it on."

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        from ..status_panels import SmoothMotionPanel
        self.sm_panel = SmoothMotionPanel(ctx, main)
        self.lay.addWidget(self.sm_panel)
        self.cards = QGridLayout()
        self.cards.setSpacing(14)
        self.lay.addLayout(self.cards)

        dp = HudPanel("Defaults for new game profiles", "GLOBAL BASELINE")
        dp.add(label("These values pre-fill every new game profile. They are not applied to any game until you "
                     "write that game's launch options.", "Faint", wrap=True))
        g = QGridLayout()
        self.d_nvapi = QCheckBox("Force DXVK-NVAPI (PROTON_ENABLE_NVAPI=1)")
        self.d_sm = QCheckBox("NVIDIA Smooth Motion")
        self.d_ngx = QCheckBox("Update DLSS via NGX updater (PROTON_ENABLE_NGX_UPDATER=1)")
        self.d_sr = QCheckBox("DLSS SR override")
        self.d_preset = QComboBox()
        self.d_preset.addItems(DLSS_PRESETS)
        self.d_mh = QCheckBox("MangoHud overlay")
        for i, w in enumerate((self.d_nvapi, self.d_sm, self.d_ngx, self.d_sr, self.d_mh)):
            g.addWidget(w, i // 2, i % 2)
        pr = QHBoxLayout()
        pr.addWidget(label("SR PRESET", "Kicker"))
        pr.addWidget(self.d_preset)
        pr.addStretch(1)
        g.addLayout(pr, 3, 0)
        dp.add(g)
        br = QHBoxLayout()
        br.addStretch(1)
        br.addWidget(button("SAVE DEFAULTS", "Primary", self._save_defaults))
        dp.add(br)
        self.lay.addWidget(dp)

        pp = HudPanel("Compatibility tools", "PROTON")
        self.proton_list = QListWidget()
        self.proton_list.setMaximumHeight(170)
        pp.add(self.proton_list)
        r = QHBoxLayout()
        r.addWidget(button("SCAN", None, self._scan_proton))
        r.addWidget(button("PROTONUP-QT (GE-PROTON)", None, lambda: self._launch("protonup-qt")))
        r.addStretch(1)
        pp.add(r)
        pp.add(label("GE-Proton and Proton-CachyOS add PROTON_DLSS_UPGRADE / PROTON_DLSS_INDICATOR. Valve Proton "
                     "uses PROTON_ENABLE_NGX_UPDATER and DXVK-NVAPI DRS variables (used by NV//CONTROL).",
                     "Faint", wrap=True))
        self.lay.addWidget(pp)
        self.lay.addStretch(1)
        self._load_defaults()
        self.on_caps()

    def _launch(self, tid):
        from ...integrations.tools import launch_tool
        if not launch_tool(tid):
            self.error("Not installed", "ProtonUp-Qt is not installed (AUR: protonup-qt).")

    def on_caps(self):
        while self.cards.count():
            it = self.cards.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        ids = ["dlss_sr", "dlss_override", "dlss_rr", "dlss_fg", "dlss_mfg", "smooth_motion", "reflex", "shader_cache"]
        for i, fid in enumerate(ids):
            f = self.ctx.feature(fid)
            if not f:
                continue
            card = HudPanel(f.name, f.scope.upper() or "FEATURE")
            row = QHBoxLayout()
            row.addWidget(StatusBadge(f.status))
            row.addWidget(label(f.mechanism, "Mono"), 1)
            card.add(row)
            if f.requirement:
                card.add(label("REQUIRES  " + f.requirement, "Faint", wrap=True))
            if f.detail:
                card.add(label(f.detail, "Muted", wrap=True))
            if f.status != Status.UNSUPPORTED:
                card.add(label("HOW  " + HOWTO.get(fid, ""), None, wrap=True))
            self.cards.addWidget(card, i // 2, i % 2)
        sm = self.ctx.feature("smooth_motion")
        self.d_sm.setEnabled(bool(sm and sm.status == Status.PER_GAME))
        if not self.d_sm.isEnabled():
            self.d_sm.setChecked(False)
            self.d_sm.setToolTip(sm.detail if sm else "")

    def _load_defaults(self):
        d = self.ctx.store.defaults()
        self.d_nvapi.setChecked(d.enable_nvapi)
        self.d_sm.setChecked(d.smooth_motion)
        self.d_ngx.setChecked(d.ngx_updater)
        self.d_sr.setChecked(d.dlss_sr_override)
        self.d_preset.setCurrentText(d.dlss_sr_preset)
        self.d_mh.setChecked(d.mangohud)

    def _save_defaults(self):
        d = self.ctx.store.defaults()
        d.enable_nvapi = self.d_nvapi.isChecked()
        d.smooth_motion = self.d_sm.isChecked() and self.d_sm.isEnabled()
        d.ngx_updater = self.d_ngx.isChecked()
        d.dlss_sr_override = self.d_sr.isChecked()
        d.dlss_sr_preset = self.d_preset.currentText()
        d.mangohud = self.d_mh.isChecked()
        self.ctx.store.save_defaults(d)
        self.main.toast("Profile defaults saved")

    def _scan_proton(self):
        if not self.ctx.settings.steam_access_granted:
            self.main.request_steam_access()
            if not self.ctx.settings.steam_access_granted:
                return

        def job():
            s = steam_mod.open_steam()
            return s.compat_tools() if s else None

        def done(tools, exc):
            self.proton_list.clear()
            if tools is None:
                self.proton_list.addItem("Steam installation not found.")
                return
            for t in tools:
                self.proton_list.addItem(f"[{t.kind:8}] {t.display}   ({t.name})")
            if not tools:
                self.proton_list.addItem("No Proton versions installed yet.")
        run_async(job, done)

    def on_show(self):
        self.sm_panel.refresh()
        if self.ctx.settings.steam_access_granted and self.proton_list.count() == 0:
            self._scan_proton()
