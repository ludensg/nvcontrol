"""Safe subprocess execution.

Every external command in NV//CONTROL goes through this module:

* commands are argument lists, never shell strings (``shell=False`` always);
* every call has a timeout;
* missing binaries are reported, not raised.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence

log = logging.getLogger(__name__)


@dataclass
class Result:
    ok: bool
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out.strip()


def which(name: str) -> str | None:
    return shutil.which(name)


def _validate(args: Sequence[str]) -> list[str]:
    if isinstance(args, (str, bytes)):
        raise TypeError("commands must be argument lists, not shell strings")
    argv = list(args)
    if not argv:
        raise ValueError("empty command")
    for a in argv:
        if not isinstance(a, str):
            raise TypeError(f"argument {a!r} is not a string")
        if "\x00" in a:
            raise ValueError("NUL byte in argument")
    return argv


def run(
    args: Sequence[str],
    timeout: float = 5.0,
    env: Mapping[str, str] | None = None,
    stdin: str | None = None,
    quiet: bool = False,
) -> Result:
    argv = _validate(args)
    exe = argv[0]
    if not os.path.isabs(exe) and which(exe) is None:
        log.debug("not installed: %s", exe)
        return Result(False, 127, "", f"{exe}: command not found")
    full_env = None
    if env is not None:
        full_env = dict(os.environ)
        full_env.update(env)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
            input=stdin,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("timeout after %.1fs: %s", timeout, argv[0])
        return Result(False, 124, "", f"{exe}: timed out after {timeout:.0f}s")
    except OSError as e:
        log.error("exec failed %s: %s", argv, e)
        return Result(False, 126, "", f"{exe}: {e}")
    if proc.returncode == 0:
        log.debug("ok: %s", argv)
    else:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()   # nvidia-smi prints errors on stdout
        (log.debug if quiet else log.warning)("exit %d: %s | output: %s", proc.returncode, argv, detail[:500])
    return Result(proc.returncode == 0, proc.returncode, proc.stdout, proc.stderr)


def launch_detached(args: Sequence[str]) -> bool:
    """Start a GUI tool without waiting for it."""
    argv = _validate(args)
    if not os.path.isabs(argv[0]) and which(argv[0]) is None:
        return False
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            shell=False,
        )
        log.info("launched %s", argv)
        return True
    except OSError as e:
        log.error("launch failed %s: %s", argv[0], e)
        return False


def process_running(name: str) -> bool:
    """True if a process with this exact command name runs (reads /proc, no pgrep needed)."""
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                    if f.read().strip() == name:
                        return True
            except OSError:
                continue
    except OSError:
        pass
    return False
