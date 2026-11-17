"""Steam library discovery and *safe* launch-option / compat-tool editing.

Rules (enforced here, not only in the UI):
* refuse to write while Steam runs (Steam rewrites its config on exit);
* back up every file before changing it;
* change only the target key, preserve everything else;
* write atomically, then re-read and verify;
* return the backup path for rollback.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..core import runner
from ..core.config import atomic_write, backup_file
from . import vdf

log = logging.getLogger(__name__)
APPID_RE = re.compile(r"^\d{1,10}$")

# Not games — Proton, runtimes, redistributables
NON_GAME_PATTERNS = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|SteamVR)", re.I)


@dataclass
class Game:
    appid: str
    name: str
    installdir: str
    library: Path
    size_bytes: int = 0

    @property
    def compatdata(self) -> Path:
        return self.library / "steamapps" / "compatdata" / self.appid


@dataclass
class CompatTool:
    name: str        # internal name used in config.vdf
    display: str
    path: Path
    kind: str        # official | custom | system


class SteamError(RuntimeError):
    pass


def candidate_roots() -> list[Path]:
    home = Path.home()
    return [home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root",
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]


def find_root(roots: list[Path] | None = None) -> Path | None:
    seen = set()
    for r in roots or candidate_roots():
        try:
            real = r.resolve()
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        if (real / "steamapps").is_dir() or (real / "config" / "config.vdf").exists():
            return real
    return None


def steam_running(root: Path | None = None) -> bool:
    if runner.process_running("steam") or runner.process_running("steamwebhelper"):
        return True
    if root:
        pidf = Path.home() / ".steam" / "steam.pid"
        try:
            pid = int(pidf.read_text().strip())
            return Path(f"/proc/{pid}").exists() and \
                "steam" in Path(f"/proc/{pid}/comm").read_text().lower()
        except (OSError, ValueError):
            pass
    return False


class Steam:
    def __init__(self, root: Path):
        self.root = root

    # ------------------------------------------------------------ discovery
    def libraries(self) -> list[Path]:
        libs = [self.root]
        f = self.root / "steamapps" / "libraryfolders.vdf"
        if f.exists():
            try:
                data = vdf.loads(f.read_text(encoding="utf-8", errors="replace"))
                lf = vdf.get_ci(data, "libraryfolders") or {}
                for v in lf.values():
                    p = v.get("path") if isinstance(v, dict) else v
                    if p:
                        pp = Path(p)
                        if pp.exists() and pp.resolve() not in [l.resolve() for l in libs]:
                            libs.append(pp)
            except vdf.VdfError:
                pass
        return libs

    def games(self) -> list[Game]:
        out: dict[str, Game] = {}
        for lib in self.libraries():
            sa = lib / "steamapps"
            for acf in sa.glob("appmanifest_*.acf"):
                try:
                    st = vdf.get_ci(vdf.loads(acf.read_text(encoding="utf-8", errors="replace")), "AppState") or {}
                except (vdf.VdfError, OSError):
                    continue
                appid, name = str(st.get("appid", "")), st.get("name", "")
                if not APPID_RE.match(appid) or not name or NON_GAME_PATTERNS.match(name):
                    continue
                out[appid] = Game(appid, name, st.get("installdir", ""), lib,
                                  int(st.get("SizeOnDisk", 0) or 0))
        return sorted(out.values(), key=lambda g: g.name.lower())

    def user_ids(self) -> list[str]:
        ud = self.root / "userdata"
        if not ud.is_dir():
            return []
        ids = [p.name for p in ud.iterdir() if p.name.isdigit() and p.name != "0"
               and (p / "config" / "localconfig.vdf").exists()]
        return sorted(ids, key=lambda i: (self.root / "userdata" / i / "config" / "localconfig.vdf").stat().st_mtime,
                      reverse=True)

    def localconfig_path(self, user: str | None = None) -> Path:
        ids = self.user_ids()
        if not ids:
            raise SteamError("No Steam user profile found (log into Steam once).")
        user = user or ids[0]
        if user not in ids:
            raise SteamError(f"Unknown Steam user {user}")
        return self.root / "userdata" / user / "config" / "localconfig.vdf"

    def compat_tools(self) -> list[CompatTool]:
        tools: list[CompatTool] = []
        for lib in self.libraries():
            for p in sorted((lib / "steamapps" / "common").glob("Proton*")):
                if (p / "proton").exists():
                    internal = _official_internal_name(p.name)
                    tools.append(CompatTool(internal, p.name, p, "official"))
        for base, kind in ((self.root / "compatibilitytools.d", "custom"),
                           (Path("/usr/share/steam/compatibilitytools.d"), "system")):
            if base.is_dir():
                for p in sorted(base.iterdir()):
                    vf = p / "compatibilitytool.vdf"
                    if not vf.exists():
                        continue
                    try:
                        ct = vdf.get_ci(vdf.loads(vf.read_text(errors="replace")), "compatibilitytools",
                                        "compat_tools") or {}
                    except vdf.VdfError:
                        continue
                    for internal, meta in ct.items():
                        disp = meta.get("display_name", internal) if isinstance(meta, dict) else internal
                        tools.append(CompatTool(internal, disp, p, kind))
        return tools

    # ------------------------------------------------------------ read
    def get_launch_options(self, appid: str, user: str | None = None) -> str:
        data = vdf.loads(self.localconfig_path(user).read_text(encoding="utf-8", errors="replace"))
        app = vdf.get_ci(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", appid)
        return (vdf.get_ci(app, "LaunchOptions") or "") if isinstance(app, dict) else ""

    def get_compat_tool(self, appid: str) -> str | None:
        cfg = self.root / "config" / "config.vdf"
        if not cfg.exists():
            return None
        data = vdf.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        m = vdf.get_ci(data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", appid)
        return m.get("name") or None if isinstance(m, dict) else None

    # ------------------------------------------------------------ write
    def _guard(self):
        if steam_running(self.root):
            raise SteamError("Steam is running. Close Steam completely (Steam ▸ Exit) before writing "
                             "launch options — Steam overwrites its config when it exits.")

    def set_launch_options(self, appid: str, options: str, user: str | None = None) -> Path:
        if not APPID_RE.match(appid):
            raise SteamError("invalid appid")
        if "\n" in options or "\x00" in options or len(options) > 4096:
            raise SteamError("launch options contain invalid characters or are too long")
        self._guard()
        path = self.localconfig_path(user)
        original = path.read_text(encoding="utf-8", errors="replace")
        data = vdf.loads(original)
        app = vdf.get_ci(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", appid, create=True)
        key = next((k for k in app if k.lower() == "launchoptions"), "LaunchOptions")
        app[key] = options
        backup = backup_file(path, f"localconfig-{appid}")
        log.info("writing launch options app=%s backup=%s options=%r", appid, backup, options)
        atomic_write(path, vdf.dumps(data))
        if self.get_launch_options(appid, user) != options:
            if backup:
                shutil.copy2(backup, path)
            log.error("launch option verification failed for %s; restored %s", appid, backup)
            raise SteamError("Verification failed — original file restored.")
        return backup  # type: ignore[return-value]

    def set_compat_tool(self, appid: str, tool_name: str | None) -> Path | None:
        if not APPID_RE.match(appid):
            raise SteamError("invalid appid")
        if tool_name is not None and not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", tool_name):
            raise SteamError("invalid compat tool name")
        self._guard()
        path = self.root / "config" / "config.vdf"
        if not path.exists():
            raise SteamError("config.vdf not found")
        data = vdf.loads(path.read_text(encoding="utf-8", errors="replace"))
        mapping = vdf.get_ci(data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping",
                             create=True)
        if tool_name is None:
            k = next((k for k in mapping if k == appid), None)
            if k:
                del mapping[k]
        else:
            mapping[appid] = {"name": tool_name, "config": "", "priority": "250"}
        backup = backup_file(path, f"config-{appid}")
        atomic_write(path, vdf.dumps(data))
        if self.get_compat_tool(appid) != tool_name:
            if backup:
                shutil.copy2(backup, path)
            raise SteamError("Verification failed — original file restored.")
        return backup

    def restore(self, backup: Path, target: Path) -> None:
        self._guard()
        if not backup.exists():
            raise SteamError("backup missing")
        atomic_write(target, backup.read_text(encoding="utf-8", errors="replace"))


def _official_internal_name(dirname: str) -> str:
    """Map 'Proton 9.0 (Beta)' -> 'proton_9', 'Proton - Experimental' -> 'proton_experimental'."""
    d = dirname.lower()
    if "experimental" in d:
        return "proton_experimental"
    if "hotfix" in d:
        return "proton_hotfix"
    m = re.search(r"(\d+)\.(\d+)", d)
    if m:
        major, minor = m.groups()
        return f"proton_{major}" if minor == "0" else f"proton_{major}{minor}"
    return re.sub(r"[^a-z0-9]+", "_", d).strip("_")


def open_steam(root: Path | None = None) -> Steam | None:
    root = root or find_root()
    return Steam(root) if root else None


def create_mock_steam(root: Path) -> Path:
    """Fake Steam tree for --mock mode and tests. Never touches a real install."""
    games = [("1091500", "Cyberpunk 2077"), ("1245620", "ELDEN RING"), ("2050650", "Resident Evil 4"),
             ("1086940", "Baldur's Gate 3"), ("553850", "HELLDIVERS 2"), ("1145360", "Hades"),
             ("1493710", "Proton Experimental")]
    sa = root / "steamapps"
    (sa / "common").mkdir(parents=True, exist_ok=True)
    for appid, name in games:
        f = sa / f"appmanifest_{appid}.acf"
        if not f.exists():
            f.write_text(vdf.dumps({"AppState": {"appid": appid, "name": name,
                                                 "installdir": name.replace(" ", ""), "SizeOnDisk": "1"}}))
    for d in ("Proton 9.0 (Beta)", "Proton - Experimental"):
        (sa / "common" / d).mkdir(exist_ok=True)
        (sa / "common" / d / "proton").touch()
    ge = root / "compatibilitytools.d" / "GE-Proton10-25"
    ge.mkdir(parents=True, exist_ok=True)
    (ge / "compatibilitytool.vdf").write_text(vdf.dumps(
        {"compatibilitytools": {"compat_tools": {"GE-Proton10-25": {"display_name": "GE-Proton10-25"}}}}))
    (sa / "libraryfolders.vdf").write_text(vdf.dumps({"libraryfolders": {"0": {"path": str(root)}}}))
    lc = root / "userdata" / "12345678" / "config" / "localconfig.vdf"
    lc.parent.mkdir(parents=True, exist_ok=True)
    if not lc.exists():
        lc.write_text(vdf.dumps({"UserLocalConfigStore": {"friends": {"PersonaName": "Richard"},
                                 "Software": {"Valve": {"Steam": {"apps": {
                                     "1245620": {"LaunchOptions": "PROTON_LOG=1 %command%", "LastPlayed": "1"}}}}}}}))
    cfg = root / "config" / "config.vdf"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    if not cfg.exists():
        cfg.write_text(vdf.dumps({"InstallConfigStore": {"Software": {"Valve": {"Steam": {
            "CompatToolMapping": {"0": {"name": "proton_experimental", "config": "", "priority": "75"}}}}}}}))
    return root


def env_home_ok() -> bool:
    return bool(os.environ.get("HOME"))
