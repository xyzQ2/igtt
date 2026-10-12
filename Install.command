#!/bin/bash
# Double-click to install (safe to run again — it updates in place).
# Copies the analyzer to ~/Instagram Analyzer, installs Python and the libraries
# into it, and schedules the daily run at 8:00. macOS blocks background jobs from
# reading Downloads/Desktop/Documents, which is why it lives in the home folder.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/Instagram Analyzer"
LABEL="com.igtt.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "Installing the Instagram Analyzer into: $DEST"
mkdir -p "$DEST"
if [ "$SRC" != "$DEST" ]; then
  # Never overwrite settings, keys or history from an earlier install.
  rsync -a --exclude .env --exclude config.yaml --exclude data --exclude .venv \
        --exclude logs --exclude reports "$SRC/" "$DEST/"
  [ -f "$DEST/config.yaml" ] || cp "$SRC/config.yaml" "$DEST/config.yaml"
fi
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
cd "$DEST"
mkdir -p logs data reports
touch .env

# uv installs its own Python, so nothing needs to be on the Mac beforehand.
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
if [ ! -x "$UV" ]; then
  echo "Downloading the Python installer (uv)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
"$UV" venv --python 3.12 --allow-existing .venv
"$UV" pip install --python .venv/bin/python -q -r requirements.txt

# Load the starting list of accounts once, on first install.
if [ ! -f data/intelligence.db ] && [ -f seeds.txt ]; then
  .venv/bin/python seed_accounts.py
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$DEST/.venv/bin/python</string><string>$DEST/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$DEST/logs/run.log</string>
  <key>StandardErrorPath</key><string>$DEST/logs/run.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "✅ Installed. It will run every day at 8:00 (or when your Mac wakes up after 8:00)."
echo "Opening the folder — double-click 'Start.command' there to open your dashboard."
open "$DEST"
