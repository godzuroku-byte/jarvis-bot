#!/usr/bin/env bash
set -e
apt-get update
apt-get install -y ffmpeg libzbar0
pip install --upgrade pip
pip install -r requirements.txt