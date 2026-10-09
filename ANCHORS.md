# Anchor Files — the load-bearing pieces

Read these first to understand or modify the system.

## Entry points
- `run_weekly.py` — orchestrator. Weekly scrape of all enabled chains.
  Hardened (flock, stale sweep, per-chain isolation). The systemd timer calls
  `refresh.sh` which calls this, then `notify_lists.py` (user digests).
- `notify_lists.py` — post-scrape Resend digest: basket verdict + deals per user.
- `backfill.py` — one-time historical backfill from the CDN (see BACKFILL.md).
- `api/main.py` — FastAPI app: public JSON endpoints, user list CRUD
  (Supabase bearer auth), B2B analytics. Hosted on Fly (plaza-pr-api).
- `seed_b2b_demo.py` — synthetic events seeder for the /negocios demo.
- `migrate_pg.py` — one-time SQLite -> Postgres migration (idempotent).

## Config
- `config/chains.yaml` — per-chain source type, URLs, VL settings. To add a
  chain: add an entry here (+ a `*_fetch.py` if it's a new interaction type).

## Source scrapers (scrapers/)
- `structured.py` — Pueblo/Amigo/Ralph's. The shared-platform grid parser.
- `econo_fetch.py` — REFERENCE browser_interactive scraper. Copy this pattern
  for any new store-gated/JS chain (Walmart PR, Mr. Special, etc.).
- `extract_vl.py` — the VL extraction core (page image -> Qwen3-VL -> JSON).
  `_rows_to_offers` validates rows; `_maybe_downscale` fits images to context.
- `validity.py` — per-source validity-date detection. Critical: wrong dates
  corrupt history.
- `cdn_fetch.py` — historical images from the aggregator CDN.

## Normalization & analysis (normalize/)
- `units.py` — size parsing + unit_price. The honest-comparison engine.
- `db.py` — storage layer. SQLite locally; Postgres when DATABASE_URL is set
  (pooler DSN). Backend switch is here — nowhere else.
- `pg_compat.py` — sqlite-like wrapper over psycopg2 (placeholder translation,
  lastrowid emulation, dict rows). Touch carefully; learnings 24-25.
- `cycle.py` — price-cycle/trend detection + buy recommendation verdicts.
- `basket.py` — per-chain basket totals + cheapest-basket verdict for lists.
- `canonicalize.py` — conservative VL-typo fixes. Keep the map SHORT.
- `schema.sql` / `schema_pg.sql` — SQLite / Postgres schemas + views.

## Serving / deploy
- `api/static/dashboard.html` — consumer frontend (open dashboard + Mi Lista
  behind magic-link). The colleague reskins THIS.
- `api/static/negocios.html` — B2B demo dashboard (synthetic events).
- `serve_vl.sh` — launches Qwen3-VL via vLLM on :8100 (AWQ, tuned for 16 GB).
- `refresh.sh` — weekly wrapper: ensures VL up, runs scrape, sends digests.
- `fly.toml` + `Dockerfile` + `requirements-api.txt` — hosted API on Fly
  (dfw). Slim deps only — the full requirements.txt makes an undeployable
  3.6 GB image.
- `deploy/*.service|*.timer` — systemd user units (scrape timer + backup
  timer). The local API service is DISABLED (Fly serves the API).
- `deploy/netlify/` — static site deploy (landing index.html, app/, negocios).
- `.env.supabase` (gitignored, chmod 600) — DB password, Resend key, service key.
  Also mirrored into the pr-shopper-scrape systemd drop-in and Fly secrets.

## Docs
- `docs/ARCHITECTURE.md` — full design + data-flow diagram.
- `docs/API.md` — every endpoint with shapes.
- `docs/LEARNINGS.md` — 20 operational lessons. Read before changing scrapers.
- `BACKFILL.md` — historical-data strategy + CDN availability map.
