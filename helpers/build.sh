#!/bin/sh
# Builds the small macOS helper apps into helpers/build/ (needs the Xcode command line tools: xcode-select --install).
#   HomeViewSpeech.app    on-device speech recognition for the voice service (asks for Speech Recognition once)
#   HomeViewCalendar.app  reads the Mac's Calendar for the dashboard (asks for Calendar access once)
#   HomeViewTouch.app     optional camera touch (asks for Camera access once)
#   personmask            optional: person cut-outs for the Photo face's depth effect
# Usage: helpers/build.sh            (all of them)
#        helpers/build.sh speech     (just one: speech, calendar, touch or personmask)
set -e
H="$(cd "$(dirname "$0")" && pwd)"
B="$H/build"
mkdir -p "$B"

app() {   # app <Name> <executable> <source.swift>
  dst="$B/HomeView$1.app/Contents"
  rm -rf "$B/HomeView$1.app"
  mkdir -p "$dst/MacOS"
  cp "$H/plist/HomeView$1.plist" "$dst/Info.plist"
  echo "Building HomeView$1.app"
  swiftc -O "$H/$3" -o "$dst/MacOS/$2"
  # Ad-hoc signature: macOS remembers the permission you grant for this build.
  codesign --force --sign - "$B/HomeView$1.app"
}

want() { [ -z "$1" ] || [ "$1" = "$2" ]; }

want "$1" speech && app Speech speechd speechd.swift
want "$1" calendar && app Calendar calendard calendard.swift
want "$1" touch && app Touch touchd touchd.swift
if want "$1" personmask; then
  echo "Building personmask"
  swiftc -O "$H/personmask.swift" -o "$B/personmask"
fi
echo "Done: $B"
