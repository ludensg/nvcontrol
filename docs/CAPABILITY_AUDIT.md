# Phase 1 — Capability audit (NVIDIA on CachyOS, November 2026)

This is what NV//CONTROL assumes about the Linux driver stack, why, and how each
item is implemented. The app re-checks everything at runtime and shows the
result in **SYSTEM TOOLS ▸ Feature matrix** (also printed by `nvcontrol --diagnostics`).

Status vocabulary used in the UI:

| Status | Meaning |
|---|---|
| **Operational** | Works now, controlled from NV//CONTROL |
| **Needs configuration** | Supported, but a package/service/permission is missing (the UI says which) |
| **Via external app** | Supported through a dedicated tool NV//CONTROL launches (e.g. LACT) |
| **Per-game** | Only exists per game (launch options or in-game menu) |
| **Unsupported here** | This GPU / driver / session can't do it |
| **Windows-only** | Not exposed by the Linux driver at all |

## GPU monitoring & tuning

| Feature | Linux status | Mechanism in NV//CONTROL | Notes |
|---|---|---|---|
| Telemetry (temp, load, clocks, VRAM, power, fan, P-state, clock limiters) | Supported | NVML (`python-nvidia-ml-py`, in Arch `extra`), fallback `nvidia-smi` | Works on Wayland and X11 |
| Power limit | Supported on most desktop GeForce | NVML `nvmlDeviceSetPowerManagementLimit` via root helper | Range comes from the driver. Laptops usually don't expose it (Dynamic Boost instead). Not kept across a driver unload, so `nvidia-persistenced` is recommended |
| Core / memory clock offset | Supported (recent drivers) | NVML `nvmlDeviceSetGpcClkVfOffset` / `SetMemClkVfOffset` via helper | No Coolbits / X11 needed. Memory offset is in NVML units (nvidia-settings shows 2×) |
| Clock locking | Volta and newer | NVML `nvmlDeviceSetGpuLockedClocks` | Used for the indirect undervolt recipe |
| Voltage / VF curve | No direct voltage API | Indirect: offset + lock; or LACT's NVIDIA VF tooling | Shown as "Via external app" |
| Manual fan speed | Desktop cards, driver ≥ 520 | NVML `nvmlDeviceSetFanSpeed_v2`, reset with `SetDefaultFanSpeed_v2` | Driver minimum is enforced |
| Fan curve | Needs a daemon | **LACT** (`lactd`) | NV//CONTROL only *reads* LACT's socket API and launches its GUI. It never edits `/etc/lact/config.yaml` |
| PowerMizer mode | X11 only | nvidia-settings | Not on Wayland |
| Persistence across reboots | — | root `nvcontrol-apply.service` + crash guard | See TROUBLESHOOTING |

## Display

| Feature | KDE Wayland | X11 |
|---|---|---|
| Resolution / refresh / scale / position | `kscreen-doctor` | `xrandr` (scale: no) |
| Adaptive Sync / G-SYNC Compatible | KWin VRR policy (never/automatic/always) | nvidia-settings |
| HDR | KWin (`hdr.enable`) | n/a |
| ICC profiles | KWin color management (Plasma ≥ 6.1) | colord / external |
| Brightness | **Compositor dimming** (`kscreen-doctor …brightness`): software, not the backlight | — |
| Monitor luminance / contrast | **DDC/CI** via `ddcutil` (real monitor control) | same |
| Digital Vibrance | **nVibrant** (talks to nvidia-modeset; not in official repos) | nvidia-settings `DigitalVibrance` |
| Gamma / contrast (driver) | Not available on Wayland | nvidia-settings color correction |
| Color temperature | KDE Night Light (external) | redshift etc. |
| DSR / DLDSR | **Windows-only** | **Windows-only** |

## RTX / gaming

| Feature | Who controls it on Linux | NV//CONTROL action |
|---|---|---|
| DLSS SR / DLAA / quality modes | The game | Explains where; per-game override below |
| DLSS preset / model override (SR, RR) | DXVK-NVAPI DRS env vars in Proton: `DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE=on`, `…_RENDER_PRESET_SELECTION=render_preset_k/latest/…` | Per-game profile |
| Newer DLSS snippets | `PROTON_ENABLE_NGX_UPDATER=1` (Valve Proton). GE-Proton / Proton-CachyOS also have `PROTON_DLSS_UPGRADE` | Per-game checkbox (Valve variable) |
| DLSS indicator | `DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS=DLSSIndicator=1024,DLSSGIndicator=2` | Per-game checkbox |
| DLSS Frame Generation | The game (RTX 40/50); FG override env available | Per-game override checkbox |
| DLSS Multi Frame Generation | The game (RTX 50) | Status only |
| **NVIDIA Smooth Motion** | Driver: `NVPRESENT_ENABLE_SMOOTH_MOTION=1`. RTX 50 since 575, RTX 40 since 580.82.07. Vulkan path (native, DXVK, VKD3D-Proton). NVIDIA: don't combine with DLSS FG | Per-game, **only offered when GPU + driver qualify**. Warns if combined with FG |
| Reflex | The game, through DXVK-NVAPI (`PROTON_ENABLE_NVAPI=1` where off by default) | Per-game NVAPI checkbox |
| Low Latency Mode (NULL), RTX HDR, RTX VSR, ShadowPlay, Freestyle, driver NIS, Ansel | **Windows-only** | Linux alternatives are listed (Gamescope NIS/FSR, vkBasalt, OBS/gpu-screen-recorder) |
| FPS limit | MangoHud `fps_limit` or Gamescope `--framerate-limit` | Global MangoHud config + per-game |
| Shader cache size | `__GL_SHADER_DISK_CACHE_SIZE` | Per-game |

## Assumptions

* Driver ≥ 570 (CachyOS ships current production/feature branches via `chwd`). Older drivers still work for telemetry; features gate themselves on version.
* KDE Plasma 6 on Wayland is the main target; X11 paths exist for vibrance, gamma and modes.
* Steam native package (`~/.local/share/Steam`); Flatpak Steam is detected for reading too.
* Tuning writes are limited to what the driver reports. NVML itself rejects out-of-range values, and the helper checks them before calling NVML too.

## Sources

* NVIDIA Linux driver README — Chapter 39 "NVIDIA Smooth Motion" (nvpresent.html)
* NVIDIA driver installation guide — "DLSS / Smooth Motion / Reflex" (docs.nvidia.com/datacenter/tesla/driver-installation-guide/gaming.html)
* dxvk-nvapi wiki — "Passing driver settings"
* LACT README and docs/API.md (github.com/ilya-zlobintsev/LACT)
* nVibrant (github.com/Tremeschin/nvibrant)
* Arch package `python-nvidia-ml-py` (extra)
* GE-Proton 10-26 / Proton-CachyOS release notes (PROTON_DLSS_UPGRADE, PROTON_DLSS_INDICATOR)
