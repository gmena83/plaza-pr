#!/usr/bin/env bash
# Nightly logical backup of the production database (Supabase Postgres) to
# mt03 (La Bóveda) over Tailscale. Replaces the old SQLite snapshot: since the
# Postgres cut-over db/shopper.db is no longer written, and it never held the
# user tables.
#
# What goes in plaza-YYYYMMDD.tar.gz:
#   csv/<table>.csv     every table in `public` (prices, lists, email prefs/log, events)
#   csv/auth_users.csv  id, email, created_at, last_sign_in_at (to re-own lists)
#   schema_pg.sql + schema_users_pg.sql  (DDL to recreate the tables)
#   manifest.json       row counts, verified against the CSVs before upload
#
# Restore: deploy/restore_db.py ARCHIVE.tar.gz          (check: rolled-back test restore)
#          deploy/restore_db.py ARCHIVE.tar.gz --apply  (into a fresh database)
# It applies the DDL, loads tables in foreign-key order, and resets identity
# sequences. Users sign in again; auth_users.csv maps old ids to emails.
#
# Env: DATABASE_URL (systemd: EnvironmentFile=.env.supabase). 14-day retention.
set -euo pipefail
REPO="$HOME/pr-shopper-pipeline"
PY="$REPO/.venv/bin/python"
REMOTE_HOST="gonzalo@100.86.238.102"
REMOTE_DIR="~/backups/plaza-pr"
STAMP="$(date +%Y%m%d)"
NAME="plaza-$STAMP"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
: "${DATABASE_URL:?DATABASE_URL not set (load .env.supabase)}"

mkdir -p "$TMP/$NAME/csv"
"$PY" - "$TMP/$NAME" <<'PY'
import csv, json, os, sys, psycopg2
out = sys.argv[1]
conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.set_session(readonly=True, isolation_level="REPEATABLE READ")   # one consistent snapshot
cur = conn.cursor()
cur.execute("""SELECT relname FROM pg_class
               WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','p') ORDER BY 1""")
queries = {t: f'SELECT * FROM public."{t}"' for (t,) in cur.fetchall()}
queries["auth_users"] = "SELECT id, email, created_at, last_sign_in_at FROM auth.users"
manifest = {}
for name, q in queries.items():
    path = f"{out}/csv/{name}.csv"
    with open(path, "w") as f:
        cur.copy_expert(f"COPY ({q}) TO STDOUT WITH CSV HEADER", f)
    cur.execute(f"SELECT count(*) FROM ({q}) s")
    manifest[name] = cur.fetchone()[0]
    with open(path, newline="") as f:            # csv-aware: fields may span lines
        n = sum(1 for _ in csv.reader(f)) - 1
    if n != manifest[name]:
        sys.exit(f"backup_db: {name}: csv has {n} rows, table has {manifest[name]}")
conn.rollback()
json.dump({"tables": manifest}, open(f"{out}/manifest.json", "w"), indent=1)
print("backup_db: " + ", ".join(f"{k}={v}" for k, v in manifest.items()))
PY
cp "$REPO/normalize/schema_pg.sql" "$REPO/normalize/schema_users_pg.sql" "$TMP/$NAME/"
tar -czf "$TMP/$NAME.tar.gz" -C "$TMP" "$NAME"

ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE_HOST" "mkdir -p $REMOTE_DIR && chmod 700 $REMOTE_DIR"
scp -o BatchMode=yes -o ConnectTimeout=15 -q "$TMP/$NAME.tar.gz" "$REMOTE_HOST:$REMOTE_DIR/"
# contains user emails: owner-only; prune anything older than 14 days
ssh -o BatchMode=yes "$REMOTE_HOST" "chmod 600 $REMOTE_DIR/$NAME.tar.gz && \
  find $REMOTE_DIR \\( -name 'plaza-*.tar.gz' -o -name 'shopper-*.db' \\) -mtime +14 -delete"
echo "backup_db: $NAME.tar.gz ($(du -h "$TMP/$NAME.tar.gz" | cut -f1)) -> $REMOTE_HOST:$REMOTE_DIR OK"
