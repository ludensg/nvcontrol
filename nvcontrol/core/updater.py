"""Self-update: finds the git clone NV//CONTROL was installed from, checks GitHub for new
commits, and runs update.sh in a terminal (sudo/pacman need a real TTY for the password)."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from . import runner
from .config import config_dir

log = logging.getLogger(__name__)

# Terminal emulators, KDE's first. Each opens update.sh and keeps the window open afterwards.
TERMINALS = [
    ("konsole", ["--hold", "-e"]),
    ("kitty", ["--hold"]),
    ("alacritty", ["--hold", "-e"]),
    ("wezterm", ["start", "--"]),
    ("gnome-terminal", ["--"]),
    ("kgx", ["--"]),
    ("xfce4-terminal", ["--hold", "-x"]),
    ("xterm", ["-hold", "-e"]),
]


@dataclass
class UpdateStatus:
    ok: bool
    behind: int = 0
    current: str = __version__
    latest: str | None = None
    commits: list[str] = field(default_factory=list)
    error: str = ""
    source: Path | None = None

    @property
    def available(self) -> bool:
        return self.ok and self.behind > 0


def _valid(p: Path) -> bool:
    return (p / ".git").exists() and (p / "update.sh").exists()


def source_dir() -> Path | None:
    """install.sh records the clone path; fall back to common locations / a dev checkout."""
    f = config_dir() / "source_dir"
    cands: list[Path] = []
    try:
        cands.append(Path(f.read_text().strip()))
    except OSError:
        pass
    cands += [Path(__file__).resolve().parents[2], Path.home() / "nvcontrol"]
    for c in cands:
        if c and _valid(c):
            return c
    return None


def _git(src: Path, *args: str, timeout: float = 10) -> runner.Result:
    return runner.run(["git", "-C", str(src), *args], timeout=timeout,
                      env={"GIT_TERMINAL_PROMPT": "0"}, quiet=True)


def check(src: Path | None = None, fetch: bool = True) -> UpdateStatus:
    src = src or source_dir()
    if src is None:
        return UpdateStatus(False, error="Source folder not found. Install with install.sh from a git clone "
                                         "(git clone https://github.com/ludensg/nvcontrol.git).")
    if runner.which("git") is None:
        return UpdateStatus(False, error="git is not installed (sudo pacman -S git).", source=src)
    if fetch:
        r = _git(src, "fetch", "--quiet", "origin", timeout=30)
        if not r.ok:
            msg = r.err.strip().splitlines()[-1] if r.err.strip() else f"exit {r.code}"
            log.warning("update check: fetch failed: %s", msg)
            return UpdateStatus(False, error=f"Could not reach GitHub: {msg}", source=src)
    r = _git(src, "rev-list", "--count", "HEAD..@{u}")
    if not r.ok or not r.text.isdigit():
        return UpdateStatus(False, error="This clone has no upstream branch (git branch -u origin/main).",
                            source=src)
    behind = int(r.text)
    commits = _git(src, "log", "--oneline", "--no-decorate", "HEAD..@{u}").out.splitlines()[:30]
    latest = None
    rv = _git(src, "show", "@{u}:nvcontrol/__init__.py")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', rv.out) if rv.ok else None
    if m:
        latest = m.group(1)
    st = UpdateStatus(True, behind, __version__, latest, commits, "", src)
    log.info("update check: %d new commit(s), installed %s, latest %s", behind, __version__, latest)
    return st


def terminal_command(script: Path, *extra: str) -> list[str] | None:
    for exe, args in TERMINALS:
        if runner.which(exe):
            return [exe, *args, "bash", str(script), *extra]
    return None


def launch_update(src: Path | None = None, force: bool = False) -> tuple[bool, str]:
    src = src or source_dir()
    if src is None:
        return False, "Source folder not found."
    script = src / "update.sh"
    cmd = terminal_command(script, *(["--force"] if force else []))
    if cmd is None:
        return False, f"No terminal emulator found. Run manually:\n  bash {script}"
    ok = runner.launch_detached(cmd)
    return ok, " ".join(cmd)


def run_in_this_terminal(force: bool = False) -> int:
    """`nvcontrol --update`: replace this process with update.sh (or open a terminal if not on a TTY)."""
    src = source_dir()
    if src is None:
        print(check(fetch=False).error)
        return 1
    script = str(src / "update.sh")
    args = ["bash", script] + (["--force"] if force else [])
    if os.isatty(0):
        os.execvp("bash", args)
    ok, msg = launch_update(src, force)
    print(msg)
    return 0 if ok else 1
