#!/usr/bin/env bash
set -e

echo "=== Update packages ==="
apt-get update || true
apt-get install -y ffmpeg libzbar0 || true

echo "=== Upgrade pip ==="
python -m pip install --upgrade pip setuptools wheel

echo "=== Install requirements ==="
python -m pip install --no-cache-dir -r requirements.txt

echo "=== Build complete ==="