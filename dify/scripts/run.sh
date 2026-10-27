#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/bootstrap.py
docker compose up -d --build
docker compose exec -T ollama ollama pull qwen3:1.7b
for attempt in $(seq 1 90); do
  if docker compose exec -T museum python app.py; then break; fi
  if [[ "$attempt" == 90 ]]; then echo 'seekdb not ready' >&2; exit 1; fi
  sleep 2
done
echo 'Open http://localhost:18080/install, or run scripts/import_dify.py to initialize/import/publish automatically.'
