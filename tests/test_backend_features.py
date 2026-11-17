from nvcontrol.backend import get_backend
from nvcontrol.backend.mock import MockBackend
from nvcontrol.backend.models import guess_arch_from_name, parse_driver_version, rtx_series
from nvcontrol.backend.smi_backend import FIELDS, parse_csv
from nvcontrol.capabilities.features import Status, build_matrix, smooth_motion_status
from nvcontrol.capabilities.system import mock_system
from nvcontrol.integrations.tools import TOOLS, install_command
from nvcontrol.tuning.presets import preset_settings


def matrix(**kw):
    b = MockBackend(**kw)
    return {f.id: f for f in build_matrix(mock_system(), b.gpus()[0], b.tuning_caps(0), b.name)}


def test_mock_backend_telemetry_ranges():
    b = get_backend(mock=True)
    t = b.telemetry(0)
    assert 0 <= t.util_gpu <= 100 and t.temp_c > 0 and t.power_w <= t.power_limit_w


def test_arch_and_series_parsing():
    assert guess_arch_from_name("NVIDIA GeForce RTX 4090") == "Ada Lovelace"
    assert guess_arch_from_name("NVIDIA GeForce RTX 5070 Ti") == "Blackwell"
    assert guess_arch_from_name("NVIDIA GeForce GTX 1660 SUPER") == "Turing"
    assert rtx_series("GeForce RTX 3080") == 30
    assert parse_driver_version("580.82.07") == (580, 82, 7)


def test_smooth_motion_gating():
    from nvcontrol.backend.models import GpuInfo
    g = lambda n, d, a: GpuInfo(0, n, driver_version=d, arch=a)  # noqa: E731
    assert smooth_motion_status(g("RTX 5080", "575.51.02", "Blackwell"))[0] == Status.PER_GAME
    assert smooth_motion_status(g("RTX 5080", "570.153", "Blackwell"))[0] == Status.UNSUPPORTED
    assert smooth_motion_status(g("RTX 4070", "580.82.07", "Ada Lovelace"))[0] == Status.PER_GAME
    assert smooth_motion_status(g("RTX 4070", "580.76.05", "Ada Lovelace"))[0] == Status.UNSUPPORTED
    assert smooth_motion_status(g("RTX 3080", "590.44", "Ampere"))[0] == Status.UNSUPPORTED


def test_matrix_rtx30_has_no_frame_gen():
    m = matrix(name="NVIDIA GeForce RTX 3080", arch="Ampere")
    assert m["dlss_fg"].status == Status.UNSUPPORTED
    assert m["dlss_mfg"].status == Status.UNSUPPORTED
    assert m["dlss_sr"].status == Status.PER_GAME


def test_matrix_rtx50_mfg():
    m = matrix(name="NVIDIA GeForce RTX 5090", arch="Blackwell")
    assert m["dlss_mfg"].status == Status.PER_GAME


def test_matrix_windows_only_marked():
    m = matrix()
    for fid in ("rtx_hdr", "dsr", "shadowplay", "low_latency"):
        assert m[fid].status == Status.WINDOWS_ONLY


def test_helper_missing_means_needs_config():
    b = MockBackend()
    s = mock_system()
    s.helper_installed = False
    m = {f.id: f for f in build_matrix(s, b.gpus()[0], b.tuning_caps(0), b.name)}
    assert m["power_limit"].status == Status.NEEDS_CONFIG


def test_wayland_vibrance_requires_nvibrant():
    m = matrix()
    assert m["vibrance"].status == Status.NEEDS_CONFIG
    assert m["gamma"].status == Status.UNSUPPORTED


def test_no_gpu_matrix():
    m = {f.id: f for f in build_matrix(mock_system(), None, MockBackend().tuning_caps(0).__class__(), "none")}
    assert m["telemetry"].status == Status.UNSUPPORTED
    assert m["smooth_motion"].status == Status.UNSUPPORTED


def test_smi_csv_parser():
    vals = ["0", "NVIDIA GeForce RTX 4070", "GPU-x", "580.95.05", "12282", "900", "45", "3", "1", "210",
            "405", "3105", "10501", "18.5", "200.00", "100.00", "220.00", "200.00", "[N/A]", "P8",
            "00000000:01:00.0", "95.04"]
    assert len(vals) == len(FIELDS)
    rows = parse_csv(", ".join(vals))
    assert rows[0]["name"] == "NVIDIA GeForce RTX 4070" and rows[0]["fan.speed"] == "[N/A]"


def test_presets_respect_driver_limits():
    caps = MockBackend().tuning_caps(0)
    s, _ = preset_settings("Maximum Performance", caps)
    assert s.power_w == caps.power.max_w
    s, _ = preset_settings("Power Efficient", caps)
    assert caps.power.min_w <= s.power_w <= caps.power.default_w
    assert s.core_offset is None  # presets never overclock


def test_install_command_is_exact_and_sanitized():
    cmd = install_command(["lact", "mangohud; rm -rf /"])
    assert cmd[:5] == ["pkexec", "pacman", "-S", "--needed", "--noconfirm"]
    assert "mangohud; rm -rf /" not in cmd


def test_only_repo_tools_autoinstall():
    for t in TOOLS:
        if t.repo in ("aur", "pypi"):
            assert not t.installable


def test_nvibrant_connector_parsing_and_apply_all(monkeypatch):
    from nvcontrol.core import runner
    from nvcontrol.integrations import display as D
    out = ("Display 0:\n• (0, HDMI)  Set Vibrance (  512)  Success\n"
           "• (1, DP  )  Set Vibrance (    0)  Success\n• (2, DP  )  Set Vibrance (    0)  Success\n"
           "• (3, DP  )  Set Vibrance (    0)  Success\n")
    assert D.nvibrant_connector_count(out) == 4
    assert D.nvibrant_connector_count("garbage") == 0
    calls = []
    monkeypatch.setattr(runner, "run", lambda argv, **k: calls.append(argv) or runner.Result(True, 0, out, ""))
    r, n = D.nvibrant_set_all(512)
    assert r.ok and n == 4
    assert calls[-1] == ["nvibrant", "512", "512", "512", "512"]   # every port, not just the first
