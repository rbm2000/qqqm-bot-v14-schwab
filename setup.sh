#!/usr/bin/env bash
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env || true
cp -n config/config.yaml config/config.yaml.bak || true
echo "If you want a password: add DASHBOARD_PASSWORD=yourpass to .env"
python -m qqqm.bot
