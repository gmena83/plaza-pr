# PLAZA — Puerto Rico Supermarket Price Intelligence

Extracts weekly discount circulars ("shoppers") from Puerto Rico supermarket
chains, normalizes them into a queryable database, computes fair unit prices,
detects price cycles, and serves a live dashboard + API — plus user accounts
with shopping lists, basket optimization, and email alerts.

**Live app:** https://plaza-pr.netlify.app (landing) · /app (dashboard) · /negocios.html (B2B demo)
**API:** https://plaza-pr-api.fly.dev

## What it does

- **Ingests** shoppers from 11 PR chains via 5 source types: structured HTML
  endpoints, image-only PDFs, hosted page images, a Playwright store-gated web
  app, and a dated CDN archive for history.
- **Extracts** products + prices from image-based circulars with a **local
  vision-language model** (Qwen3-VL-8B AWQ on an RTX 5070 Ti, served by vLLM) —
  no cloud OCR, no per-page cost.
- **Normalizes** messy chain-specific size strings ("Pqte. de 12 Latas de 10
  oz", "95¢ LB.", "3 LIBRAS") into canonical sizes and comparable **unit
  prices** ($/lb, $/100ml, $/un).
- **Tracks history** week over week and **detects price cycles** (alternating
  weekly sales, rising/falling trends) to recommend **buy now / buy soon /
  wait / buy cheapest**.
- **User accounts** (Supabase Auth magic links): shopping lists, per-chain
  **basket optimization** ("compra tu lista en Econo esta semana"), and a
  post-scrape **email digest** (Resend) with the best offers on your list.
- **B2B demo dashboard** (/negocios): market-intelligence view for chains and
  brands — searches, engagement funnel, per-brand attention/conversion.
  Currently seeded with synthetic events; the queries are production queries.

## Production architecture

```
menatech01 (workstation)                    Supabase (Postgres + Auth)
  scrapers + VL extraction    --write-->     offers / products / lists / events
  run_weekly (systemd timer)                 auth.users (magic links)
  notify_lists.py (Resend)        ^
       |                          |  read
       v                          |
  nightly sqlite backup to mt03   |
                                  |
Fly.io (plaza-pr-api)  -----------+   Netlify (static frontend)
  FastAPI read API + list CRUD  <---  landing / dashboard / negocios
```

The site stays up when the workstation is down — data just stops refreshing,
and the dashboard freshness badge shows staleness.

## Current coverage

| Chain | Source type | Weekly offers |
|-------|-------------|---------------|
| Ralph's | structured | ~1000 |
| Pueblo | structured | ~920 |
| Amigo | structured | ~800 |
| Mr. Special | cdn (history) | ~460 |
| Econo | browser_interactive (Playwright) | ~380 |
| Selectos | pdf | ~255 |
| SuperMax | pdf | ~220 |
| Agranel | cdn (history) | ~180 |
| Freshmart | cdn (history) | ~140 |
| Mi Gente | images | ~135 |
| Walmart PR | cdn (history) | ~15 |

~5,000+ active offers/week; 8,000+ offers with history.

## Repo layout

```
api/main.py                 FastAPI: search/best/history/recommendation +
                            list CRUD (Supabase bearer) + B2B analytics
api/static/dashboard.html   consumer dashboard (open + Mi Lista behind login)
api/static/negocios.html    B2B demo dashboard (synthetic-data badge)
scrapers/
  common.py                 HTTP session, price/size parsers, config loader
  structured.py             Pueblo/Amigo/Ralph's paginated-grid scraper
  pdf_fetch.py              discover + download weekly PDFs (Selectos, SuperMax)
  image_fetch.py            Wix/hosted page-image fetcher (Mi Gente)
  browser_fetch.py          generic Playwright image harvester
  econo_fetch.py            store-gated interactive Playwright scraper (Econo)
  cdn_fetch.py              dated historical images (shoppersdepuertorico CDN)
  extract_vl.py             PDF/images -> Qwen3-VL -> validated offer rows
  validity.py               per-source validity-date detection (text + VL)
normalize/
  units.py                  size parsing + unit-price computation
  db.py                     storage layer: SQLite or Postgres via DATABASE_URL
  pg_compat.py              sqlite-like wrapper over psycopg2
  cycle.py                  price-cycle / trend detection + buy recommendation
  basket.py                 per-chain basket totals + cheapest-basket verdict
  canonicalize.py           conservative VL-typo canonicalization
  schema.sql / schema_pg.sql  SQLite / Postgres schemas
run_weekly.py               hardened orchestrator (flock, stale-sweep, isolation)
notify_lists.py             post-scrape user digest via Resend
seed_b2b_demo.py            synthetic events for the B2B demo
migrate_pg.py               one-time SQLite -> Postgres migration
backfill.py                 historical backfill from the CDN (see BACKFILL.md)
fly.toml / Dockerfile       hosted API (slim deps: requirements-api.txt)
serve_vl.sh                 launch vLLM OpenAI server for Qwen3-VL
refresh.sh                  weekly wrapper: VL up -> scrape -> notify
deploy/                     systemd units, backup/alert scripts, netlify deploy
docs/                       ARCHITECTURE, API, LEARNINGS
```

## Operations (menatech01)

- **Scrape timer**: `pr-shopper-scrape.timer` (Thu+Sun 06:00) → refresh.sh →
  run_weekly (writes to Supabase via DATABASE_URL in a systemd drop-in) →
  notify_lists.py (user digests via Resend).
- **Backup timer**: `pr-shopper-backup.timer` (nightly 03:30) → mt03
  ~/backups/plaza-pr, 14-day retention.
- **Failure alerts**: OnFailure → pr-shopper-notify@.service → Telegram.
- **Secrets**: `.env.supabase` (gitignored, chmod 600) holds the DB password,
  Resend key, and Supabase service key. Fly secrets mirror DATABASE_URL +
  Supabase anon key.

## Local development

```bash
cd pr-shopper-pipeline
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
sudo apt install -y poppler-utils      # pdftoppm / pdftotext

# serve the VL model (needed for PDF/image/browser chains)
bash serve_vl.sh                        # Qwen3-VL on :8100

# scrape all chains (SQLite unless DATABASE_URL points at Supabase)
PYTHONPATH=. .venv/bin/python -m run_weekly

# backfill ~4 weeks of history from the CDN (optional, one-time)
PYTHONPATH=. .venv/bin/python -m backfill --weeks 4

# serve the API + dashboard locally (SQLite fallback)
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8200
# open http://127.0.0.1:8200/
```

See `docs/ARCHITECTURE.md` for the full design, `docs/API.md` for endpoints,
`docs/LEARNINGS.md` for operational lessons, and `BACKFILL.md` for the
historical-data strategy.
