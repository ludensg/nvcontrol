#!/usr/bin/env bash
# Removes NV//CONTROL. Resets GPU tuning to driver defaults first.
#   ./uninstall.sh          keep your profiles/settings
#   ./uninstall.sh --purge  also delete ~/.config/nvcontrol, ~/.local/share/nvcontrol, logs and /etc/nvcontrol
set -uo pipefail
PURGE=0; [[ ${1:-} == --purge ]] && PURGE=1
run() { echo "   \$ $*"; "$@"; }

if [[ -x /usr/lib/nvcontrol/nvcontrol-helper ]]; then
  echo ":: Resetting GPU power/clocks/fans to driver defaults"
  run sudo /usr/lib/nvcontrol/nvcontrol-helper reset-all || true
  run sudo /usr/lib/nvcontrol/nvcontrol-helper clear-startup || true
fi
run sudo systemctl disable --now nvcontrol-apply.service nvcontrol-stable.timer 2>/dev/null || true
if pacman -Q nvcontrol >/dev/null 2>&1; then run sudo pacman -Rns nvcontrol; fi
rm -f "$HOME/.config/autostart/nvcontrol-vibrance.desktop"

if (( PURGE )); then
  echo ":: Purging user data (Steam backups in ~/.local/share/nvcontrol/backups are deleted too)"
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/nvcontrol" "${XDG_DATA_HOME:-$HOME/.local/share}/nvcontrol" \
         "${XDG_STATE_HOME:-$HOME/.local/state}/nvcontrol" "${XDG_CACHE_HOME:-$HOME/.cache}/nvcontrol"
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}"/MangoHud/nvcontrol-*.conf
  run sudo rm -rf /etc/nvcontrol /var/lib/nvcontrol /var/log/nvcontrol-helper.log
else
  echo ":: Kept your settings, profiles and backups. Use --purge to remove them."
fi
echo ":: Steam launch options written by NV//CONTROL stay in Steam. Remove them per game in Steam if wanted."
