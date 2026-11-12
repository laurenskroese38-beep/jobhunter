#!/usr/bin/env bash
# Lancement planifié (macOS / Linux). Voir README pour l'installer dans cron.
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate 2>/dev/null
mkdir -p logs
python run.py --jitter 45 >> logs/cron.log 2>&1
