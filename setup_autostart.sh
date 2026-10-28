#!/bin/bash
# Makes unplugged.ai start by itself when you log in to your Mac, and start again if it ever stops.
# Works with no internet at all: it only needs the Mac itself (open http://127.0.0.1:8000).
#   ./setup_autostart.sh            install and start
#   ./setup_autostart.sh remove     stop and uninstall
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
LABEL="ai.unplugged.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "$1" = "remove" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed. unplugged.ai no longer starts by itself (./start.sh still works)."
  exit 0
fi

[ -x "$DIR/.venv/bin/python" ] || { echo "Missing $DIR/.venv. Do step 3 of the README first."; exit 1; }
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 && ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Something is already listening on port 8000 (probably ./start.sh in a terminal). Stop it first (Ctrl+C), then run this again."
  exit 1
fi
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>$DIR/.venv/bin/python</string><string>server.py</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PYTORCH_ENABLE_MPS_FALLBACK</key><string>1</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$DIR/logs/server.out</string>
  <key>StandardErrorPath</key><string>$DIR/logs/server.out</string>
</dict></plist>
EOF
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed. unplugged.ai is starting now at http://127.0.0.1:8000 and will start at every login."
echo "Remove it any time with: ./setup_autostart.sh remove"
