"""Profile persistence: per-game profiles, global defaults, import/export."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..core.config import atomic_write, config_dir, load_json, save_json
from .game_profile import GameProfile


def profiles_dir() -> Path:
    p = config_dir() / "profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


class ProfileStore:
    DEFAULTS_ID = "defaults"

    def __init__(self, base: Path | None = None):
        self.base = base or profiles_dir()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, appid: str) -> Path:
        if appid != self.DEFAULTS_ID and not appid.isdigit():
            raise ValueError("invalid appid")
        return self.base / f"{appid}.json"

    def defaults(self) -> GameProfile:
        d = load_json(self._path(self.DEFAULTS_ID), None)
        return GameProfile.from_dict(d) if d else GameProfile()

    def save_defaults(self, p: GameProfile) -> None:
        d = p.to_dict()
        d["appid"], d["name"] = "", ""
        save_json(self._path(self.DEFAULTS_ID), d)

    def get(self, appid: str, name: str = "") -> GameProfile:
        d = load_json(self._path(appid), None)
        if d:
            return GameProfile.from_dict(d)
        base = self.defaults()
        base.appid, base.name = appid, name
        return base

    def exists(self, appid: str) -> bool:
        return self._path(appid).exists()

    def save(self, p: GameProfile) -> None:
        p.validate()
        save_json(self._path(p.appid), p.to_dict())

    def delete(self, appid: str) -> None:
        self._path(appid).unlink(missing_ok=True)

    def all(self) -> list[GameProfile]:
        out = []
        for f in sorted(self.base.glob("*.json")):
            if f.stem == self.DEFAULTS_ID:
                continue
            d = load_json(f, None)
            if d:
                try:
                    out.append(GameProfile.from_dict(d))
                except (TypeError, ValueError):
                    continue
        return out

    def export_bundle(self, dest: Path) -> int:
        items = [p.to_dict() for p in self.all()]
        bundle = {"format": "nvcontrol-profiles", "version": 1, "exported": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "defaults": self.defaults().to_dict(), "profiles": items}
        atomic_write(dest, json.dumps(bundle, indent=2) + "\n")
        return len(items)

    def import_bundle(self, src: Path, overwrite: bool = False) -> int:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        if data.get("format") != "nvcontrol-profiles":
            raise ValueError("Not an NV//CONTROL profile bundle")
        n = 0
        for d in data.get("profiles", []):
            p = GameProfile.from_dict(d)
            if not p.appid or (self.exists(p.appid) and not overwrite):
                continue
            self.save(p)
            n += 1
        return n
