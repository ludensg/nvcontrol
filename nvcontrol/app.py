"""Entry point: `nvcontrol [--mock] [--verbose] [--wizard] [--diagnostics] [--veneco]`."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import APP_NAME, __version__


def _isolate_mock_home():
    """--mock never touches the real user config, Steam or MangoHud files."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "nvcontrol" / "mock-home"
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
        p = base / sub
        p.mkdir(parents=True, exist_ok=True)
        os.environ[var] = str(p)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="nvcontrol", description=f"{APP_NAME} — NVIDIA control center for Linux")
    ap.add_argument("--mock", action="store_true", help="simulated GPU and Steam library (no hardware access)")
    ap.add_argument("--verbose", "-v", action="store_true", help="debug-level logging (also to stderr)")
    ap.add_argument("--wizard", action="store_true", help="run the setup wizard again")
    ap.add_argument("--diagnostics", action="store_true", help="print a diagnostic report and exit")
    ap.add_argument("--bug-report", action="store_true", help="print diagnostics + recent logs and exit")
    ap.add_argument("--update", action="store_true", help="pull the latest version from GitHub and reinstall")
    ap.add_argument("--veneco", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    mock = args.mock or os.environ.get("NVCONTROL_MOCK", "") not in ("", "0")
    if mock:
        _isolate_mock_home()
    from .core import logs
    logfile = logs.setup(args.verbose)
    log = logging.getLogger("nvcontrol")
    if os.geteuid() == 0:
        print("NV//CONTROL must not run as root. Start it as your normal user; privileged actions use polkit.",
              file=sys.stderr)
        log.error("refused to start as root")
        return 1

    if args.update:
        from .core import updater
        return updater.run_in_this_terminal()

    if args.diagnostics or args.bug_report:
        from PySide6.QtCore import QCoreApplication
        QCoreApplication(sys.argv[:1])
        from .core.report import build_report
        from .ui.context import AppContext
        ctx = AppContext(mock)
        ctx.detect_system()
        rep = build_report(ctx)
        print(logs.bug_report(rep) if args.bug_report else rep)
        return 0

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("nvcontrol")
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName("nvcontrol")
    app.setWindowIcon(QIcon.fromTheme("nvcontrol", QIcon(str(Path(__file__).parent / "ui" / "nvcontrol.svg"))))
    logs.install_qt_handler()
    log.info("log file: %s, mock=%s", logfile, mock)

    from .ui import theme
    theme.init_fonts()
    app.setFont(theme.font("body", 10))
    from .ui.context import AppContext
    ctx = AppContext(mock)
    if args.veneco:
        ctx.settings.veneco_mode = True
    theme.set_mode("nvidia")
    app.setStyleSheet(theme.stylesheet())

    if args.wizard or not ctx.settings.first_run_done:
        from .ui.wizard import SetupWizard
        SetupWizard(ctx).exec()
        ctx.settings.first_run_done = True
        ctx.settings.save()
    else:
        ctx.detect_system()

    from .ui.main_window import MainWindow
    win = MainWindow(ctx)
    win.restyle()
    win.show()
    rc = app.exec()
    log.info("exit %s", rc)
    return rc
