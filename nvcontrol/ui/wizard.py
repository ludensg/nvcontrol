"""First-run setup wizard: inspect → dependencies → features → preset → done."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView,
                               QRadioButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import TAGLINE
from ..capabilities.features import Status
from ..core.config import data_dir, save_json
from ..tuning.presets import DESCRIPTIONS, PRESET_NAMES, preset_settings
from .async_util import run_async
from .install_dialog import InstallDialog
from .widgets import CircuitDivider, HudPanel, StatusBadge, button, label

log = logging.getLogger("nvcontrol.wizard")
STAGES = ["INSPECTION", "DEPENDENCIES", "FEATURES", "CONFIGURATION", "COMPLETE"]


class SetupWizard(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Root")
        self.setWindowTitle("NV//CONTROL — Setup")
        self.resize(980, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 20)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("FIRST-RUN CONFIGURATION", "Kicker"))
        col.addWidget(label("NV//CONTROL", "H1"))
        col.addWidget(label(TAGLINE, "Muted"))
        head.addLayout(col, 1)
        self.steps = []
        for i, s in enumerate(STAGES):
            lb = label(f"{i + 1:02d} {s}", "Kicker")
            self.steps.append(lb)
            head.addWidget(lb)
        lay.addLayout(head)
        lay.addWidget(CircuitDivider())
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.skip = button("SKIP SETUP", None, self.accept)
        self.back = button("BACK", None, self._back)
        self.next = button("NEXT", "Primary", self._next)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        lay.addLayout(nav)
        self._pages = [self._p_inspect(), self._p_deps(), self._p_features(), self._p_config(), self._p_done()]
        for p in self._pages:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QScrollArea.NoFrame)
            sc.setWidget(p)
            self.stack.addWidget(sc)
        self._go(0)
        self._run_inspection()

    # ------------------------------------------------------------------ navigation
    def _go(self, i):
        self.stack.setCurrentIndex(i)
        for k, lb in enumerate(self.steps):
            lb.setStyleSheet("" if k == i else "color: #5C625A;")
        self.back.setEnabled(i > 0)
        self.next.setText("OPEN DASHBOARD" if i == len(STAGES) - 1 else "NEXT")
        if i == 2:
            self._fill_features()
        if i == 3:
            self._update_preview()
        if i == 4:
            self._fill_summary()

    def _back(self):
        self._go(max(0, self.stack.currentIndex() - 1))

    def _next(self):
        i = self.stack.currentIndex()
        if i == 3 and not self._apply_config():
            return
        if i == len(STAGES) - 1:
            self.ctx.settings.first_run_done = True
            self.ctx.settings.save()
            self.accept()
            return
        self._go(i + 1)

    # ------------------------------------------------------------------ stage 1
    def _p_inspect(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.inspect_panel = HudPanel("System readiness report", "STAGE 01")
        self.inspect_grid = QGridLayout()
        self.inspect_grid.setColumnStretch(2, 1)
        self.inspect_panel.add(self.inspect_grid)
        self.verdict = label("Inspecting system…", "H2", wrap=True)
        v.addWidget(self.verdict)
        v.addWidget(self.inspect_panel)
        v.addStretch(1)
        return w

    def _run_inspection(self):
        self.next.setEnabled(False)

        def done(_r, exc):
            self.next.setEnabled(True)
            if exc:
                self.verdict.setText(f"Inspection error: {exc} (see log)")
            self._fill_inspection()
        run_async(self.ctx.detect_system, done)

    def _row(self, r, key, value, ok):
        st = {True: Status.OPERATIONAL, False: Status.UNSUPPORTED, None: Status.NEEDS_CONFIG}[ok]
        self.inspect_grid.addWidget(StatusBadge(st), r, 0)
        self.inspect_grid.addWidget(label(key.upper(), "Kicker"), r, 1)
        self.inspect_grid.addWidget(label(str(value), "Mono", wrap=True), r, 2)

    def _fill_inspection(self):
        s, g, c, t = self.ctx.sysinfo, self.ctx.gpu, self.ctx.caps, self.ctx.backend.telemetry(self.ctx.gpu_index)
        h = self.ctx.health
        rows = [
            ("NVIDIA driver", (h.title + (f" — {h.fix[0]}" if h.fix else "")) if h else "not checked",
             bool(h and h.ok)),
            ("GPU", f"{g.name} ({g.arch or 'unknown arch'})" if g else "No NVIDIA GPU found", bool(g)),
            ("VRAM", f"{g.vram_total_mb} MiB" if g and g.vram_total_mb else "—", bool(g)),
            ("Driver", f"{g.driver_version} · {'open' if g and g.open_kernel_module else 'proprietary'} kernel module"
             if g else "—", bool(g)),
            ("CUDA", g.cuda_version if g and g.cuda_version else "not reported", bool(g and g.cuda_version) or None),
            ("Temperature / load", f"{t.temp_c} °C · {t.util_gpu} %" if t.temp_c is not None else "—",
             t.temp_c is not None),
            ("Power control", f"{c.power.min_w:.0f}–{c.power.max_w:.0f} W" if c.power and c.power.adjustable
             else "not adjustable", bool(c.power and c.power.adjustable) or None),
            ("Clock offsets", f"core {c.gpc_offset.min_mhz}…{c.gpc_offset.max_mhz}" if c.gpc_offset else "not exposed",
             bool(c.gpc_offset) or None),
            ("Fans", f"{c.fan_count} controllable" if c.fan_count else "not controllable", bool(c.fan_count) or None),
            ("Telemetry source", self.ctx.backend.source, self.ctx.backend.name in ("nvml", "mock") or None),
            ("Desktop", f"{s.desktop or '?'} {s.plasma_version or ''}", s.is_kde or None),
            ("Session", s.session, s.session in ("wayland", "x11")),
            ("Kernel", s.kernel, True),
            ("nvidia_drm modeset", s.nvidia_drm_modeset, s.nvidia_drm_modeset),
            ("Vulkan", f"{s.vulkan_device or '?'} · API {s.vulkan_api or '?'}" if s.vulkan_ok else "not detected",
             s.vulkan_ok or None),
            ("Displays", ", ".join(f"{d.name} {d.current_mode.label if d.current_mode else ''}" for d in s.displays)
             or "none detected", bool(s.displays) or None),
            ("Gaming software", ", ".join(k for k in ("steam", "gamescope", "mangohud", "gamemode") if s.has(k))
             or "none", s.has("steam") or None),
            ("GPU utilities", ", ".join(k for k in ("lact", "nvidia-settings", "goverlay", "vulkan-tools") if s.has(k))
             or "none", s.has("lact") or None),
            ("Privileged helper", "installed" if s.helper_installed else "missing — run install.sh",
             s.helper_installed or None),
        ]
        while self.inspect_grid.count():
            it = self.inspect_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, (k, v, ok) in enumerate(rows):
            self._row(i, k, v, ok)
        if h and not h.ok:
            self.verdict.setText(f"⚠ {h.title}. " + (h.fix[0] if h.fix else ""))
        elif not g:
            self.verdict.setText("No NVIDIA GPU detected — monitoring and tuning are unavailable. "
                                 "Check the driver (chwd / nvidia-utils) and reboot.")
        elif not s.helper_installed:
            self.verdict.setText("GPU ready. Monitoring works; tuning needs the privileged helper from install.sh.")
        else:
            self.verdict.setText("SYSTEM READY.")
        self._fill_deps()

    # ------------------------------------------------------------------ stage 2
    def _p_deps(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.dep_panel = HudPanel("Dependencies", "STAGE 02")
        self.dep_panel.add(label("Only packages from official / CachyOS repositories are installed automatically. "
                                 "Nothing is installed without showing you the exact command first.", "Muted", wrap=True))
        self.dep_box = QVBoxLayout()
        self.dep_panel.add(self.dep_box)
        r = QHBoxLayout()
        r.addStretch(1)
        self.dep_btn = button("INSTALL SELECTED", "Primary", self._install)
        r.addWidget(self.dep_btn)
        self.dep_panel.add(r)
        v.addWidget(self.dep_panel)
        v.addStretch(1)
        self.dep_checks: list[tuple[QCheckBox, object]] = []
        return w

    def _fill_deps(self):
        while self.dep_box.count():
            it = self.dep_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    x = it.layout().takeAt(0)
                    if x.widget():
                        x.widget().deleteLater()
        self.dep_checks = []
        for st in self.ctx.sysinfo.tools.values():
            t = st.tool
            row = QHBoxLayout()
            row.addWidget(StatusBadge(Status.OPERATIONAL if st.installed else Status.NEEDS_CONFIG))
            if not st.installed and t.installable:
                cb = QCheckBox(f"{t.name}  ({' '.join(t.packages)})")
                cb.setChecked(t.recommended)
                self.dep_checks.append((cb, t))
                row.addWidget(cb)
            else:
                row.addWidget(label(t.name + ("" if st.installed else f"  — {t.note or 'manual install'}"),
                                    None if st.installed else "Muted"))
            row.addWidget(label(t.description, "Faint", wrap=True), 1)
            self.dep_box.addLayout(row)
        self.dep_btn.setEnabled(bool(self.dep_checks))

    def _install(self):
        sel = [t for cb, t in self.dep_checks if cb.isChecked()]
        if not sel:
            return
        dlg = InstallDialog(self, [p for t in sel for p in t.packages], [f"{t.name}: {t.description}" for t in sel],
                            self.ctx.mock)
        dlg.exec()
        if dlg.ok:
            self._run_inspection()

    # ------------------------------------------------------------------ stage 3
    def _p_features(self):
        w = QWidget()
        v = QVBoxLayout(w)
        p = HudPanel("Feature matrix", "STAGE 03")
        self.f_summary = label("", "H3", wrap=True)
        p.add(self.f_summary)
        self.f_table = QTableWidget(0, 3)
        self.f_table.setHorizontalHeaderLabels(["FEATURE", "STATUS", "HOW / WHY"])
        self.f_table.verticalHeader().setVisible(False)
        self.f_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.f_table.setMinimumHeight(460)
        p.add(self.f_table)
        v.addWidget(p)
        return w

    def _fill_features(self):
        fs = self.ctx.features
        counts = {s: sum(1 for f in fs if f.status == s) for s in Status}
        self.f_summary.setText("  ·  ".join(f"{n} {s.value.lower()}" for s, n in counts.items() if n))
        self.f_table.setRowCount(len(fs))
        for r, f in enumerate(fs):
            self.f_table.setItem(r, 0, QTableWidgetItem(f.name))
            self.f_table.setCellWidget(r, 1, StatusBadge(f.status))
            self.f_table.setItem(r, 2, QTableWidgetItem(f"{f.mechanism}. {f.detail}".strip(". ")))
        self.f_table.resizeColumnToContents(0)
        self.f_table.resizeColumnToContents(1)

    # ------------------------------------------------------------------ stage 4
    def _p_config(self):
        w = QWidget()
        v = QVBoxLayout(w)
        p = HudPanel("Initial configuration", "STAGE 04")
        self.group = QButtonGroup(self)
        for i, n in enumerate(PRESET_NAMES):
            rb = QRadioButton(n.upper())
            rb.setChecked(n == self.ctx.settings.active_preset)
            self.group.addButton(rb, i)
            p.add(rb)
            p.add(label("    " + DESCRIPTIONS[n], "Faint", wrap=True))
        self.group.idToggled.connect(lambda *_: self._update_preview())
        self.preview = label("", "Mono", wrap=True)
        p.add(self.preview)
        self.apply_now = QCheckBox("Apply now (asks for your password)")
        self.apply_boot = QCheckBox("Also apply at every boot")
        p.add(self.apply_now)
        p.add(self.apply_boot)
        p.add(label("The current values are saved as a snapshot first, so you can always restore them "
                    "(GPU TUNING ▸ RESET TO DEFAULTS restores driver defaults).", "Faint", wrap=True))
        v.addWidget(p)
        v.addStretch(1)
        return w

    def _preset(self) -> str:
        return PRESET_NAMES[max(0, self.group.checkedId())]

    def _update_preview(self):
        name = self._preset()
        s, notes = preset_settings(name, self.ctx.caps)
        d = s.as_dict()
        txt = "WILL APPLY: " + (", ".join(f"{k}={v}" for k, v in d.items()) if d else "nothing (driver defaults)")
        if notes:
            txt += "\n" + "\n".join(notes)
        self.preview.setText(txt)
        ok = bool(d) and self.ctx.feature("power_limit") is not None and \
            self.ctx.feature("power_limit").status == Status.OPERATIONAL
        self.apply_now.setEnabled(ok)
        self.apply_boot.setEnabled(ok)
        if not ok:
            self.apply_now.setChecked(False)
            self.apply_boot.setChecked(False)

    def _apply_config(self) -> bool:
        name = self._preset()
        self.ctx.settings.active_preset = name
        self.ctx.settings.save()
        s, _ = preset_settings(name, self.ctx.caps)
        d = s.as_dict()
        snap = data_dir() / "original-tuning.json"
        if not snap.exists() and self.ctx.gpu and self.ctx.caps.power:
            save_json(snap, {"gpu": self.ctx.gpu.uuid, "power_w": self.ctx.caps.power.current_w,
                             "core_offset": self.ctx.caps.gpc_offset.current_mhz if self.ctx.caps.gpc_offset else None,
                             "mem_offset": self.ctx.caps.mem_offset.current_mhz if self.ctx.caps.mem_offset else None})
        self.result_lines = [f"Preset: {name}"]
        if self.apply_now.isChecked() and d:
            r = self.ctx.helper.apply(self.ctx.gpu_index, d)
            self.result_lines.append("Applied now: " + ("✓" if r.ok else f"✗ {r.error}"))
            if r.ok and self.apply_boot.isChecked():
                r2 = self.ctx.helper.save_startup(self.ctx.gpu_index, d)
                self.result_lines.append("Startup profile: " + ("✓" if r2.ok else f"✗ {r2.error}"))
            self.ctx.refresh_caps()
        else:
            self.result_lines.append("Nothing applied to hardware.")
        return True

    # ------------------------------------------------------------------ stage 5
    def _p_done(self):
        w = QWidget()
        v = QVBoxLayout(w)
        p = HudPanel("Configuration summary", "STAGE 05")
        self.summary = label("", "Mono", wrap=True)
        p.add(self.summary)
        v.addWidget(p)
        v.addWidget(label("ONE SYSTEM. TOTAL CONTROL.", "H1"), 0, Qt.AlignCenter)
        v.addStretch(1)
        return w

    def _fill_summary(self):
        g = self.ctx.gpu
        fs = self.ctx.features
        lines = [f"GPU       {g.name if g else '—'}", f"DRIVER    {g.driver_version if g else '—'}",
                 f"SESSION   {self.ctx.sysinfo.session} / {self.ctx.sysinfo.desktop}",
                 f"FEATURES  {sum(f.status == Status.OPERATIONAL for f in fs)} operational, "
                 f"{sum(f.status == Status.PER_GAME for f in fs)} per-game, "
                 f"{sum(f.status == Status.NEEDS_CONFIG for f in fs)} need configuration", ""]
        lines += getattr(self, "result_lines", [])
        self.summary.setText("\n".join(lines))
