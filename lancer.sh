#!/usr/bin/env sh
# Lance le bot en simulation (Linux / macOS). Arrêt : Ctrl+C.
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
python3 -m bot run "$@"
