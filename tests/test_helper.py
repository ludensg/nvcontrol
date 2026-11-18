"""The root helper's validation logic, tested without root or a GPU."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nvh", Path(__file__).resolve().parents[1] / "nvcontrol" / "helper" / "nvcontrol_helper.py")
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)


def test_range_check():
    assert H.check_range("x", 5, 0, 10) == 5
    with pytest.raises(H.Invalid):
        H.check_range("x", 11, 0, 10)


def test_lock_validation():
    assert H.validate_lock(300, 2000, [210, 3105]) == (300, 2000)
    with pytest.raises(H.Invalid):
        H.validate_lock(2000, 300, [])
    with pytest.raises(H.Invalid):
        H.validate_lock(100, 4000, [210, 3105])


def test_startup_validation():
    assert H.validate_startup({"power_w": 250, "core_offset": 100})["gpu"] == 0
    with pytest.raises(H.Invalid):
        H.validate_startup({"power_w": 250, "rm": "-rf"})
    with pytest.raises(H.Invalid):
        H.validate_startup({"power_w": "250; reboot"})
    with pytest.raises(H.Invalid):
        H.validate_startup({"gpu": 99})


def test_safe_mode_flag():
    assert H.safe_mode_requested("quiet splash nvcontrol.safe=1")
    assert not H.safe_mode_requested("quiet splash")


def test_parser_rejects_unknown_commands():
    with pytest.raises(SystemExit):
        H.build_parser().parse_args(["exec", "rm"])
    with pytest.raises(SystemExit):
        H.build_parser().parse_args(["set-power-limit", "--watts", "abc"])


def test_requires_root(capsys, monkeypatch):
    monkeypatch.setattr(H.os, "geteuid", lambda: 1000)
    assert H.main(["set-power-limit", "--watts", "200"]) == H.EXIT_INVALID
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_apply_startup_crash_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "STARTUP_FILE", tmp_path / "tuning.json")
    monkeypatch.setattr(H, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(H, "PENDING", tmp_path / "state" / "boot-pending")
    calls = []
    monkeypatch.setattr(H, "apply_settings", lambda s: calls.append(s) or {"ok": 1})
    (tmp_path / "tuning.json").write_text(json.dumps({"power_w": 200}))
    assert H.op_apply_startup() == {"ok": 1}            # boot 1: applied, pending set
    assert "skipped" in H.op_apply_startup()             # crash before stable mark → skipped
    H.op_mark_stable()
    assert H.op_apply_startup() == {"ok": 1}
    assert len(calls) == 2


def test_mock_helper_enforces_range():
    from nvcontrol.backend.mock import MockBackend
    from nvcontrol.tuning.helper_client import MockHelperClient
    b = MockBackend()
    c = MockHelperClient(b)
    assert c.apply(0, {"power_w": 300, "core_offset": 50}, fan_auto=True).ok
    assert b.power_limit == 300 and b.gpc_offset == 50
    assert not c.apply(0, {"power_w": 9999}).ok
    assert c.reset_all(0).ok and b.gpc_offset == 0


def test_fan_curve_validation():
    ok = H.validate_curve([[40, 30], [60, 50], [80, 100]], fan_min=30)
    assert ok == [[40, 30], [60, 50], [80, 100]]
    for bad in ([[40, 30]],                                  # too few points
                [[60, 50], [40, 30]],                        # temps not increasing
                [[40, 60], [60, 50]],                        # speed decreasing
                [[40, 20], [60, 50]],                        # below driver minimum
                [[40, 30], [90, 80]],                        # doesn't reach 100 % by failsafe temp
                [[40, 30], [60, True]],                      # bool isn't a number
                "rm -rf /"):
        with pytest.raises(H.Invalid):
            H.validate_curve(bad, fan_min=30)


def test_fan_curve_interpolation_and_failsafe():
    pts = [[40, 30], [60, 50], [80, 100]]
    assert H.curve_speed(pts, 20) == 30
    assert H.curve_speed(pts, 50) == 40
    assert H.curve_speed(pts, 70) == 75
    assert H.curve_speed(pts, H.FAILSAFE_C) == 100
    assert H.curve_speed([[30, 30], [60, 60]], 62) == 60   # above last point keeps last value…
    assert H.curve_speed([[30, 30], [60, 60]], 66) == 100  # …until 5 °C past it


def test_new_lab_commands_parse():
    p = H.build_parser()
    assert p.parse_args(["set-temp-target", "--celsius", "80"]).celsius == 80
    assert p.parse_args(["set-fan", "--percent", "60", "--fan", "1"]).fan == 1
    assert p.parse_args(["set-persistence", "--state", "on"]).state == "on"
    with pytest.raises(SystemExit):
        p.parse_args(["set-persistence", "--state", "maybe"])
    with pytest.raises(SystemExit):
        p.parse_args(["lock-mem-clocks", "--min", "x", "--max", "1"])


def test_mock_helper_lab_ops():
    from nvcontrol.backend.mock import MockBackend
    from nvcontrol.tuning.helper_client import MockHelperClient
    b = MockBackend()
    c = MockHelperClient(b)
    assert c.set_temp_target(0, 75).ok and b.temp_target == 75
    assert not c.set_temp_target(0, 120).ok                 # outside driver range
    assert c.lock_mem(0, 10501, 11501).ok and b.mem_locked == (10501, 11501)
    assert c.set_persistence(0, True).ok and b.persistence
    assert c.set_fan_one(0, 1, 70).ok and b.fan_per[1] == 70
    assert not c.fan_curve(True).ok                         # no curve saved yet
    assert c.save_fan_curve(0, [[40, 30], [80, 100]]).ok and c.fan_curve(True).ok and b.fan_curve_on
