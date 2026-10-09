-- PLAZA Postgres schema (Supabase). Mirrors normalize/schema.sql (SQLite).
-- Run with the service-role connection, then grants/RLS from migrate_pg.py.

CREATE TABLE IF NOT EXISTS chains (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chain_slug   TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',   -- running|ok|error|stale
    offers_found INTEGER DEFAULT 0,
    source       TEXT,
    valid_from   DATE,
    valid_to     DATE,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         BIGINT NOT NULL REFERENCES scrape_runs(id),
    chain_slug     TEXT NOT NULL,
    product_raw    TEXT NOT NULL,
    product_norm   TEXT,
    sku            TEXT,
    brand          TEXT,
    size_text      TEXT,
    price_sale     DOUBLE PRECISION,
    price_regular  DOUBLE PRECISION,
    unit_price     DOUBLE PRECISION,
    unit_basis     TEXT,
    promo          TEXT,
    size_canonical TEXT,
    base_qty       DOUBLE PRECISION,
    base_unit      TEXT,
    price_basis    TEXT,
    category       TEXT,
    page           INTEGER,
    valid_from     DATE,
    valid_to       DATE,
    source_url     TEXT,
    scraped_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(chain_slug, product_norm, size_text, price_sale, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_offers_norm      ON offers(product_norm);
CREATE INDEX IF NOT EXISTS idx_offers_chain     ON offers(chain_slug);
CREATE INDEX IF NOT EXISTS idx_offers_valid     ON offers(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_offers_unitprice ON offers(product_norm, base_unit, unit_price);

CREATE TABLE IF NOT EXISTS products (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_norm  TEXT UNIQUE NOT NULL,
    display_name  TEXT,
    brand         TEXT,
    category      TEXT,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW v_best_prices AS
SELECT
    product_norm,
    MIN(price_sale) AS best_price,
    (SELECT o2.chain_slug FROM offers o2
      WHERE o2.product_norm = o.product_norm
        AND CURRENT_DATE BETWEEN o2.valid_from AND o2.valid_to
      ORDER BY o2.price_sale ASC LIMIT 1) AS best_chain,
    COUNT(DISTINCT chain_slug) AS chains_carrying
FROM offers o
WHERE CURRENT_DATE BETWEEN valid_from AND valid_to
  AND product_norm IS NOT NULL
GROUP BY product_norm;

CREATE OR REPLACE VIEW v_price_history AS
SELECT
    product_norm,
    chain_slug,
    valid_from           AS week_start,
    valid_to             AS week_end,
    MIN(price_sale)      AS price_sale,
    MAX(price_regular)   AS price_regular,
    COUNT(*)             AS observations
FROM offers
WHERE price_sale IS NOT NULL
GROUP BY product_norm, chain_slug, valid_from, valid_to;

CREATE OR REPLACE VIEW v_price_trend AS
SELECT
    h.product_norm,
    h.chain_slug,
    h.week_start,
    h.price_sale,
    LAG(h.price_sale) OVER (PARTITION BY h.product_norm, h.chain_slug
                            ORDER BY h.week_start) AS prev_price,
    ROUND( ((h.price_sale - LAG(h.price_sale) OVER (PARTITION BY h.product_norm, h.chain_slug
                            ORDER BY h.week_start))
           / NULLIF(LAG(h.price_sale) OVER (PARTITION BY h.product_norm, h.chain_slug
                            ORDER BY h.week_start), 0) * 100)::numeric, 1) AS pct_change
FROM v_price_history h;
