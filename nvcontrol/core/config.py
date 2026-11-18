"""Application configuration storage (XDG paths, atomic JSON writes)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def _xdg(var: str, default: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v else Path.home() / default


def config_dir() -> Path:
    p = _xdg("XDG_CONFIG_HOME", ".config") / "nvcontrol"
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = _xdg("XDG_DATA_HOME", ".local/share") / "nvcontrol"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backup_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = _xdg("XDG_CACHE_HOME", ".cache") / "nvcontrol"
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write(path: Path | str, text: str, mode: int | None = None) -> None:
    """Write via temp file + fsync + rename, so readers never see half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        elif path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def backup_file(path: Path | str, tag: str) -> Path | None:
    """Copy a file into the backup dir with a timestamp. Returns backup path."""
    path = Path(path)
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = backup_dir() / f"{tag}-{stamp}-{path.name}"
    n = 1
    while dest.exists():
        dest = backup_dir() / f"{tag}-{stamp}-{n}-{path.name}"
        n += 1
    shutil.copy2(path, dest)
    return dest


def load_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path: Path, data: Any) -> None:
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


@dataclass
class Settings:
    first_run_done: bool = False
    poll_interval_ms: int = 1000
    graph_seconds: int = 120
    animations: bool = True
    scanlines: bool = False
    veneco_mode: bool = False
    sound_muted: bool = True          # never autoplay audio
    sound_volume: int = 30            # percent
    steam_access_granted: bool = False
    active_preset: str = "Balanced"
    startup_profile: str = ""
    selected_gpu: int = 0
    window_geometry: str = ""
    check_updates: bool = True
    extra: dict = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        raw = load_json(cls.path(), {})
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        s.poll_interval_ms = max(250, min(10000, int(s.poll_interval_ms)))
        s.sound_volume = max(0, min(100, int(s.sound_volume)))
        return s

    def save(self) -> None:
        save_json(self.path(), asdict(self))
