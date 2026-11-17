"""Builds every page against the mock GPU (offscreen) and flips Veneco Mode."""
import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    from nvcontrol.ui import theme
    theme.init_fonts()
    a.setStyleSheet(theme.stylesheet())
    return a


def test_main_window_and_veneco(app):
    from nvcontrol.backend.models import Telemetry
    from nvcontrol.ui import theme
    from nvcontrol.ui.context import AppContext
    from nvcontrol.ui.labels import L
    from nvcontrol.ui.main_window import MainWindow
    ctx = AppContext(mock=True)
    ctx.detect_system()
    w = MainWindow(ctx)
    for i in range(len(w.pages)):
        w.show_page(i)
    w._on_sample(ctx.backend.telemetry(0))
    w._on_sample(Telemetry())          # all-None telemetry must not crash
    before = {k: ctx.backend.power_limit for k in ("p",)}
    w._set_veneco(True, intro=False)
    assert theme.is_veneco() and L("nav.command") == "CENTRO DE COMANDO DEL COÑO"
    assert ctx.backend.power_limit == before["p"]   # cosmetic only
    w._set_veneco(False, intro=False)
    assert not theme.is_veneco()
    w.close()


def test_wizard_builds(app):
    from nvcontrol.ui.context import AppContext
    from nvcontrol.ui.wizard import SetupWizard
    ctx = AppContext(mock=True)
    ctx.detect_system()
    wz = SetupWizard(ctx)
    for i in range(5):
        wz._go(i)
    wz.close()
