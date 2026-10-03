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
with_widget=false
for arg in "$@"; do
  case "$arg" in
    --with-watcher) with_watcher=true ;;
    --with-widget) with_widget=true ;;
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
install -m 755 "$repo/bin/omarchy-screensaver-cadence" "$repo/bin/omarchy-launch-screensaver-cadence" "$bin/"
install -m 644 \
  "$repo/helpers/ai-slides.jsonc" \
  "$repo/helpers/bauhaus-svg.py" \
  "$repo/helpers/cadence-config.py" \
  "$repo/helpers/cadence-ctl.py" \
  "$repo/helpers/herdr-slide.py" \
  "$repo/helpers/notify-slide.py" \
  "$repo/helpers/notify-watch.py" \
  "$repo/helpers/stats-slide.py" \
  "$repo/helpers/wordfont.py" \
  "$config/"
install -m 755 "$repo/helpers/ai-slides.py" "$config/"
echo "installed: $bin/omarchy-screensaver-cadence, $bin/omarchy-launch-screensaver-cadence and helpers"

if [[ -f "$config/cadence.yaml" ]]; then
  echo "kept existing config: $config/cadence.yaml"
else
  install -m 644 "$repo/config/cadence.yaml" "$config/cadence.yaml"
  echo "installed config: $config/cadence.yaml"
fi

# The line format remains an independent fallback when cadence.yaml cannot be
# resolved (for example, when PyYAML is unavailable), so install it on a fresh
# setup without replacing an existing user's list.
if [[ -f "$config/slides" ]]; then
  echo "kept existing fallback: $config/slides"
else
  install -m 644 "$repo/config/slides" "$config/slides"
  echo "installed fallback: $config/slides"
fi

if $with_widget; then
  # A bar widget is an Omarchy plugin, so it goes in the plugin directory and is
  # registered with the shell rather than just copied somewhere.
  plugin="$HOME/.config/omarchy/plugins/matthewh.cadence"
  mkdir -p "$plugin"
  install -m 644 "$repo/widget/manifest.json" "$repo/widget/BarWidget.qml" "$repo/widget/Panel.qml" "$plugin/"
  rm -f "$plugin/CadenceWidget.qml"
  if command -v omarchy-shell-config >/dev/null; then
    # Register through omarchy-shell-config rather than editing shell.json by hand:
    # it is the supported path and keeps the bar layout intact. The jq program is
    # the first argument; anything after it would be passed to jq as an argument.
    (
      source /usr/share/omarchy/bin/omarchy-shell-config
      commit '.bar.layout.right = (((.bar.layout.right // []) | map(select(.id != "matthewh.cadence"))) + [{"id":"matthewh.cadence"}]) | .plugins = ((((.plugins // []) | map(select(.id != "matthewh.cadence"))) + [{"id":"matthewh.cadence"}]))'
    ) >/dev/null 2>&1 && echo "registered matthewh.cadence in the bar" || {
      echo "install: could not update shell.json; add the widget manually" >&2
    }
  fi
  echo "installed bar widget: $plugin"
else
  echo "skipped the bar widget."
  echo "  enable it with: ./install.sh --with-widget"
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
  1. Review the primary config:   ~/.config/omarchy/screensaver/cadence.yaml
  2. Preview without fullscreen:  omarchy-screensaver-cadence --dump
  3. Start it:                    omarchy-launch-screensaver-cadence

Cadence is installed as its own command because /usr/share/omarchy/bin is first
in PATH, so a ~/.local/bin/omarchy-screensaver could never shadow Omarchy's own.
Omarchy's screensaver is untouched and still used for idle.
EOF
