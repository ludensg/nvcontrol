"""Updater against real temporary git repositories (no network)."""
import shutil
import subprocess

import pytest

from nvcontrol.core import updater
from nvcontrol.core.config import config_dir

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(cwd), "PATH": "/usr/bin:/bin"})


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    dev = tmp_path / "dev"
    subprocess.run(["git", "clone", str(origin), str(dev)], check=True, capture_output=True)
    (dev / "nvcontrol").mkdir()
    (dev / "nvcontrol" / "__init__.py").write_text('__version__ = "0.1.3"\n')
    (dev / "update.sh").write_text("#!/bin/bash\n")
    git(dev, "add", ".")
    git(dev, "commit", "-m", "v0.1.3")
    git(dev, "push", "-u", "origin", "main")
    friend = tmp_path / "friend"
    subprocess.run(["git", "clone", str(origin), str(friend)], check=True, capture_output=True)
    return dev, friend


def test_up_to_date(repos):
    _, friend = repos
    st = updater.check(friend)
    assert st.ok and st.behind == 0 and not st.available


def test_detects_new_version(repos):
    dev, friend = repos
    (dev / "nvcontrol" / "__init__.py").write_text('__version__ = "0.1.4"\n')
    git(dev, "commit", "-am", "v0.1.4: shiny")
    git(dev, "push")
    st = updater.check(friend)
    assert st.available and st.behind == 1 and st.latest == "0.1.4"
    assert any("shiny" in c for c in st.commits)


def test_source_dir_from_install_record(repos):
    _, friend = repos
    (config_dir() / "source_dir").write_text(str(friend) + "\n")
    assert updater.source_dir() == friend


def test_missing_source_is_explained(tmp_path):
    st = updater.check(tmp_path)   # not a git repo
    assert not st.ok and st.error


def test_terminal_command_prefers_konsole(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.runner, "which", lambda b: "/usr/bin/" + b if b in ("konsole", "xterm") else None)
    cmd = updater.terminal_command(tmp_path / "update.sh", "--force")
    assert cmd[:3] == ["konsole", "--hold", "-e"] and cmd[-2:] == [str(tmp_path / "update.sh"), "--force"]
