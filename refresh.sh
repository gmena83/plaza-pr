#!/usr/bin/env bash
# Weekly shopper refresh. Run Thursday + Sunday mornings via cron/systemd timer.
set -e
cd "$(dirname "$0")"
LOG=data/run_$(date +%Y%m%d_%H%M%S).log
{
  echo "=== shopper run $(date) ==="
  # ensure VL server is up for PDF chains
  if ! curl -sf http://127.0.0.1:8100/v1/models >/dev/null 2>&1; then
    echo "starting VL server..."
    bash serve_vl.sh > data/vllm_server.log 2>&1 &
    # wait up to 5 min for readiness
    for i in $(seq 1 60); do
      sleep 5
      curl -sf http://127.0.0.1:8100/v1/models >/dev/null 2>&1 && break
    done
  fi
  .venv/bin/python -m run_weekly "$@"
  echo "=== done $(date) ==="
} >> "$LOG" 2>&1
tail -30 "$LOG"
