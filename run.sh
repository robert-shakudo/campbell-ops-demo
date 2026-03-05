#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Campbell & Company — Ops Co-Pilot ==="
echo "Working dir: $(pwd)"
echo "Python: $(python3 --version)"

echo "--- Installing Python dependencies ---"
pip install --no-cache-dir -r requirements.txt -q

echo "--- Starting Campbell Ops Co-Pilot on :8787 ---"
python3 main.py
