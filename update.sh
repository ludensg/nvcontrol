#!/usr/bin/env bash
# NV//CONTROL updater: pulls the latest version from GitHub and reinstalls it.
#   bash update.sh           update if there is something new
#   bash update.sh --force   reinstall even if already up to date
# Log: ~/.local/state/nvcontrol/logs/update.log
#
# Everything lives inside main() so bash reads the whole script before `git pull`
# replaces this file on disk.
main() {
  set -euo pipefail
  local HERE LOGDIR LOG FORCE=0
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [[ ${1:-} == --force ]] && FORCE=1
  LOGDIR="${XDG_STATE_HOME:-$HOME/.local/state}/nvcontrol/logs"
  mkdir -p "$LOGDIR"
  LOG="$LOGDIR/update.log"
  exec > >(tee -a "$LOG") 2>&1
  local G=$'\e[38;5;112m' Y=$'\e[33m' R=$'\e[31m' N=$'\e[0m'
  echo "=== NV//CONTROL update $(date -Is) ==="
  [[ $EUID -eq 0 ]] && { echo "${R}xx${N} Run as your normal user, not root."; return 1; }
  cd "$HERE"
  [[ -d .git ]] || { echo "${R}xx${N} $HERE is not a git clone. Re-clone it from GitHub."; return 1; }

  local before
  before="$(git rev-parse --short HEAD)"
  echo "${G}::${N} Current version: $(grep -oP '__version__ = "\K[^"]+' nvcontrol/__init__.py) ($before)"
  echo "${G}::${N} Checking GitHub…"
  if ! git fetch --quiet origin; then
    echo "${R}xx${N} Could not reach GitHub (offline, or the repo is private and you're not logged in)."
    return 1
  fi
  local behind
  behind="$(git rev-list --count HEAD..@{u})"
  if [[ $behind == 0 && $FORCE == 0 ]]; then
    echo "${G}::${N} Already up to date."
    return 0
  fi
  if [[ $behind != 0 ]]; then
    echo "${G}::${N} $behind new change(s):"
    git --no-pager log --oneline --no-decorate HEAD..@{u} | sed 's/^/     /'
  fi

  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "${Y}!!${N} Local edits found; saving them with git stash so the update can proceed."
    git stash push -m "nvcontrol-update $(date -Is)"
  fi
  if ! git pull --ff-only --quiet; then
    echo "${R}xx${N} Could not fast-forward. To discard local history and match GitHub exactly:"
    echo "     cd $HERE && git reset --hard @{u} && bash update.sh"
    return 1
  fi
  echo "${G}::${N} Updated $before → $(git rev-parse --short HEAD). Reinstalling…"
  bash "$HERE/install.sh" --update
  echo
  echo "${G}::${N} Done. Close and reopen NV//CONTROL. Update log: $LOG"
}
main "$@"
exit $?
