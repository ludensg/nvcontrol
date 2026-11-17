from __future__ import annotations

from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QHeaderView, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem)

from ...capabilities.features import Status
from ...core import runner
from ...integrations import lact
from ...integrations.tools import TOOLS, launch_tool
from ..async_util import run_async
from ..install_dialog import InstallDialog
from ..widgets import HudPanel, StatusBadge, button, label
from .base import Page

DIAGS = [
    ("nvidia-smi", ["nvidia-smi", "-q"]),
    ("vulkaninfo", ["vulkaninfo", "--summary"]),
    ("Driver version", ["cat", "/proc/driver/nvidia/version"]),
    ("DRM modeset", ["cat", "/sys/module/nvidia_drm/parameters/modeset"]),
    ("Startup service", ["systemctl", "status", "--no-pager", "nvcontrol-apply.service"]),
    ("lactd", ["systemctl", "status", "--no-pager", "lactd"]),
    ("Kernel log (NVRM)", ["journalctl", "-k", "-b", "--no-pager", "-g", "NVRM|nvidia", "-n", "80"]),
]


class ToolsPage(Page):
    nav_key = "nav.tools"
    kicker = "// 07 · INTEGRATIONS"
    subtitle = "Launch, install and diagnose the tools NV//CONTROL builds on — no terminal needed."

    def __init__(self, ctx, main):
        super().__init__(ctx, main)
        self.tool_grid = QGridLayout()
        self.tool_grid.setSpacing(12)
        self.lay.addLayout(self.tool_grid)
        r = QHBoxLayout()
        r.addStretch(1)
        self.inst_all = button("INSTALL RECOMMENDED MISSING", "Primary", self._install_missing)
        r.addWidget(self.inst_all)
        self.lay.addLayout(r)

        dp = HudPanel("Diagnostics", "DRIVER · VULKAN · SERVICES")
        br = QHBoxLayout()
        for name, cmd in DIAGS:
            br.addWidget(button(name.upper(), None, lambda _=False, c=cmd, n=name: self._diag(n, c)))
        br.addWidget(button("LACT STATUS", None, self._lact))
        br.addStretch(1)
        dp.add(br)
        self.diag = QPlainTextEdit()
        self.diag.setObjectName("Mono")
        self.diag.setReadOnly(True)
        self.diag.setMinimumHeight(220)
        dp.add(self.diag)
        self.lay.addWidget(dp)

        fp = HudPanel("Feature matrix", "WHAT WORKS ON THIS MACHINE")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["FEATURE", "STATUS", "MECHANISM", "DETAIL"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setMinimumHeight(420)
        self.table.setWordWrap(True)
        fp.add(self.table)
        self.lay.addWidget(fp)
        self.lay.addStretch(1)
        self.on_caps()

    def on_caps(self):
        while self.tool_grid.count():
            it = self.tool_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, t in enumerate(TOOLS):
            st = self.ctx.sysinfo.tools.get(t.id)
            inst = bool(st and st.installed)
            card = HudPanel(t.name, t.category.upper())
            row = QHBoxLayout()
            row.addWidget(StatusBadge(Status.OPERATIONAL if inst else Status.NEEDS_CONFIG))
            row.addWidget(label(" ".join(t.packages) or t.id, "Mono"), 1)
            card.add(row)
            card.add(label(t.description, "Muted", wrap=True))
            if t.note and not inst:
                card.add(label(t.note, "Faint", wrap=True))
            br = QHBoxLayout()
            if t.launch:
                b = button("LAUNCH", None, lambda _=False, tid=t.id: self._launch(tid))
                b.setEnabled(inst)
                br.addWidget(b)
            if not inst and t.installable:
                br.addWidget(button("INSTALL", None, lambda _=False, tt=t: self._install([tt])))
            br.addStretch(1)
            card.add(br)
            self.tool_grid.addWidget(card, i // 3, i % 3)
        self.table.setRowCount(len(self.ctx.features))
        for r, f in enumerate(self.ctx.features):
            self.table.setItem(r, 0, QTableWidgetItem(f.name))
            self.table.setCellWidget(r, 1, StatusBadge(f.status))
            self.table.setItem(r, 2, QTableWidgetItem(f.mechanism))
            self.table.setItem(r, 3, QTableWidgetItem(" ".join(x for x in (f.requirement, f.detail) if x)))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

    def _launch(self, tid):
        if not launch_tool(tid):
            self.error("Launch failed", f"Could not start {tid}.")

    def _missing_recommended(self):
        return [st.tool for st in self.ctx.sysinfo.tools.values()
                if not st.installed and st.tool.recommended and st.tool.installable]

    def _install(self, tools):
        pkgs = [p for t in tools for p in t.packages]
        dlg = InstallDialog(self, pkgs, [f"{t.name}: {t.description}" for t in tools], self.ctx.mock)
        dlg.exec()
        if dlg.ok:
            self.main.redetect()

    def _install_missing(self):
        miss = self._missing_recommended()
        if not miss:
            self.info("Dependencies", "All recommended packages are installed.")
            return
        self._install(miss)

    def _diag(self, name, cmd):
        self.diag.setPlainText(f"$ {' '.join(cmd)}\n…")

        def done(r, exc):
            if exc:
                self.diag.setPlainText(str(exc))
                return
            self.diag.setPlainText(f"$ {' '.join(cmd)}\n\n{r.out}{r.err}" if (r.out or r.err)
                                   else f"$ {' '.join(cmd)}\n\n(no output, exit {r.code})")
        run_async(lambda: runner.run(cmd, timeout=20), done)

    def _lact(self):
        run_async(lact.status, lambda r, e: self.diag.setPlainText(
            f"LACT daemon: {r[0]}\n{r[1]}" if r else str(e)))
