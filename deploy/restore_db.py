"""Restore a PLAZA backup archive (deploy/backup_db.sh) into Postgres.

  restore_db.py ARCHIVE.tar.gz            --check (default): restore into a
                                          throwaway schema inside a transaction,
                                          verify every row count, then ROLL BACK.
                                          Safe against production; run it to
                                          prove a backup is usable.
  restore_db.py ARCHIVE.tar.gz --apply    restore into `public` of the database
                                          in DATABASE_URL (a fresh project).
                                          Refuses if `offers` already has rows.

Order of operations: schema_pg.sql + schema_users_pg.sql (DDL), then tables
in foreign-key order (parents first), then identity sequences are moved past
max(id) so new inserts don't collide. auth.users is NOT restored (Supabase owns
it): users sign in again with the same email; csv/auth_users.csv maps old user
ids to emails for re-owning lists / email_prefs / email_log.

Env: DATABASE_URL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import psycopg2

LOCKDOWN_MARKER = "-- ── lock down the public key"


def fk_order(cur, schema: str, tables: list[str]) -> list[str]:
    """Topological order: a table comes after every table it references."""
    cur.execute("""SELECT c.relname, p.relname FROM pg_constraint k
                   JOIN pg_class c ON c.oid = k.conrelid JOIN pg_class p ON p.oid = k.confrelid
                   WHERE k.contype = 'f' AND k.connamespace = %s::regnamespace""", (schema,))
    parents: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in cur.fetchall():
        if child in parents and parent in parents and child != parent:
            parents[child].add(parent)
    order: list[str] = []
    while parents:
        ready = sorted(t for t, ps in parents.items() if not ps - set(order))
        if not ready:
            raise SystemExit(f"FK cycle among {sorted(parents)}")
        for t in ready:
            order.append(t)
            del parents[t]
    return order


def restore(conn, d: Path, schema: str, check: bool) -> bool:
    manifest = json.loads((d / "manifest.json").read_text())["tables"]
    cur = conn.cursor()
    if check:
        cur.execute(f"CREATE SCHEMA {schema}")
        cur.execute(f"SET LOCAL search_path = {schema}, public")
    cur.execute((d / "schema_pg.sql").read_text())
    users_sql = (d / "schema_users_pg.sql").read_text()
    # the lockdown REVOKEs name live public tables; skip them in a check run
    cur.execute(users_sql.split(LOCKDOWN_MARKER)[0] if check else users_sql)

    tables = [t for t in manifest if t != "auth_users"]
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = %s::regnamespace AND relkind = 'r'",
                (schema,))
    created = {r[0] for r in cur.fetchall()}
    missing = [t for t in tables if t not in created]
    if missing:
        print(f"FAIL: schema files don't create {missing}")
        return False
    if not check:
        cur.execute("SELECT count(*) FROM public.offers")
        if cur.fetchone()[0]:
            raise SystemExit("refusing --apply: public.offers already has rows (not a fresh database)")

    ok = True
    for t in fk_order(cur, schema, tables):
        with open(d / "csv" / f"{t}.csv") as f:
            cur.copy_expert(f'COPY {schema}."{t}" FROM STDIN WITH CSV HEADER', f)
        cur.execute(f'SELECT count(*) FROM {schema}."{t}"')
        got = cur.fetchone()[0]
        good = got == manifest[t]
        ok &= good
        print(f"  {t:12} {got:>6} / {manifest[t]:<6} {'ok' if good else 'MISMATCH'}")

    # identity columns: continue numbering after the restored ids
    cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                   WHERE table_schema = %s AND is_identity = 'YES'""", (schema,))
    for t, col in cur.fetchall():
        cur.execute(f"""SELECT setval(pg_get_serial_sequence('{schema}."{t}"', '{col}'),
                        GREATEST((SELECT max("{col}") FROM {schema}."{t}"), 1))""")
    if check:   # prove a fresh insert doesn't collide with restored ids
        cur.execute(f"INSERT INTO {schema}.lists (user_id) VALUES (gen_random_uuid()) RETURNING id")
        print(f"  new insert after restore got id {cur.fetchone()[0]} (no collision)")
        cur.execute(f"SELECT count(*) FROM {schema}.v_price_history")
        print(f"  views work on restored data: v_price_history = {cur.fetchone()[0]} rows")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--apply", action="store_true", help="restore into public (fresh database only)")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(a.archive) as tf:
            tf.extractall(tmp, filter="data")
        d = next(Path(tmp).iterdir())
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            ok = restore(conn, d, "public" if a.apply else "_restore_check", check=not a.apply)
            if a.apply and ok:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    verdict = "PASS" if ok else "FAIL"
    print(f"restore {'applied' if a.apply and ok else 'check'}: {verdict}"
          + ("" if a.apply else " (rolled back, nothing persisted)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
