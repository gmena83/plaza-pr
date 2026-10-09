#!/usr/bin/env bash
# Nightly backup of the shopper SQLite DB to mt03 (La Bóveda) over Tailscale.
# Uses sqlite3 .backup (safe under WAL with concurrent readers/writers),
# keeps 14 days of snapshots on mt03.
set -euo pipefail

DB="$HOME/pr-shopper-pipeline/db/shopper.db"
SQLITE3="$HOME/pr-shopper-pipeline/.venv/bin/python"
STAMP="$(date +%Y%m%d)"
LOCAL_TMP="$(mktemp -d)"
REMOTE_HOST="gonzalo@100.86.238.102"
REMOTE_DIR="~/backups/plaza-pr"

trap 'rm -rf "$LOCAL_TMP"' EXIT

if [[ ! -f "$DB" ]]; then
  echo "backup_db: $DB not found" >&2
  exit 1
fi

"$SQLITE3" - "$DB" "$LOCAL_TMP/shopper-$STAMP.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY

ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE_HOST" "mkdir -p $REMOTE_DIR"
scp -o BatchMode=yes -o ConnectTimeout=15 -q \
  "$LOCAL_TMP/shopper-$STAMP.db" "$REMOTE_HOST:$REMOTE_DIR/"

# prune remote snapshots older than 14 days
ssh -o BatchMode=yes "$REMOTE_HOST" \
  "find $REMOTE_DIR -name 'shopper-*.db' -mtime +14 -delete"

echo "backup_db: shopper-$STAMP.db -> $REMOTE_HOST:$REMOTE_DIR OK"
