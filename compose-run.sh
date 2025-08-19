#!/usr/bin/env bash
set -e
cp -n .env.example .env || true
docker compose up --build -d
echo "Open http://localhost:5005"
