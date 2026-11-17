"""MangoHud configuration files (key=value, unknown lines preserved)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..core.config import atomic_write, backup_file

KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")
VAL_RE = re.compile(r"^[A-Za-z0-9_+.,#:/ \-]{0,200}$")

PRESETS: dict[str, dict[str, str | None]] = {
    "Minimal (FPS only)": {"fps": None, "frametime": "0", "gpu_stats": "0", "cpu_stats": "0",
                           "position": "top-left"},
    "Standard": {"fps": None, "frametime": None, "frame_timing": None, "gpu_stats": None,
                 "gpu_temp": None, "gpu_power": None, "cpu_stats": None, "cpu_temp": None,
                 "vram": None, "ram": None, "position": "top-left"},
    "Full diagnostics": {"fps": None, "frametime": None, "frame_timing": None, "gpu_stats": None,
                         "gpu_temp": None, "gpu_core_clock": None, "gpu_mem_clock": None,
                         "gpu_power": None, "gpu_fan": None, "throttling_status": None,
                         "cpu_stats": None, "cpu_temp": None, "core_load": None, "vram": None,
                         "ram": None, "vulkan_driver": None, "engine_version": None, "wine": None,
                         "position": "top-left"},
}


def config_root() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "MangoHud"


def global_config_path() -> Path:
    return config_root() / "MangoHud.conf"


def profile_config_path(appid: str) -> Path:
    if not appid.isdigit():
        raise ValueError("appid must be numeric")
    return config_root() / f"nvcontrol-{appid}.conf"


def parse(text: str) -> list[tuple[str | None, str | None, str]]:
    """Returns list of (key, value, raw_line). key None for comments/blank."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            out.append((None, None, line))
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            out.append((k.strip(), v.strip(), line))
        else:
            out.append((s, None, line))
    return out


def update(text: str, changes: dict[str, str | None | bool]) -> str:
    """Apply changes: value str -> key=value, None -> bare flag, False -> remove key."""
    for k, v in changes.items():
        if not KEY_RE.match(k):
            raise ValueError(f"invalid MangoHud key {k!r}")
        if isinstance(v, str) and not VAL_RE.match(v):
            raise ValueError(f"invalid MangoHud value for {k}")
    lines = parse(text)
    done = set()
    result = []
    for key, _val, raw in lines:
        if key is not None and key in changes:
            v = changes[key]
            done.add(key)
            if v is False:
                continue
            result.append(key if v is None else f"{key}={v}")
        else:
            result.append(raw)
    for k, v in changes.items():
        if k not in done and v is not False:
            result.append(k if v is None else f"{k}={v}")
    return "\n".join(result).rstrip("\n") + "\n"


def write_config(path: Path, changes: dict, header: str = "") -> Path | None:
    existing = path.read_text(encoding="utf-8") if path.exists() else (f"# {header}\n" if header else "")
    backup = backup_file(path, "mangohud") if path.exists() else None
    atomic_write(path, update(existing, changes))
    return backup


def read_config(path: Path) -> dict[str, str | None]:
    if not path.exists():
        return {}
    return {k: v for k, v, _ in parse(path.read_text(encoding="utf-8")) if k}
