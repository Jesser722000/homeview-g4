#!/bin/sh
# Stops HomeView's LaunchAgents and removes them. Your config.json and photos are left alone.
# Add --all to also delete the runtime copy (~/Library/Application Support/HomeView/app) and the logs.
for s in server relay voice; do
  launchctl bootout "gui/$(id -u)/local.homeview.$s" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/local.homeview.$s.plist"
done
pkill -f 'HomeViewSpeech.app/Contents/MacOS/speechd' 2>/dev/null || true
pkill -f 'HomeViewCalendar.app/Contents/MacOS/calendard' 2>/dev/null || true
pkill -f 'HomeViewTouch.app/Contents/MacOS/touchd' 2>/dev/null || true
if [ "$1" = "--all" ]; then
  rm -rf "$HOME/Library/Application Support/HomeView/app" "$HOME/Library/Logs/HomeView"
fi
echo "HomeView services removed."
