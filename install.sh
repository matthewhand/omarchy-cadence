#!/bin/bash

# install.sh -- install cadence for the current user.
#
# Everything lands in user config only (~/.local/bin and ~/.config/omarchy), so
# nothing in /usr/share/omarchy is touched and no sudo is needed. Cadence is
# installed alongside Omarchy's own screensaver, not over it.

set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bin="$HOME/.local/bin"
config="$HOME/.config/omarchy/screensaver"
unit_dir="$HOME/.config/systemd/user"

with_watcher=false
for arg in "$@"; do
  case "$arg" in
    --with-watcher) with_watcher=true ;;
    -h | --help)
      sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "install: unknown option: $arg" >&2; exit 1 ;;
  esac
done

missing=0
for cmd in ttfx jq hyprctl; do
  command -v "$cmd" >/dev/null || { echo "install: required command not found: $cmd" >&2; missing=1; }
done
command -v omarchy-transcode-ascii >/dev/null || {
  echo "install: omarchy-transcode-ascii not found (needed for image slides)" >&2
  missing=1
}
((missing == 0)) || exit 1

mkdir -p "$bin" "$config" "$unit_dir"
install -m 755 "$repo/bin/omarchy-cadence" "$repo/bin/omarchy-launch-cadence" "$bin/"
install -m 644 "$repo/helpers/"*.py "$config/"
echo "installed: $bin/omarchy-cadence, $bin/omarchy-launch-cadence"

if [[ -f "$config/slides" ]]; then
  echo "kept existing slide list: $config/slides"
else
  install -m 644 "$repo/config/slides" "$config/slides"
  echo "installed slide list: $config/slides"
fi

if $with_watcher; then
  install -m 644 "$repo/systemd/cadence-notify-watch.service" "$unit_dir/"
  systemctl --user daemon-reload
  systemctl --user enable --now cadence-notify-watch.service
  echo "installed and started: cadence-notify-watch.service (desktop notifications)"
else
  echo "skipped the notification watcher."
  echo "  enable it with: ./install.sh --with-watcher"
fi

cat <<'EOF'

Next:
  1. Review the slide list:      ~/.config/omarchy/screensaver/slides
  2. Preview without fullscreen:  omarchy-cadence --dump
  3. Start it:                    omarchy-launch-cadence

Cadence is installed as its own command because /usr/share/omarchy/bin is first
in PATH, so a ~/.local/bin/omarchy-screensaver could never shadow Omarchy's own.
Omarchy's screensaver is untouched and still used for idle.
EOF
