"""Shared application state + background telemetry worker."""
from __future__ import annotations

import logging

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot

from ..backend import get_backend
from ..backend.models import Telemetry, TuningCaps
from ..capabilities import system
from ..capabilities.driverhealth import diagnose, mock_health
from ..capabilities.features import build_matrix
from ..core.config import Settings
from ..profiles.store import ProfileStore
from ..tuning.helper_client import HelperClient, MockHelperClient

log = logging.getLogger(__name__)


class AppContext(QObject):
    caps_changed = Signal()
    theme_changed = Signal()

    def __init__(self, mock: bool = False):
        super().__init__()
        self.mock = mock
        self.settings = Settings.load()
        self.backend = get_backend(mock)
        log.info("backend: %s (%s)", self.backend.name, self.backend.source)
        self.helper = MockHelperClient(self.backend) if mock else HelperClient()
        self.store = ProfileStore()
        self.sysinfo = system.mock_system() if mock else system.SystemInfo()
        self.gpus = self.backend.gpus()
        self.gpu = self.gpus[min(self.settings.selected_gpu, len(self.gpus) - 1)] if self.gpus else None
        log.info("gpu: %s", self.gpu)
        self.caps = TuningCaps()
        self.features = []
        self.last: Telemetry = Telemetry()
        self.health = mock_health() if mock else None

    def detect_system(self):
        if not self.mock:
            self.sysinfo = system.detect()
            self.health = diagnose()
            (log.info if self.health.ok else log.error)(
                "driver health: %s | %s | kernel=%s userspace=%s | nvidia-smi: %s", self.health.state.value,
                self.health.title, self.health.kernel_version, self.health.userspace_version,
                self.health.smi_message[:300])
        log.info("system: %s, %s, %s session, kernel %s", self.sysinfo.distro, self.sysinfo.desktop,
                 self.sysinfo.session, self.sysinfo.kernel)
        self.refresh_caps()

    def refresh_caps(self):
        self.caps = self.backend.tuning_caps(self.gpu.index) if self.gpu else TuningCaps()
        self.features = build_matrix(self.sysinfo, self.gpu, self.caps, self.backend.name)
        self.caps_changed.emit()

    def feature(self, fid: str):
        return next((f for f in self.features if f.id == fid), None)

    @property
    def gpu_index(self) -> int:
        return self.gpu.index if self.gpu else 0


class TelemetryWorker(QObject):
    sample = Signal(object)

    def __init__(self, backend, index: int, interval_ms: int):
        super().__init__()
        self.backend, self.index, self.interval = backend, index, interval_ms
        self.timer: QTimer | None = None
        self._errors = 0

    @Slot()
    def start(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(self.interval)
        self.poll()

    @Slot(int)
    def set_interval(self, ms: int):
        self.interval = ms
        if self.timer:
            self.timer.setInterval(ms)

    @Slot()
    def poll(self):
        try:
            self.sample.emit(self.backend.telemetry(self.index))
            self._errors = 0
        except Exception:  # noqa: BLE001
            self._errors += 1
            if self._errors <= 3:
                log.exception("telemetry poll failed")

    @Slot()
    def stop(self):
        if self.timer:
            self.timer.stop()


class TelemetryThread(QObject):
    sample = Signal(object)
    _interval = Signal(int)

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.thread = QThread()
        self.worker = TelemetryWorker(ctx.backend, ctx.gpu_index, ctx.settings.poll_interval_ms)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.sample.connect(self.sample)
        self._interval.connect(self.worker.set_interval)

    def start(self):
        self.thread.start()

    def set_interval(self, ms: int):
        self._interval.emit(ms)

    def stop(self):
        QMetaObject.invokeMethod(self.worker, "stop", Qt.BlockingQueuedConnection)
        self.thread.quit()
        self.thread.wait(2000)
