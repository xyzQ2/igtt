#!/bin/bash
# Double-click to open the dashboard and settings in your browser.
# Keep this window open while you use it; close it when you're done.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Not installed yet — double-click Install.command first."
  read -r -p "Press Enter to close."
  exit 1
fi
.venv/bin/python serve.py
