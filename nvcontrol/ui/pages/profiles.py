from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from ...capabilities.features import Status
from ...core.config import cache_dir
from ...integrations import mangohud
from ...integrations import steam as S
from ...profiles.game_profile import DLSS_PRESETS, GAMESCOPE_FILTERS, GameProfile, build_launch_options
from ..async_util import run_async
from ..widgets import HudPanel, button, label
from .base import Page

log = logging.getLogger("nvcontrol.profiles")


class DiffDialog(QDialog):
    def __init__(self, parent, game: str, old: str, new: str, extra: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Write launch options")
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"WRITE TO STEAM · {game}", "H2"))
        lay.addWidget(label("CURRENT", "Kicker"))
        a = QPlainTextEdit(old or "(empty)")
        a.setObjectName("Mono")
        a.setReadOnly(True)
        a.setMaximumHeight(70)
        lay.addWidget(a)
        lay.addWidget(label("NEW", "Kicker"))
        b = QPlainTextEdit(new or "(empty — clears launch options)")
        b.setObjectName("Mono")
        b.setReadOnly(True)
        b.setMaximumHeight(90)
        lay.addWidget(b)
        for e in extra:
            lay.addWidget(label("• " + e, "Muted", wrap=True))
        lay.addWidget(label("A timestamped backup of localconfig.vdf is made first; you can roll back from this page.",
                            "Faint", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("WRITE")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ProfilesPage(Page):
    nav_key = "nav.profiles"
    kicker = "// 05 · PER-GAME CONFIGURATION"
    subtitle = ("Build Steam launch options visually. Nothing is written to Steam until you press WRITE TO STEAM "
                "and confirm; Steam must be closed.")

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        self.steam: S.Steam | None = None
        self.games: list[S.Game] = []
        self.tools: list[S.CompatTool] = []
        self.profile: GameProfile | None = None
        self.last_backup: dict[str, Path] = {}
        self._loading = False

        gate = HudPanel("Steam library", "ACCESS")
        gr = QHBoxLayout()
        self.gate_lbl = label("NV//CONTROL reads your Steam library only after you allow it.", "Muted", wrap=True)
        gr.addWidget(self.gate_lbl, 1)
        self.scan_btn = button("SCAN STEAM LIBRARY", "Primary", self._scan)
        gr.addWidget(self.scan_btn)
        gr.addWidget(button("IMPORT", None, self._import))
        gr.addWidget(button("EXPORT", None, self._export))
        gate.add(gr)
        self.lay.addWidget(gate)

        split = QSplitter(Qt.Horizontal)
        left = HudPanel("Games", "LIBRARY")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.textChanged.connect(self._filter)
        left.add(self.search)
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.currentItemChanged.connect(self._select)
        left.add(self.list)
        split.addWidget(left)

        right = HudPanel("Profile", "EDITOR")
        self.game_title = label("Select a game", "H2")
        right.add(self.game_title)
        self.tabs = QTabWidget()
        right.add(self.tabs)
        self._build_tabs()
        right.add(label("RESULTING STEAM LAUNCH OPTIONS", "Kicker"))
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("Mono")
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(90)
        right.add(self.preview)
        self.warn = label("", "Warn", wrap=True)
        right.add(self.warn)
        self.current_lbl = label("", "Faint", wrap=True)
        right.add(self.current_lbl)
        br = QHBoxLayout()
        self.b_save = button("SAVE PROFILE", None, self._save)
        self.b_write = button("WRITE TO STEAM", "Primary", self._write)
        self.b_copy = button("COPY", None, self._copy)
        self.b_roll = button("ROLL BACK LAST WRITE", "Danger", self._rollback)
        for b in (self.b_save, self.b_write, self.b_copy):
            br.addWidget(b)
        br.addStretch(1)
        br.addWidget(self.b_roll)
        right.add(br)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        split.setMinimumHeight(640)
        self.lay.addWidget(split)
        self._set_editor_enabled(False)

    # ------------------------------------------------------------------ form
    def _build_tabs(self):
        def tab():
            w = QWidget()
            f = QFormLayout(w)
            f.setLabelAlignment(Qt.AlignRight)
            f.setHorizontalSpacing(14)
            return w, f

        w, f = tab()
        self.proton = QComboBox()
        f.addRow("Proton version", self.proton)
        self.nvapi = QCheckBox("PROTON_ENABLE_NVAPI=1 (needed for DLSS/Reflex in some titles)")
        self.sm = QCheckBox("NVIDIA Smooth Motion (NVPRESENT_ENABLE_SMOOTH_MOTION=1)")
        self.ngx = QCheckBox("Fetch newer DLSS via NGX updater (PROTON_ENABLE_NGX_UPDATER=1)")
        self.sr = QCheckBox("Override DLSS Super Resolution preset")
        self.sr_p = QComboBox()
        self.sr_p.addItems(DLSS_PRESETS)
        self.srm = QComboBox()
        self.srm.addItem("Use the game's setting", "app")
        self.srm.addItem("DLAA (native resolution)", "dlaa")
        self.srm.addItem("Custom render scale", "custom")
        self.srr = QSpinBox()
        self.srr.setRange(33, 100)
        self.srr.setSuffix(" %")
        self.rr = QCheckBox("Override DLSS Ray Reconstruction preset")
        self.rr_p = QComboBox()
        self.rr_p.addItems(DLSS_PRESETS)
        self.fg = QCheckBox("Enable DLSS Frame Generation override")
        self.ind = QCheckBox("Show DLSS indicator (verify what's active)")
        self.cache = QSpinBox()
        self.cache.setRange(0, 64)
        self.cache.setSuffix(" GB")
        self.cache.setSpecialValueText("driver default")
        for row in (self.nvapi, self.sm, self.ngx):
            f.addRow("", row)
        f.addRow("", self.sr)
        f.addRow("SR preset", self.sr_p)
        srm_row = QHBoxLayout()
        srm_row.addWidget(self.srm, 1)
        srm_row.addWidget(self.srr)
        f.addRow("SR mode override", srm_row)
        f.addRow("", self.rr)
        f.addRow("RR preset", self.rr_p)
        f.addRow("", self.fg)
        f.addRow("", self.ind)
        f.addRow("Shader cache", self.cache)
        self.sm_note = label("", "Faint", wrap=True)
        f.addRow("", self.sm_note)
        self.tabs.addTab(w, "NVIDIA / PROTON")

        w, f = tab()
        self.mh = QCheckBox("MangoHud overlay")
        self.mh_p = QComboBox()
        self.mh_p.addItems(list(mangohud.PRESETS))
        self.fps = QSpinBox()
        self.fps.setRange(0, 1000)
        self.fps.setSpecialValueText("unlimited")
        self.gm = QCheckBox("Feral GameMode (gamemoderun)")
        self.gpu_prof = QComboBox()
        self.gpu_prof.addItems(["", "Balanced", "Maximum Performance", "Quiet Operation", "Power Efficient", "Custom"])
        f.addRow("", self.mh)
        f.addRow("Overlay preset", self.mh_p)
        f.addRow("FPS limit", self.fps)
        f.addRow("", self.gm)
        f.addRow("GPU profile (note)", self.gpu_prof)
        f.addRow("", label("The GPU profile is a reminder only: tuning is global. LACT can switch its own profiles "
                           "automatically when a game process starts.", "Faint", wrap=True))
        self.tabs.addTab(w, "PERFORMANCE")

        w, f = tab()
        self.gs = QCheckBox("Run inside Gamescope")
        self.gs_W, self.gs_H, self.gs_w, self.gs_h, self.gs_r = (QSpinBox() for _ in range(5))
        for s in (self.gs_W, self.gs_H, self.gs_w, self.gs_h):
            s.setRange(0, 7680)
            s.setSpecialValueText("auto")
        self.gs_r.setRange(0, 500)
        self.gs_r.setSpecialValueText("auto")
        self.gs_f = QCheckBox("Fullscreen (-f)")
        self.gs_filter = QComboBox()
        self.gs_filter.addItems(GAMESCOPE_FILTERS)
        self.gs_hdr = QCheckBox("HDR (--hdr-enabled)")
        f.addRow("", self.gs)
        r1 = QHBoxLayout()
        r1.addWidget(self.gs_W)
        r1.addWidget(label("×"))
        r1.addWidget(self.gs_H)
        f.addRow("Output (-W/-H)", r1)
        r2 = QHBoxLayout()
        r2.addWidget(self.gs_w)
        r2.addWidget(label("×"))
        r2.addWidget(self.gs_h)
        f.addRow("Render (-w/-h)", r2)
        f.addRow("Refresh (-r)", self.gs_r)
        f.addRow("Upscale filter (-F)", self.gs_filter)
        f.addRow("", self.gs_f)
        f.addRow("", self.gs_hdr)
        self.gs_note = label("", "Faint", wrap=True)
        f.addRow("", self.gs_note)
        self.tabs.addTab(w, "GAMESCOPE")

        w, f = tab()
        self.env = QPlainTextEdit()
        self.env.setObjectName("Mono")
        self.env.setPlaceholderText("KEY=value, one per line")
        self.env.setMaximumHeight(100)
        self.args = QLineEdit()
        self.args.setPlaceholderText("arguments passed to the game after %command%")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(90)
        f.addRow("Extra env", self.env)
        f.addRow("Game args", self.args)
        f.addRow("Notes", self.notes)
        self.tabs.addTab(w, "ADVANCED")

        for wdg in (self.nvapi, self.sm, self.ngx, self.sr, self.rr, self.fg, self.ind, self.mh, self.gm, self.gs,
                    self.gs_f, self.gs_hdr):
            wdg.toggled.connect(self._changed)
        self.srm.currentIndexChanged.connect(lambda _: self.srr.setEnabled(self.srm.currentData() == "custom"))
        self.srr.valueChanged.connect(self._changed)
        for wdg in (self.srm, self.sr_p, self.rr_p, self.mh_p, self.gs_filter, self.proton, self.gpu_prof):
            wdg.currentIndexChanged.connect(self._changed)
        for wdg in (self.cache, self.fps, self.gs_W, self.gs_H, self.gs_w, self.gs_h, self.gs_r):
            wdg.valueChanged.connect(self._changed)
        self.env.textChanged.connect(self._changed)
        self.args.textChanged.connect(self._changed)

    def _set_editor_enabled(self, on: bool):
        self.tabs.setEnabled(on)
        for b in (self.b_save, self.b_write, self.b_copy, self.b_roll):
            b.setEnabled(on)

    def on_caps(self):
        sm = self.ctx.feature("smooth_motion")
        ok = bool(sm and sm.status == Status.PER_GAME)
        self.sm.setEnabled(ok)
        self.sm_note.setText(("Smooth Motion: " + sm.detail) if sm else "")
        self.gs.setEnabled(self.ctx.sysinfo.has("gamescope"))
        self.gs_note.setText("" if self.gs.isEnabled() else "Gamescope is not installed (pacman -S gamescope).")
        self.mh.setEnabled(self.ctx.sysinfo.has("mangohud"))
        self.gm.setEnabled(self.ctx.sysinfo.has("gamemode"))

    def on_show(self):
        if self.ctx.settings.steam_access_granted and not self.games:
            self._scan()

    # ------------------------------------------------------------------ steam
    def _scan(self):
        if not self.ctx.settings.steam_access_granted:
            self.main.request_steam_access()
            if not self.ctx.settings.steam_access_granted:
                return
        mock = self.ctx.mock

        def job():
            root = S.create_mock_steam(cache_dir() / "mock-steam") if mock else None
            st = S.open_steam(root)
            if not st:
                return None
            return st, st.games(), st.compat_tools()

        def done(res, exc):
            if exc:
                self.error("Steam scan failed", str(exc))
                return
            if not res:
                self.gate_lbl.setText("Steam installation not found (~/.local/share/Steam, ~/.steam, Flatpak).")
                return
            self.steam, self.games, self.tools = res
            self.gate_lbl.setText(f"{len(self.games)} games · {len(self.tools)} compatibility tools · {self.steam.root}")
            self.proton.blockSignals(True)
            self.proton.clear()
            self.proton.addItem("(leave Steam's setting)", None)
            for t in self.tools:
                self.proton.addItem(f"{t.display}  [{t.kind}]", t.name)
            self.proton.blockSignals(False)
            self._filter()
        run_async(job, done)

    def _filter(self):
        q = self.search.text().lower()
        self.list.clear()
        for g in self.games:
            if q in g.name.lower():
                it = QListWidgetItem(("● " if self.ctx.store.exists(g.appid) else "   ") + g.name)
                it.setData(Qt.UserRole, g)
                self.list.addItem(it)

    def _select(self, cur, _prev):
        if not cur:
            return
        g: S.Game = cur.data(Qt.UserRole)
        self.profile = self.ctx.store.get(g.appid, g.name)
        self.game_title.setText(f"{g.name.upper()}  ·  {g.appid}")
        self._load(self.profile)
        self._set_editor_enabled(True)
        try:
            cur_opts = self.steam.get_launch_options(g.appid) if self.steam else ""
            tool = self.steam.get_compat_tool(g.appid) if self.steam else None
            self.current_lbl.setText(f"Current in Steam: {cur_opts or '(none)'}   ·   compat tool: {tool or 'Steam default'}")
        except S.SteamError as e:
            self.current_lbl.setText(str(e))
        self._changed()

    def _load(self, p: GameProfile):
        self._loading = True
        idx = self.proton.findData(p.proton)
        self.proton.setCurrentIndex(max(0, idx))
        self.nvapi.setChecked(p.enable_nvapi)
        self.sm.setChecked(p.smooth_motion and self.sm.isEnabled())
        self.ngx.setChecked(p.ngx_updater)
        self.sr.setChecked(p.dlss_sr_override)
        self.sr_p.setCurrentText(p.dlss_sr_preset)
        self.srm.setCurrentIndex(max(0, self.srm.findData(p.dlss_sr_mode)))
        self.srr.setValue(p.dlss_sr_ratio)
        self.srr.setEnabled(p.dlss_sr_mode == "custom")
        self.rr.setChecked(p.dlss_rr_override)
        self.rr_p.setCurrentText(p.dlss_rr_preset)
        self.fg.setChecked(p.dlss_fg_override)
        self.ind.setChecked(p.dlss_indicator)
        self.cache.setValue(p.shader_cache_gb)
        self.mh.setChecked(p.mangohud)
        self.mh_p.setCurrentText(p.mangohud_preset)
        self.fps.setValue(p.fps_limit)
        self.gm.setChecked(p.gamemode)
        self.gpu_prof.setCurrentText(p.gpu_profile)
        self.gs.setChecked(p.gamescope)
        self.gs_W.setValue(p.gs_width)
        self.gs_H.setValue(p.gs_height)
        self.gs_w.setValue(p.gs_render_width)
        self.gs_h.setValue(p.gs_render_height)
        self.gs_r.setValue(p.gs_refresh)
        self.gs_f.setChecked(p.gs_fullscreen)
        self.gs_filter.setCurrentText(p.gs_filter)
        self.gs_hdr.setChecked(p.gs_hdr)
        self.env.setPlainText("\n".join(f"{k}={v}" for k, v in p.extra_env.items()))
        self.args.setText(p.game_args)
        self.notes.setPlainText(p.notes)
        self._loading = False

    def _collect(self) -> GameProfile:
        p = self.profile or GameProfile()
        p.proton = self.proton.currentData()
        p.enable_nvapi = self.nvapi.isChecked()
        p.smooth_motion = self.sm.isChecked() and self.sm.isEnabled()
        p.ngx_updater = self.ngx.isChecked()
        p.dlss_sr_override = self.sr.isChecked()
        p.dlss_sr_preset = self.sr_p.currentText()
        p.dlss_sr_mode = self.srm.currentData()
        p.dlss_sr_ratio = self.srr.value()
        p.dlss_rr_override = self.rr.isChecked()
        p.dlss_rr_preset = self.rr_p.currentText()
        p.dlss_fg_override = self.fg.isChecked()
        p.dlss_indicator = self.ind.isChecked()
        p.shader_cache_gb = self.cache.value()
        p.mangohud = self.mh.isChecked()
        p.mangohud_preset = self.mh_p.currentText()
        p.fps_limit = self.fps.value()
        p.gamemode = self.gm.isChecked()
        p.gpu_profile = self.gpu_prof.currentText()
        p.gamescope = self.gs.isChecked()
        p.gs_width, p.gs_height = self.gs_W.value(), self.gs_H.value()
        p.gs_render_width, p.gs_render_height = self.gs_w.value(), self.gs_h.value()
        p.gs_refresh = self.gs_r.value()
        p.gs_fullscreen = self.gs_f.isChecked()
        p.gs_filter = self.gs_filter.currentText()
        p.gs_hdr = self.gs_hdr.isChecked()
        env = {}
        for line in self.env.toPlainText().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        p.extra_env = env
        p.game_args = self.args.text()
        p.notes = self.notes.toPlainText()
        return p

    def _build(self):
        p = self._collect()
        sm = self.ctx.feature("smooth_motion")
        mh_path = str(mangohud.profile_config_path(p.appid)) if p.appid else None
        return p, build_launch_options(p, bool(sm and sm.status == Status.PER_GAME), mh_path)

    def _changed(self, *_):
        if self._loading or not self.profile:
            return
        _, res = self._build()
        self.preview.setPlainText(res.options or "(no launch options)")
        self.warn.setText("\n".join("⚠ " + w for w in res.warnings))

    def _save(self):
        p, _ = self._build()
        self.ctx.store.save(p)
        self.main.toast(f"Profile saved: {p.name}")
        self._filter()

    def _copy(self):
        QGuiApplication.clipboard().setText(self.preview.toPlainText())
        self.main.toast("Launch options copied")

    def _write(self):
        if not self.steam or not self.profile:
            return
        p, res = self._build()
        if not self.ctx.mock and S.steam_running(self.steam.root):
            self.error("Steam is running", "Close Steam completely (Steam ▸ Exit) — Steam overwrites its config when "
                                           "it exits, which would discard the change.")
            return
        try:
            old = self.steam.get_launch_options(p.appid)
            old_tool = self.steam.get_compat_tool(p.appid)
        except S.SteamError as e:
            self.error("Steam", str(e))
            return
        extra = []
        if res.mangohud_changes is not None:
            extra.append(f"MangoHud config will be written: {mangohud.profile_config_path(p.appid)}")
        if p.proton and p.proton != old_tool:
            extra.append(f"Compatibility tool: {old_tool or 'Steam default'} → {p.proton} (config.vdf, backed up)")
        extra += res.warnings
        if DiffDialog(self, p.name, old, res.options, extra).exec() != QDialog.Accepted:
            return
        try:
            if res.mangohud_changes is not None:
                mangohud.write_config(mangohud.profile_config_path(p.appid), res.mangohud_changes,
                                      f"NV//CONTROL profile for {p.name}")
            bk = self.steam.set_launch_options(p.appid, res.options)
            if bk:
                self.last_backup[p.appid] = bk
            if p.proton and p.proton != old_tool:
                self.steam.set_compat_tool(p.appid, p.proton)
            self.ctx.store.save(p)
            self.main.toast(f"Written to Steam ✓  backup: {bk}")
            self._select(self.list.currentItem(), None)
        except (S.SteamError, OSError, ValueError) as e:
            self.error("Write failed", str(e))

    def _rollback(self):
        if not self.steam or not self.profile:
            return
        bk = self.last_backup.get(self.profile.appid)
        if not bk:
            from ...core.config import backup_dir
            cands = sorted(backup_dir().glob(f"localconfig-{self.profile.appid}-*"))
            bk = cands[-1] if cands else None
        if not bk:
            self.info("Roll back", "No backup for this game yet.")
            return
        if not self.confirm("Roll back", f"Restore localconfig.vdf from\n{bk}?\n\nThis restores ALL launch options "
                                         "to the state at that moment."):
            return
        try:
            self.steam.restore(bk, self.steam.localconfig_path())
            self.main.toast("Restored ✓")
            self._select(self.list.currentItem(), None)
        except S.SteamError as e:
            self.error("Roll back failed", str(e))

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export profiles", str(Path.home() / "nvcontrol-profiles.json"),
                                           "JSON (*.json)")
        if p:
            n = self.ctx.store.export_bundle(Path(p))
            self.main.toast(f"Exported {n} profiles")

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import profiles", str(Path.home()), "JSON (*.json)")
        if p:
            try:
                n = self.ctx.store.import_bundle(Path(p), overwrite=self.confirm("Import", "Overwrite existing profiles?"))
                self.main.toast(f"Imported {n} profiles")
                self._filter()
            except (ValueError, OSError) as e:
                self.error("Import failed", str(e))
