#!/bin/sh
# Installs HomeView's three services as LaunchAgents, so they start at login and restart if they crash:
#   local.homeview.server  the dashboard (renders the screens)        logs: ~/Library/Logs/HomeView/server.log
#   local.homeview.relay   what the iMac connects to                  logs: ~/Library/Logs/HomeView/relay.log
#   local.homeview.voice   the voice assistant                        logs: ~/Library/Logs/HomeView/voice.log
#
# launchd can't read ~/Documents or ~/Desktop, so this copies the project to ~/Library/Application Support/HomeView/app
# and runs it from there. Run it again after you change config.json or update the code.
#
# Usage:  launchd/install.sh                 (all three)
#         launchd/install.sh server relay    (just these)
#         PYTHON=/path/to/python3 launchd/install.sh
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/HomeView/app"
LOGS="$HOME/Library/Logs/HomeView"
PY="${PYTHON:-/usr/bin/python3}"
SERVICES="${*:-server relay voice}"

[ -f "$SRC/config.json" ] || { echo "No config.json yet. Run: cp config.example.json config.json  (then edit it)" >&2; exit 1; }
"$PY" -c 'import PIL' 2>/dev/null || { echo "$PY can't import Pillow. Run: $PY -m pip install --user pillow numpy" >&2; exit 1; }

mkdir -p "$APP" "$LOGS" "$HOME/Library/LaunchAgents"
chmod 700 "$HOME/Library/Application Support/HomeView"
for s in $SERVICES; do launchctl bootout "gui/$(id -u)/local.homeview.$s" 2>/dev/null || true; done

# Copy the runtime files (not git history, caches or rendered output).
rsync -a --delete --exclude '.git' --exclude 'out' --exclude '.chrome-*' --exclude '__pycache__' --exclude 'voice/out' "$SRC/" "$APP/"
chmod 600 "$APP/config.json"

for s in $SERVICES; do
  t="$SRC/launchd/local.homeview.$s.plist.template"
  [ -f "$t" ] || { echo "Unknown service: $s" >&2; exit 1; }
  sed -e "s|__APP_DIR__|$APP|g" -e "s|__LOG_DIR__|$LOGS|g" -e "s|__PYTHON__|$PY|g" "$t" > "$HOME/Library/LaunchAgents/local.homeview.$s.plist"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.homeview.$s.plist"
done

sleep 3
for s in $SERVICES; do
  if launchctl print "gui/$(id -u)/local.homeview.$s" | grep -q 'state = running'; then
    echo "local.homeview.$s is running"
  else
    echo "local.homeview.$s did not start; see $LOGS/$s.log" >&2
  fi
done
