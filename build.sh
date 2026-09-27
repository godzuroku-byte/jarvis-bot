#!/usr/bin/env bash
set -e

echo "=== Starting build ==="
echo "=== Upgrading pip ==="
python -m pip install --upgrade pip setuptools wheel

echo "=== Installing requirements ==="
python -m pip install --no-cache-dir -r requirements.txt

echo "=== Build complete ==="