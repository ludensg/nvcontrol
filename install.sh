#!/usr/bin/env bash
# NV//CONTROL installer for CachyOS / Arch Linux.
# Builds a native pacman package from this folder (makepkg) and installs it.
# Every privileged step is printed before it runs. Output is logged to:
#   ~/.local/state/nvcontrol/logs/install.log
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# --update / --yes: non-interactive (used by update.sh); skips the optional questions
UPDATE=0
for arg in "$@"; do case "$arg" in --update|--yes|-y) UPDATE=1 ;; esac; done
LOGDIR="${XDG_STATE_HOME:-$HOME/.local/state}/nvcontrol/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/install.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== NV//CONTROL install $(date -Is) ==="

G=$'\e[38;5;112m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'
say()  { echo "${G}::${N} $*"; }
warn() { echo "${Y}!!${N} $*"; }
die()  { echo "${R}xx${N} $*"; echo "Full log: $LOG"; exit 1; }
run()  { echo "   \$ $*"; "$@"; }

[[ $EUID -eq 0 ]] && die "Run as your normal user (sudo is requested only where needed)."
command -v pacman >/dev/null || die "pacman not found — this installer targets CachyOS / Arch Linux."

if ! lspci 2>/dev/null | grep -qi 'nvidia'; then
  warn "No NVIDIA GPU visible in lspci. The app will still install (try: nvcontrol --mock)."
fi
if ! command -v nvidia-smi >/dev/null; then
  warn "nvidia-smi not found. On CachyOS install the driver with:  sudo chwd -a"
fi

say "Build tools needed for a native package:"
run sudo pacman -S --needed --noconfirm base-devel python-build python-installer python-setuptools \
    python-wheel python-pytest pyside6 python-nvidia-ml-py polkit

say "Building and installing the nvcontrol package (makepkg)…"
cd "$HERE"
run makepkg -sif --noconfirm

say "Enabling startup-tuning services (they do nothing until you save a startup profile):"
run sudo systemctl daemon-reload
run sudo systemctl enable nvcontrol-apply.service nvcontrol-stable.timer

# Remember where the source lives so the app's updater can find it
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/nvcontrol"
mkdir -p "$CFG"
echo "$HERE" > "$CFG/source_dir"
say "Updater source folder recorded: $HERE"

if (( UPDATE )); then
  say "Update installed. Restart NV//CONTROL to use the new version."
  say "Install log: $LOG"
  exit 0
fi

if systemctl list-unit-files nvidia-persistenced.service >/dev/null 2>&1; then
  if ! systemctl is-enabled --quiet nvidia-persistenced 2>/dev/null; then
    read -r -p "Enable nvidia-persistenced (keeps power limits applied while no app uses the GPU)? [Y/n] " a
    if [[ ! $a =~ ^[Nn] ]]; then run sudo systemctl enable --now nvidia-persistenced; fi
  fi
fi

echo
read -r -p "Install recommended optional tools (lact mangohud lib32-mangohud goverlay gamescope vulkan-tools)? [y/N] " a
if [[ $a =~ ^[Yy] ]]; then
  run sudo pacman -S --needed lact mangohud lib32-mangohud goverlay gamescope vulkan-tools
  read -r -p "Enable the LACT daemon now? [Y/n] " b
  [[ $b =~ ^[Nn] ]] || run sudo systemctl enable --now lactd
fi

say "Done. Start ${G}NV//CONTROL${N} from the app menu or run:  nvcontrol"
say "Demo without touching hardware:  nvcontrol --mock"
say "Install log: $LOG"
