PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS chains (
    id          INTEGER PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id           INTEGER PRIMARY KEY,
    chain_slug   TEXT NOT NULL,
    started_at   TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'running',   -- running|ok|error
    offers_found INTEGER DEFAULT 0,
    source       TEXT,                               -- pdf path or endpoint
    valid_from   TEXT,
    valid_to     TEXT,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES scrape_runs(id),
    chain_slug     TEXT NOT NULL,
    product_raw    TEXT NOT NULL,            -- as printed in the shopper
    product_norm   TEXT,                     -- normalized name for matching
    sku            TEXT,                     -- retailer SKU (structured chains) or generated key
    brand          TEXT,
    size_text      TEXT,                     -- "12 oz", "1 lb", "caja 24 un"
    price_sale     REAL,
    price_regular  REAL,
    unit_price     REAL,                     -- computed price per base unit when derivable
    unit_basis     TEXT,                     -- "lb","oz","un","l"
    promo          TEXT,                     -- "2x1", "2/$5", "limite 4", etc.
    size_canonical TEXT,                     -- normalized size e.g. "15.5oz", "12x10oz"
    base_qty       REAL,                     -- total content in base_unit (g/ml/un)
    base_unit      TEXT,                     -- 'g' | 'ml' | 'un'
    price_basis    TEXT,                     -- '$/lb' | '$/100ml' | '$/un'
    category       TEXT,
    page           INTEGER,
    valid_from     TEXT,
    valid_to       TEXT,
    source_url     TEXT,
    scraped_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chain_slug, product_norm, size_text, price_sale, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_offers_norm    ON offers(product_norm);
CREATE INDEX IF NOT EXISTS idx_offers_chain   ON offers(chain_slug);
CREATE INDEX IF NOT EXISTS idx_offers_valid   ON offers(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_offers_unitprice ON offers(product_norm, base_unit, unit_price);

-- Current best price view across chains (only offers valid "today").
CREATE VIEW IF NOT EXISTS v_best_prices AS
SELECT
    product_norm,
    MIN(price_sale)          AS best_price,
    (SELECT chain_slug FROM offers o2
      WHERE o2.product_norm = o.product_norm
        AND date('now') BETWEEN date(o2.valid_from) AND date(o2.valid_to)
      ORDER BY price_sale ASC LIMIT 1) AS best_chain,
    COUNT(DISTINCT chain_slug) AS chains_carrying
FROM offers o
WHERE date('now') BETWEEN date(valid_from) AND date(valid_to)
  AND product_norm IS NOT NULL
GROUP BY product_norm;

-- Products dimension: one row per normalized product name across all chains.
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY,
    product_norm  TEXT UNIQUE NOT NULL,
    display_name  TEXT,
    brand         TEXT,
    category      TEXT,
    first_seen    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Price history: every distinct (product, chain, week) price point ever seen.
-- offers rows are never deleted, so this is a convenience view over them that
-- collapses re-scrapes of the same week into a single observation.
CREATE VIEW IF NOT EXISTS v_price_history AS
SELECT
    product_norm,
    chain_slug,
    valid_from                    AS week_start,
    valid_to                      AS week_end,
    MIN(price_sale)               AS price_sale,      -- best (lowest) that week
    MAX(price_regular)            AS price_regular,
    COUNT(*)                      AS observations
FROM offers
WHERE price_sale IS NOT NULL
GROUP BY product_norm, chain_slug, valid_from;

-- Week-over-week price movement per product+chain.
CREATE VIEW IF NOT EXISTS v_price_trend AS
SELECT
    h.product_norm,
    h.chain_slug,
    h.week_start,
    h.price_sale,
    LAG(h.price_sale) OVER (PARTITION BY h.product_norm, h.chain_slug
                            ORDER BY h.week_start) AS prev_price,
    ROUND( (h.price_sale - LAG(h.price_sale) OVER (PARTITION BY h.product_norm, h.chain_slug
                            ORDER BY h.week_start))
           / NULLIF(LAG(h.price_sale) OVER (PARTITION BY h.product_norm, h.chain_slug
                            ORDER BY h.week_start), 0) * 100, 1) AS pct_change
FROM v_price_history h;
