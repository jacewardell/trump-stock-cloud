#!/bin/bash
# One-command setup for running the daily + poll jobs on a Mac via launchd.
# Creates the venv, installs deps, caches the company list, generates the
# launchd agents (daily at 4:15pm ET in this machine's local time, poll every
# 2 minutes), and loads them.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
LABEL="com.trumpstockcloud.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
POLL_LABEL="com.trumpstockcloud.poll"
POLL_PLIST="$HOME/Library/LaunchAgents/$POLL_LABEL.plist"

echo "==> Python venv + dependencies"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

echo "==> Caching S&P500 + Nasdaq100 company list"
./venv/bin/python src/companies.py

echo "==> Checking prerequisites"
command -v claude >/dev/null || {
  echo "!! Claude Code CLI ('claude') not found."
  echo "   Install it and run 'claude' once to log in (uses your subscription),"
  echo "   then re-run this script. Without it, days with candidates fall back to"
  echo "   cashtag-only counting."
}
git -C "$PROJECT_DIR" config user.email >/dev/null 2>&1 || \
  echo "!! git identity not set globally; the runner falls back to a placeholder."
git -C "$PROJECT_DIR" remote get-url origin >/dev/null 2>&1 || \
  echo "!! no 'origin' remote; the daily push will fail until you add one with write access."

echo "==> Computing local time for 4:15pm ET"
read -r HH MM < <(./venv/bin/python -c "from datetime import datetime; from zoneinfo import ZoneInfo; et=datetime.now(ZoneInfo('America/New_York')).replace(hour=16,minute=15,second=0,microsecond=0); l=et.astimezone(); print(l.hour, l.minute)")
echo "   4:15pm ET = ${HH}:$(printf '%02d' "$MM") local"

echo "==> Writing launchd agent: $PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/run_daily_local.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>$HH</integer>
        <key>Minute</key><integer>$MM</integer>
    </dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/run.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/run.log</string>
    <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF

echo "==> Writing launchd agent: $POLL_PLIST"
cat > "$POLL_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$POLL_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/run_poll_local.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>120</integer>
    <key>StandardOutPath</key><string>$PROJECT_DIR/poll.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/poll.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

echo "==> Removing legacy agents (old labels)"
for old in com.jacewardell.trump-stock-cloud com.jacewardell.trump-stock-poll; do
  old_plist="$HOME/Library/LaunchAgents/$old.plist"
  [ -f "$old_plist" ] || continue
  launchctl bootout "gui/$(id -u)" "$old_plist" 2>/dev/null || true
  rm "$old_plist"
  echo "   removed $old"
done

echo "==> Loading the agents"
for p in "$PLIST" "$POLL_PLIST"; do
  launchctl bootout "gui/$(id -u)" "$p" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$p"
done

echo
echo "Done. Daily job runs at ${HH}:$(printf '%02d' "$MM") local (4:15pm ET); poll runs every 2 min."
echo "  Run now:    bash $PROJECT_DIR/run_daily_local.sh"
echo "  Logs:       $PROJECT_DIR/run.log, $PROJECT_DIR/poll.log"
echo "  Uninstall:  launchctl bootout gui/\$(id -u) <plist> && rm <plist>  (daily + poll)"
echo "Note: if your timezone does not observe US daylight saving (e.g. Arizona),"
echo "re-run this script at the next DST change to keep it aligned to 4:15pm ET."
