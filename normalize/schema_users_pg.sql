-- PLAZA user-side tables (Supabase Postgres). Applied by hand / Management API,
-- NOT by db.init_db (which only manages the price tables in schema_pg.sql).
-- Idempotent: safe to re-run on an existing project.
--
-- The project previously hosted conGenAI; its 23 tables, 3 functions and the
-- auth.users trigger on_auth_user_created were dropped on 2026-10-09
-- (backup: ~/backups/congenai-20261009.tar.gz, copy on mt03 ~/backups/congenai/).
-- `public` now holds only PLAZA objects.
--
-- Access model: the browser only ever talks to the Fly API (and to Supabase Auth
-- for magic links). The API and the scraper connect as `postgres` through the
-- pooler, which owns these tables and bypasses RLS. The public (anon) key that
-- ships in the frontend must never be able to write anything.

-- ── shopping lists ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lists (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     UUID NOT NULL,                       -- auth.users.id
    name        TEXT NOT NULL DEFAULT 'Mi lista',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS list_items (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    list_id         BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    product_norm    TEXT NOT NULL,
    size_canonical  TEXT,                            -- '' = no specific size
    any_size        BOOLEAN NOT NULL DEFAULT false,  -- "cualquier tamaño"
    display_name    TEXT,
    target_price    DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (list_id, product_norm, size_canonical)
);
CREATE INDEX IF NOT EXISTS idx_list_items_list ON list_items(list_id);
CREATE INDEX IF NOT EXISTS idx_list_items_norm ON list_items(product_norm);

ALTER TABLE lists      ENABLE ROW LEVEL SECURITY;
ALTER TABLE list_items ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'lists_owner') THEN
    CREATE POLICY lists_owner ON lists USING (auth.uid() = user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'list_items_owner') THEN
    CREATE POLICY list_items_owner ON list_items USING (EXISTS (
      SELECT 1 FROM lists WHERE lists.id = list_items.list_id AND lists.user_id = auth.uid()));
  END IF;
END $$;

-- ── Mi Lista email digest ───────────────────────────────────────────────────
-- One row per user, created (opt-in) the first time they have list items.
CREATE TABLE IF NOT EXISTS email_prefs (
    user_id          UUID PRIMARY KEY,
    enabled          BOOLEAN NOT NULL DEFAULT true,
    unsub_token      TEXT NOT NULL UNIQUE
                     DEFAULT replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-',''),
    unsubscribed_at  TIMESTAMPTZ,
    reason           TEXT,                 -- link | one_click | toggle
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per user per digest slot (Mon/Thu date): the double-send guard.
CREATE TABLE IF NOT EXISTS email_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     UUID NOT NULL,
    kind        TEXT NOT NULL,             -- list_digest
    period      DATE NOT NULL,             -- slot date
    status      TEXT NOT NULL,             -- sent | skipped | failed
    resend_id   TEXT,
    subject     TEXT,
    n_items     INT,
    n_deals     INT,
    summary     JSONB,                     -- {item_id: [chain, price]} as sent
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, kind, period)
);
CREATE INDEX IF NOT EXISTS idx_email_log_user ON email_log(user_id, created_at DESC);

ALTER TABLE email_prefs ENABLE ROW LEVEL SECURITY;   -- no policies: API-only
ALTER TABLE email_log   ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON email_prefs, email_log FROM anon, authenticated;

-- ── lock down the public key ────────────────────────────────────────────────
-- Supabase grants anon/authenticated full DML on every new public table by
-- default. Price data is public-read but must not be writable with the key
-- that ships in dashboard.html.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON chains, offers, products, scrape_runs, events FROM anon, authenticated;
-- lists: RLS already limits a logged-in user to their own rows; anon never writes.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON lists, list_items FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLES FROM anon, authenticated;
