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


def test_output_selection_survives_refresh_and_resume(app, monkeypatch):
    from nvcontrol.ui.context import AppContext
    from nvcontrol.ui.main_window import MainWindow, ResumeWatcher
    ctx = AppContext(mock=True)
    ctx.detect_system()
    w = MainWindow(ctx)
    from nvcontrol.ui.pages.display import DisplayPage
    page = next(p for p in w.pages if isinstance(p, DisplayPage))
    page.out.setCurrentIndex(1)
    name = page._cur().name
    page.on_caps()                                  # what APPLY OUTPUT triggers via refresh
    assert page._cur().name == name                 # bug 1: selection no longer jumps back
    # bug 2: after resume, a dimmed output is put back to the remembered brightness
    page._remember_brightness("DP-1", 80)
    ctx.sysinfo.displays[0].brightness = 20         # what KDE came back with
    sent = []
    monkeypatch.setattr(page, "_set", lambda n, prop, v: sent.append((n, prop, v)))
    from nvcontrol.ui import async_util
    monkeypatch.setattr(async_util, "run_async", lambda fn, cb: cb(fn(), None))
    import nvcontrol.ui.pages.display as dmod
    monkeypatch.setattr(dmod, "run_async", lambda fn, cb: cb(fn(), None))
    page.on_resume()
    assert ("DP-1", "brightness", "80") in sent
    # watcher detects a sleep gap
    rw = ResumeWatcher(w)
    got = []
    rw.resumed.connect(got.append)
    rw.offset -= 120
    rw._tick()
    assert got and got[0] >= 119
    w.close()


def test_kscreen_brightness_parsing():
    from nvcontrol.integrations.display import _brightness_pct
    assert _brightness_pct(1.0) == 100 and _brightness_pct(1) == 100
    assert _brightness_pct(0.35) == 35 and _brightness_pct(70) == 70
    assert _brightness_pct(None) is None


def test_global_graphics_and_lab_pages(app, monkeypatch):
    from nvcontrol.integrations import globalenv as G
    from nvcontrol.ui.context import AppContext
    from nvcontrol.ui.main_window import MainWindow
    from nvcontrol.ui.pages.global_graphics import GlobalGraphicsPage
    from nvcontrol.ui.pages.lab import LabPage
    ctx = AppContext(mock=True)
    ctx.detect_system()
    w = MainWindow(ctx)
    gp = next(p for p in w.pages if isinstance(p, GlobalGraphicsPage))
    gp.widgets["anisotropic"].setCurrentIndex(gp.widgets["anisotropic"].findData("16x"))
    gp.widgets["max_fps"].setValue(297)
    assert "d3d11.samplerAnisotropy = 16" in gp.preview.toPlainText()
    assert not gp.widgets["dlss_mfg_count"].isEnabled()          # RTX 4080 mock → no MFG
    gp._apply()
    assert "dxgi.maxFrameRate = 297" in G.dxvk_path().read_text()
    lab = next(p for p in w.pages if isinstance(p, LabPage))
    assert lab.tt.isEnabled() and lab.tt.minimum() == 65 and len(lab.fan_sliders) == 2
    w.show()
    w.show_page(w.pages.index(lab))
    lab.tabs.setCurrentIndex(2)
    lab._refresh_sensors()
    assert lab.sens.rowCount() > 5
    w.close()
