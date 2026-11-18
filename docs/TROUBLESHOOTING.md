# Troubleshooting

## First: get the logs

| What | Where |
|---|---|
| App log (rotating, 5 × 2 MB) | `~/.local/state/nvcontrol/logs/nvcontrol.log` |
| Privileged helper (every root action) | `/var/log/nvcontrol-helper.log` |
| Installer | `~/.local/state/nvcontrol/logs/install.log` |
| Startup service | `journalctl -u nvcontrol-apply -b` |

The quickest way to report a problem: **SETTINGS ▸ COPY BUG REPORT**, then paste it.
From a terminal: `nvcontrol --bug-report > report.md`. For more detail, start with
`nvcontrol --verbose` (debug logging, also printed to the terminal).

Crashes are caught. The traceback goes into the log and a dialog points you to it.

---

## "No NVIDIA GPU detected"
* `nvidia-smi` must work in a terminal. If it doesn't: `sudo chwd -a` (CachyOS) and reboot.
* `lsmod | grep nvidia` should list `nvidia`, `nvidia_modeset`, `nvidia_drm`.
* Telemetry source says *nvidia-smi* → install `python-nvidia-ml-py` for NVML (faster, needed for clock offsets).

## Tuning buttons are disabled / "Needs configuration"
* The privileged helper isn't installed. Run `./install.sh`, or check that `/usr/lib/nvcontrol/nvcontrol-helper` exists.
* `pkexec` missing → `sudo pacman -S polkit`. KDE ships a polkit agent; on other desktops make sure one is running.
* "Authentication cancelled" → you closed the password prompt.
* `NotSupported` from the helper → your GPU/VBIOS doesn't allow that setting (common: power limit on laptops).

## The system became unstable after tuning
1. Changes made with **APPLY / TEST** last until reboot only, so a reboot clears them.
2. If you saved a **startup profile** and the boot crashes, it's skipped automatically on the next boot (crash guard: a boot must stay up 3 minutes to count as stable).
3. Force-skip from the boot menu: add `nvcontrol.safe=1` to the kernel command line.
4. Remove it for good: `sudo /usr/lib/nvcontrol/nvcontrol-helper clear-startup`
5. Reset everything now: `sudo /usr/lib/nvcontrol/nvcontrol-helper reset-all`

## Power limit resets after a while
The driver forgets the limit when it unloads (no GPU clients). Enable persistence:
`sudo systemctl enable --now nvidia-persistenced`.

## Fan curve
Fan *curves* need a daemon. Install LACT (`sudo pacman -S lact`, then `sudo systemctl enable --now lactd`) and use **OPEN LACT · FAN CURVES**. If LACT status says *denied*, add your user's group to `admin_groups` in `/etc/lact/config.yaml` and restart `lactd`. Don't use NV//CONTROL's manual fan speed and a LACT fan curve at the same time.

## Digital Vibrance on Wayland
* Install nVibrant: `pipx install nvibrant`. It must match your driver version; update it after driver updates.
* Each monitor has its own slider. NV//CONTROL detects every GPU port, shows the connected ones, and guesses the KDE name (e.g. Port 2 · DP → DP-2). Press **IDENTIFY** to turn that monitor grey for 2 s if you're unsure which is which.
* The ALL slider sets every monitor at once. *Re-apply at login* stores each monitor's value.

## Brightness is low / stuck after sleep or hibernate
NV//CONTROL detects resume and, about 4 s later, puts each monitor's compositor brightness back to the value
you set (or the value it had before sleeping) and re-applies per-monitor vibrance, which the driver resets to 0.
Turn this off with *Restore brightness & vibrance after sleep / hibernate* on the Display page.
The brightness slider now applies as soon as you release it, and always sends the value, even if the app's
cached reading was stale. If it's still stuck: `kscreen-doctor -o` shows what KWin thinks, and the log shows a
`resume:` line for every value restored. Also check that KDE's own power settings (*Dim automatically*) aren't fighting it.

## Display change left me with a black screen
Wait 15 s. The previous mode comes back automatically unless you press KEEP.
Otherwise switch to a TTY (Ctrl+Alt+F3) and run `kscreen-doctor -o` and `kscreen-doctor output.DP-1.mode.<id>`.

## Steam launch options didn't stick
* Steam must be **fully closed** (Steam ▸ Exit). Steam rewrites `localconfig.vdf` when it exits. NV//CONTROL refuses to write while it runs.
* Every write first backs the file up to `~/.local/share/nvcontrol/backups/`. **ROLL BACK LAST WRITE** restores it.
* Several Steam accounts: the most recently used profile is edited.

## Smooth Motion option is greyed out
It needs RTX 50 + driver ≥ 575 or RTX 40 + driver ≥ 580.82.07, and only works on the Vulkan path (native Vulkan, DXVK, VKD3D-Proton). OpenGL games aren't covered.

## DLSS override doesn't seem to apply
Enable **Show DLSS indicator** in the profile to see which DLSS version/preset is active. Old games may need **Fetch newer DLSS via NGX updater**. Some titles block DLL updates. Native Linux games aren't affected by Proton variables.

## MangoHud shows nothing
Use the `mangohud` wrapper (the profile does this), or `--mangoapp` inside Gamescope (also automatic). 32-bit games need `lib32-mangohud`.

## Global Graphics settings don't take effect
* They load at **login**: log out and back in, then start Steam again. Check with `env | grep -E "__GL|DXVK|NVPRESENT"` in a new terminal.
* A game's own launch options (Game Profiles) win over global values.
* Files: `~/.config/environment.d/90-nvcontrol.conf` and `~/.config/nvcontrol/dxvk.conf`. Delete them (or press RESTORE DEFAULTS) to undo. Backups are in `~/.local/share/nvcontrol/backups/`.
* Direct3D rows (V-Sync, frame cap, anisotropy, triple buffering) only reach games running through DXVK (Proton/Wine D3D9–11). OpenGL rows only reach OpenGL games.

## Fan curve (GPU LAB)
* Status: `systemctl status nvcontrol-fancurve`. Log: `journalctl -u nvcontrol-fancurve -b`.
* Stop it immediately: `sudo systemctl disable --now nvcontrol-fancurve`. The fans return to the card's automatic curve.
* Don't run it together with a LACT fan curve.

## Updates
* "Source folder not found": the app finds the git clone through `~/.config/nvcontrol/source_dir`, which install.sh writes. Run `bash install.sh` once from the clone, or clone to `~/nvcontrol`.
* "Could not reach GitHub": offline, or the repo is private and git isn't logged in (`gh auth login`).
* "Could not fast-forward": run `cd ~/nvcontrol && git reset --hard @{u} && bash update.sh`.
* Nothing happens on UPDATE NOW: no supported terminal was found. Run `bash ~/nvcontrol/update.sh` yourself.
* Log: `~/.local/state/nvcontrol/logs/update.log`

## Running from source / without installing
```
python -m nvcontrol --mock      # simulated GPU, isolated config
python -m nvcontrol             # real hardware (helper needs install.sh for tuning)
QT_QPA_PLATFORM=offscreen python -m pytest -q
```
