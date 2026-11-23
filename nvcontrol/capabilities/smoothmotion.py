"""Smooth Motion verification.

How we know it's really working (per NVIDIA's README, chapter "NVIDIA Smooth Motion"):
* NVPRESENT_ENABLE_SMOOTH_MOTION=1 enables the implicit Vulkan layer VK_LAYER_NV_present.
* If that layer's shared library is mapped into the game process, Smooth Motion is active.
* NVPRESENT_LOG_LEVEL=4 + NVPRESENT_LOG_FILE=… makes the layer write a log; no log = layer never loaded.

We check three things: preflight (GPU, driver, layer installed, Vulkan), live processes
(/proc/<pid>/environ + /proc/<pid>/maps), and the optional per-game verification log.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..backend.models import GpuInfo, parse_driver_version
from .driverhealth import DriverHealth
from .features import Status, smooth_motion_status

log = logging.getLogger(__name__)

LAYER_NAME = "VK_LAYER_NV_present"
ENV = "NVPRESENT_ENABLE_SMOOTH_MOTION"
LAYER_DIRS = ["/usr/share/vulkan/implicit_layer.d", "/etc/vulkan/implicit_layer.d",
              "/usr/local/share/vulkan/implicit_layer.d"]
ALL_ARCH_DRIVER = (595,)   # README for 580 says "x86_64 Vulkan applications"; 595 says "Vulkan applications"

HELPER_PROCS = {"wineserver", "services.exe", "winedevice.exe", "plugplay.exe", "explorer.exe", "rpcss.exe",
                "svchost.exe", "steam.exe", "conhost.exe", "start.exe", "tabtip.exe", "pv-bwrap", "srt-bwrap",
                "reaper", "steam", "steamwebhelper", "python3", "python", "bash", "sh", "wine64-preloader",
                "pressure-vessel", "gamescopereaper", "mangoapp", "gamemoded", "winedbg"}


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    p = Path(base) / "nvcontrol" / "smoothmotion"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path(appid: str) -> Path:
    if not str(appid).isdigit():
        raise ValueError("appid must be numeric")
    return state_dir() / f"{appid}.log"


# ------------------------------------------------------------------------------ layer manifest
@dataclass
class LayerInfo:
    manifest: Path
    library: str
    lib32: bool = False


def find_layers(dirs: list[str] | None = None) -> list[LayerInfo]:
    found = []
    home_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "vulkan/implicit_layer.d"
    for d in (dirs or LAYER_DIRS + [str(home_dir)]):
        for f in sorted(Path(d).glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            layers = data.get("layers") or ([data["layer"]] if "layer" in data else [])
            for layer in layers:
                if layer.get("name") == LAYER_NAME:
                    lib = layer.get("library_path", "")
                    found.append(LayerInfo(f, lib, lib32="32" in f.name or "i386" in lib or "lib32" in lib))
    return found


# ------------------------------------------------------------------------------ preflight
@dataclass
class Check:
    name: str
    ok: bool | None          # None = informational / unknown
    detail: str


def preflight(gpu: GpuInfo | None, health: DriverHealth, vulkan_ok: bool, layers: list[LayerInfo] | None = None) \
        -> list[Check]:
    layers = find_layers() if layers is None else layers
    st, why = smooth_motion_status(gpu)
    checks = [Check("GPU and driver version", st == Status.PER_GAME, why),
              Check("NVIDIA driver running", health.ok, health.title if health.ok else
                    f"{health.title}. {health.fix[0] if health.fix else ''}")]
    if layers:
        checks.append(Check("Smooth Motion layer installed", True,
                            f"{LAYER_NAME} → {Path(layers[0].library).name or layers[0].manifest.name}"))
    else:
        checks.append(Check("Smooth Motion layer installed", False,
                            f"{LAYER_NAME} manifest not found in {', '.join(LAYER_DIRS)}. Your driver may be "
                            "older than 575, or nvidia-utils is incomplete."))
    checks.append(Check("Vulkan working", vulkan_ok, "Vulkan sees the NVIDIA GPU" if vulkan_ok else
                        "vulkaninfo can't find a GPU, so Vulkan games (and Smooth Motion) can't run. Usually "
                        "fixed by restarting after a driver update."))
    drv = parse_driver_version(gpu.driver_version if gpu else "")
    if drv and drv < ALL_ARCH_DRIVER:
        checks.append(Check("32-bit games", None, "Driver < 595 supports Smooth Motion only for 64-bit "
                                                  "(x86_64) games."))
    return checks


# ------------------------------------------------------------------------------ live processes
@dataclass
class RunningGame:
    pid: int
    name: str
    appid: str | None
    env_on: bool
    layer_loaded: bool | None       # None = can't tell from memory maps
    vulkan: bool
    wined3d: bool
    dxvk: bool
    is32: bool
    log_file: str | None = None
    verdict: str = ""
    active: bool = False
    reasons: list[str] = field(default_factory=list)


def _read_env(pid: str) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, _, v = item.partition(b"=")
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


def _elf32(pid: str) -> bool:
    try:
        with open(f"/proc/{pid}/exe", "rb") as f:
            hdr = f.read(5)
        return len(hdr) == 5 and hdr[4] == 1
    except OSError:
        return False


def judge(g: RunningGame, driver: tuple[int, ...]) -> RunningGame:
    if g.layer_loaded is None and g.env_on and g.vulkan and not (g.wined3d and not g.dxvk):
        g.active = True
        g.verdict = "Smooth Motion is very likely ACTIVE (enabled, game renders with Vulkan)"
        g.reasons.append("Turn on the verification log in Game Profiles to confirm 100 %.")
        return g
    if g.layer_loaded:
        g.active = True
        g.verdict = "Smooth Motion is ACTIVE (NVIDIA present layer loaded in the game)"
        if g.wined3d:
            g.reasons.append("WineD3D is also loaded; make sure the game renders through DXVK/VKD3D.")
        return g
    if not g.env_on:
        g.verdict = "Smooth Motion is NOT enabled for this game"
        g.reasons += ["The game started without NVPRESENT_ENABLE_SMOOTH_MOTION=1.",
                      "Enable it in Game Profiles, then Write to Steam with Steam fully closed, and relaunch the game."]
        return g
    g.verdict = "Smooth Motion was requested but is NOT running"
    if g.wined3d and not g.dxvk:
        g.reasons.append("The game renders through WineD3D (OpenGL). Smooth Motion needs the Vulkan path, which is what "
                         "DXVK/VKD3D give DX11/DX12 games under Proton: remove "
                         "PROTON_USE_WINED3D and use DXVK/VKD3D.")
    elif not g.vulkan:
        g.reasons.append("The game isn't using Vulkan (native OpenGL game, or it hasn't started rendering yet). "
                         "Smooth Motion needs Vulkan. DX11/DX12 games under Proton qualify (DXVK/VKD3D translate them to Vulkan); "
                         "native OpenGL games don't.")
    if g.is32 and driver and driver < ALL_ARCH_DRIVER:
        g.reasons.append("This is a 32-bit game. Your driver only supports Smooth Motion for 64-bit games "
                         "(fixed in driver 595+).")
    if g.vulkan and not g.reasons:
        g.reasons.append("Vulkan is in use but the layer didn't load. Check that the driver isn't waiting for a "
                         "restart, and run once with VK_LOADER_DEBUG=layer to see why the loader skipped it.")
    return g


def scan(layer_libs: list[str] | None = None, driver_version: str = "") -> list[RunningGame]:
    """Find running Steam games (own user) and decide whether Smooth Motion is really active."""
    libs = {Path(x).name for x in (layer_libs if layer_libs is not None else
                                    [li.library for li in find_layers()]) if x}
    # If the layer lives inside a library every NVIDIA Vulkan app maps anyway (e.g. libGLX_nvidia),
    # its presence in /proc/maps proves nothing; then only the verification log can confirm it.
    shared = {lb for lb in libs if lb.startswith(("libGLX_nvidia", "libnvidia-glcore", "libnvidia-vulkan"))}
    libs = (libs - shared) | ({"libnvidia-present.so"} if not libs - shared else set())
    driver = parse_driver_version(driver_version)
    uid = os.getuid()
    best: dict[str, RunningGame] = {}
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return []
    for pid in pids:
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            name = Path(f"/proc/{pid}/comm").read_text().strip()
        except OSError:
            continue
        if name.lower() in HELPER_PROCS:
            continue
        env = _read_env(pid)
        appid = env.get("SteamAppId") or env.get("SteamGameId")
        env_on = env.get(ENV) == "1"
        if not (env_on or (appid and appid != "0")):
            continue
        try:
            maps = Path(f"/proc/{pid}/maps").read_text(errors="replace")
        except OSError:
            continue
        vulkan = "libvulkan.so" in maps
        layer_loaded: bool | None = any(lib.split(".so")[0] in maps for lib in libs) if libs else None
        lf = env.get("NVPRESENT_LOG_FILE")
        if lf and env_on:
            try:
                if Path(lf).stat().st_mtime >= os.stat(f"/proc/{pid}").st_ctime - 2:
                    layer_loaded = True          # the layer wrote its log after this process started
            except OSError:
                pass
        if shared and layer_loaded is False and not lf:
            layer_loaded = None
        g = RunningGame(int(pid), name, appid if appid and appid != "0" else None, env_on, layer_loaded, vulkan,
                        "wined3d" in maps, "/dxvk/" in maps or "vkd3d" in maps, _elf32(pid),
                        env.get("NVPRESENT_LOG_FILE"))
        if not (vulkan or layer_loaded or env_on):
            continue
        key = g.appid or f"pid{pid}"
        rank = (bool(g.layer_loaded), g.vulkan, g.env_on)
        cur = best.get(key)
        if cur is None or rank > (bool(cur.layer_loaded), cur.vulkan, cur.env_on):
            best[key] = g
    return [judge(g, driver) for g in best.values()]


def mock_scan() -> list[RunningGame]:
    g = RunningGame(4242, "Cyberpunk2077.exe", "1091500", True, True, True, False, True, False)
    return [judge(g, (580, 95, 5))]


# ------------------------------------------------------------------------------ verification log
@dataclass
class LogResult:
    exists: bool
    loaded: bool
    lines: int = 0
    highlights: list[str] = field(default_factory=list)
    modified: float | None = None


def read_log(path: Path) -> LogResult:
    if not path.exists():
        return LogResult(False, False)
    try:
        text = path.read_text(errors="replace")
        mtime = path.stat().st_mtime
    except OSError:
        return LogResult(False, False)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hl = [ln.strip()[:200] for ln in lines if re.search(r"error|fail|warn|disabl|unsupport|enabl|smooth", ln, re.I)]
    return LogResult(True, bool(lines), len(lines), hl[-8:], mtime)
