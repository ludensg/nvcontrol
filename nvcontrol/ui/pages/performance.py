from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QSpinBox

from ...integrations import mangohud
from ...integrations.tools import launch_tool
from ..widgets import HudPanel, StatusBadge, button, label
from .base import Page

POSITIONS = ["top-left", "top-right", "top-center", "bottom-left", "bottom-right", "bottom-center"]


class PerformancePage(Page):
    nav_key = "nav.performance"
    kicker = "· FRAME PACING"
    subtitle = "Overlay, frame cap and launch wrappers."

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        mp = HudPanel("MangoHud — global configuration", "OVERLAY · SCOPE: ALL MANGOHUD GAMES")
        self.mh_status = QHBoxLayout()
        mp.add(self.mh_status)
        f = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems(list(mangohud.PRESETS))
        self.fps = QSpinBox()
        self.fps.setRange(0, 1000)
        self.fps.setSpecialValueText("unlimited")
        self.pos = QComboBox()
        self.pos.addItems(POSITIONS)
        self.toggle = QLineEdit("Shift_R+F12")
        self.hidden = QCheckBox("Start hidden (toggle with the key)")
        self.logging = QCheckBox("Enable frametime logging key (Shift_L+F2, logs to ~/mangohud-logs)")
        f.addRow("Preset", self.preset)
        f.addRow("FPS limit", self.fps)
        f.addRow("Position", self.pos)
        f.addRow("Toggle key", self.toggle)
        f.addRow("", self.hidden)
        f.addRow("", self.logging)
        mp.add(f)
        r = QHBoxLayout()
        r.addWidget(button("WRITE GLOBAL CONFIG", "Primary", self._write))
        r.addWidget(button("OPEN GOVERLAY", None, lambda: self._launch("goverlay")))
        r.addStretch(1)
        mp.add(r)
        self.path_lbl = label(str(mangohud.global_config_path()), "Faint")
        mp.add(self.path_lbl)
        self.cfg_view = QPlainTextEdit()
        self.cfg_view.setObjectName("Mono")
        self.cfg_view.setReadOnly(True)
        self.cfg_view.setMaximumHeight(140)
        mp.add(self.cfg_view)
        self.lay.addWidget(mp)

        sp = HudPanel("How settings apply", "SCOPE")
        for t in ("GLOBAL — MangoHud.conf above: used by any game started with `mangohud %command%` or MANGOHUD=1.",
                  "PER-GAME — Game Profiles write a dedicated MangoHud config and launch options for one game.",
                  "LAUNCHER — Gamescope options exist only in that game's launch line.",
                  "V-SYNC — In-game. Under Wayland, the compositor presents; prefer VRR + an FPS cap a few frames "
                  "below refresh.",
                  "LOW LATENCY — Use NVIDIA Reflex where the game offers it (works through DXVK-NVAPI)."):
            sp.add(label("▸ " + t, None, wrap=True))
        self.lay.addWidget(sp)

        tp = HudPanel("Launch wrappers", "AVAILABILITY")
        self.wrap_rows = QFormLayout()
        tp.add(self.wrap_rows)
        self.lay.addWidget(tp)
        self.lay.addStretch(1)
        self._load()
        self.on_caps()

    def _launch(self, tid):
        if not launch_tool(tid):
            self.error("Not installed", f"{tid} is not installed. See SYSTEM TOOLS.")

    def _load(self):
        cfg = mangohud.read_config(mangohud.global_config_path())
        if "fps_limit" in cfg and (cfg["fps_limit"] or "").split(",")[0].isdigit():
            self.fps.setValue(int(cfg["fps_limit"].split(",")[0]))
        if cfg.get("position") in POSITIONS:
            self.pos.setCurrentText(cfg["position"])
        if cfg.get("toggle_hud"):
            self.toggle.setText(cfg["toggle_hud"])
        self.hidden.setChecked("no_display" in cfg)
        self.logging.setChecked("toggle_logging" in cfg)
        p = mangohud.global_config_path()
        self.cfg_view.setPlainText(p.read_text() if p.exists() else "(no global MangoHud config yet)")

    def on_caps(self):
        while self.mh_status.count():
            it = self.mh_status.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        f = self.ctx.feature("overlay")
        self.mh_status.addLayout(self.status_row(f))
        while self.wrap_rows.rowCount():
            self.wrap_rows.removeRow(0)
        for tid, desc in (("mangohud", "Overlay + limiter"), ("gamescope", "Upscaling / resolution / HDR"),
                          ("gamemode", "CPU governor while gaming"), ("goverlay", "MangoHud GUI editor")):
            st = self.ctx.sysinfo.tools.get(tid)
            from ...capabilities.features import Status
            badge = StatusBadge(Status.OPERATIONAL if st and st.installed else Status.NEEDS_CONFIG)
            row = QHBoxLayout()
            row.addWidget(badge)
            row.addWidget(label(desc, "Muted"), 1)
            self.wrap_rows.addRow(tid, row)

    def _write(self):
        changes = dict(mangohud.PRESETS[self.preset.currentText()])
        changes["fps_limit"] = str(self.fps.value()) if self.fps.value() else False
        changes["position"] = self.pos.currentText()
        key = self.toggle.text().strip()
        if key:
            changes["toggle_hud"] = key
        changes["no_display"] = None if self.hidden.isChecked() else False
        if self.logging.isChecked():
            changes["toggle_logging"] = "Shift_L+F2"
            changes["output_folder"] = str(__import__("pathlib").Path.home() / "mangohud-logs")
        else:
            changes["toggle_logging"] = False
        try:
            bk = mangohud.write_config(mangohud.global_config_path(), changes, "Managed in part by NV//CONTROL")
            self.main.toast("MangoHud config written" + (f" (backup {bk.name})" if bk else ""))
        except (ValueError, OSError) as e:
            self.error("MangoHud", str(e))
        self._load()
