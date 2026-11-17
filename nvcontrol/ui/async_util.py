"""Run blocking work (pkexec, pacman, Steam scans) off the GUI thread."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal, Slot

log = logging.getLogger(__name__)
_live: set = set()


class _Worker(QObject):
    done = Signal(object, object)   # result, exception

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(self.fn(), None)
        except Exception as e:  # noqa: BLE001
            log.exception("background task failed")
            self.done.emit(None, e)


class _Receiver(QObject):
    """Lives on the GUI thread so the callback runs there (queued connection)."""

    def __init__(self, cb, th):
        super().__init__()
        self.cb, self.th = cb, th

    @Slot(object, object)
    def finish(self, res, exc):
        try:
            self.cb(res, exc)
        except Exception:  # noqa: BLE001
            log.exception("callback failed")
        finally:
            self.th.quit()


def run_async(fn, on_done) -> None:
    """fn() runs in a thread; on_done(result, exc) runs on the GUI thread."""
    for k in list(_live):          # drop finished threads from earlier calls
        if k[0].isFinished():
            _live.discard(k)
    th = QThread()
    w = _Worker(fn)
    r = _Receiver(on_done, th)
    w.moveToThread(th)
    th.started.connect(w.run)
    w.done.connect(r.finish)
    _live.add((th, w, r))
    th.start()


def wait_all(timeout_ms: int = 3000) -> None:
    """Called at shutdown so no worker thread is destroyed while running."""
    for th, _w, _r in list(_live):
        th.quit()
        th.wait(timeout_ms)


import atexit  # noqa: E402

atexit.register(wait_all)
