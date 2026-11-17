"""Logging: rotating file log, crash handler, Qt message capture, bug-report bundle.

Log location: $XDG_STATE_HOME/nvcontrol/logs/nvcontrol.log  (default ~/.local/state/...)
Privileged helper log: /var/log/nvcontrol-helper.log
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
import traceback
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
HELPER_LOG = Path("/var/log/nvcontrol-helper.log")
_crash_callbacks: list = []


def log_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    p = Path(base) / "nvcontrol" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_file() -> Path:
    return log_dir() / "nvcontrol.log"


def setup(verbose: bool = False) -> Path:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)
    fh = logging.handlers.RotatingFileHandler(log_file(), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG if verbose else logging.WARNING)
    sh.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(sh)
    sys.excepthook = _excepthook
    threading.excepthook = lambda a: _excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    from .. import __version__
    logging.getLogger("nvcontrol").info(
        "=== NV//CONTROL %s start | python %s | %s ===", __version__, platform.python_version(), platform.platform())
    return log_file()


def on_crash(cb) -> None:
    """Register a callback(text) shown to the user on unhandled exceptions."""
    _crash_callbacks.append(cb)


def _excepthook(etype, value, tb):
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    text = "".join(traceback.format_exception(etype, value, tb))
    logging.getLogger("nvcontrol.crash").critical("Unhandled exception:\n%s", text)
    for cb in _crash_callbacks:
        try:
            cb(text)
        except Exception:  # noqa: BLE001
            pass


def install_qt_handler() -> None:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    qlog = logging.getLogger("qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def handler(mode, ctx, msg):
        qlog.log(levels.get(mode, logging.INFO), "%s", msg)

    qInstallMessageHandler(handler)


def tail(path: Path, lines: int = 300) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError as e:
        return f"(could not read {path}: {e})"


def bug_report(diagnostics: str = "") -> str:
    """Everything needed to diagnose a problem, as one paste-able text."""
    parts = ["# NV//CONTROL bug report", "", "## Diagnostics", diagnostics or "(not collected)", "",
             f"## Application log (last 300 lines of {log_file()})", "```", tail(log_file()), "```"]
    if HELPER_LOG.exists():
        parts += ["", f"## Privileged helper log ({HELPER_LOG})", "```", tail(HELPER_LOG, 80), "```"]
    return "\n".join(parts) + "\n"
