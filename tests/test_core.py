import json

import pytest

from nvcontrol.core import config, logs, runner


def test_runner_rejects_shell_strings():
    with pytest.raises(TypeError):
        runner.run("echo hi; rm -rf /")


def test_runner_rejects_nul():
    with pytest.raises(ValueError):
        runner.run(["echo", "a\x00b"])


def test_runner_missing_binary_is_reported():
    r = runner.run(["definitely-not-a-real-binary-xyz"])
    assert not r.ok and r.code == 127


def test_runner_timeout():
    r = runner.run(["sleep", "5"], timeout=0.3)
    assert not r.ok and r.code == 124


def test_runner_ok():
    r = runner.run(["echo", "hello"])
    assert r.ok and r.text == "hello"


def test_atomic_write_and_backup(tmp_path):
    f = tmp_path / "x.conf"
    config.atomic_write(f, "one\n")
    config.atomic_write(f, "two\n")
    assert f.read_text() == "two\n"
    b = config.backup_file(f, "t")
    assert b and b.read_text() == "two\n"
    assert not list(tmp_path.glob(".x.conf.*"))  # no temp files left


def test_settings_roundtrip_and_clamp():
    s = config.Settings.load()
    assert s.sound_muted is True  # never autoplay
    s.poll_interval_ms = 5
    s.save()
    raw = json.loads(config.Settings.path().read_text())
    raw["unknown_key"] = 1
    config.Settings.path().write_text(json.dumps(raw))
    s2 = config.Settings.load()
    assert s2.poll_interval_ms == 250


def test_logging_and_bug_report():
    path = logs.setup(verbose=True)
    import logging
    logging.getLogger("nvcontrol.test").error("boom-marker")
    for h in logging.getLogger().handlers:
        h.flush()
    assert "boom-marker" in path.read_text()
    rep = logs.bug_report("DIAG")
    assert "DIAG" in rep and "boom-marker" in rep


def test_excepthook_logs_crash():
    path = logs.setup()
    seen = []
    logs.on_crash(seen.append)
    try:
        raise RuntimeError("crash-marker")
    except RuntimeError as e:
        logs._excepthook(type(e), e, e.__traceback__)
    import logging
    for h in logging.getLogger().handlers:
        h.flush()
    assert "crash-marker" in path.read_text()
    assert seen and "crash-marker" in seen[0]
