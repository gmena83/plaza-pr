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
  **Mi Lista email digest** every Monday and Thursday (see below).
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
  nightly Postgres backup to mt03 |
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

## Mi Lista email digest

Every Monday and Thursday each user with list items gets one email, sent via
Resend from `PLAZA <milista@plazapr.menatech.dev>` (subdomain verified: DKIM,
SPF, DMARC `p=reject`; mail-tester 10/10). Replies go to `contact@menatech.dev`;
the footer carries the postal address (410 Francisco Sein, San Juan, PR 00917).
Both are defaults in `notify_lists.py`, overridable with `PLAZA_REPLY_TO` /
`PLAZA_POSTAL_ADDRESS`.

- **Headline:** the best 1- or 2-store plan for the list
  (`normalize/basket.store_plan`): "Walmart + Agranel cubren 3 de 6 productos",
  estimated total, savings vs regular price.
- **Per item:** price, unit price, old price, valid-until date, plus one advice
  line: hit your target price, real deal vs its history (same cycle engine as
  `/api/recommendation`), wait (it usually drops next week), rising, or dropped
  vs its last circular.
- Items on offer only at a third store, and items with no offer this week,
  are listed separately.
- Opt-in by default; "Resumen por email" checkbox in Mi Lista; footer link
  goes to a one-button confirm page; RFC 8058 one-click unsubscribe header.

Schedule and safety (`notify_lists.py`):
- Thursday: sent by `refresh.sh` right after the 06:00 scrape. Monday 07:30:
  `pr-shopper-digest.timer`, which also retries Thursday at 11:00 (no-op if sent).
- One email per user per slot: `email_log` UNIQUE + Resend Idempotency-Key.
- Never mails stale prices: Thursday requires this week's scrape to have
  succeeded for 6+ chains; every slot requires 6+ chains with current offers.
  Otherwise it skips and pings Telegram.
- Send summary and failures go to Telegram.

```bash
set -a; . ./.env.supabase; set +a          # DATABASE_URL, RESEND_API_KEY
PYTHONPATH=. .venv/bin/python notify_lists.py --preview /tmp/digest   # HTML+text per user, no send
PYTHONPATH=. .venv/bin/python notify_lists.py --dry-run               # who would get what
PYTHONPATH=. .venv/bin/python notify_lists.py --test-to you@x.com     # [PRUEBA] copy, not logged
PYTHONPATH=. .venv/bin/python -m pytest tests -q                      # digest/store-plan unit tests
```

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
  reco.py                   per-product recommendation (shared by API + email)
  basket.py                 per-chain basket totals + 1-/2-store plan
  digest.py                 Mi Lista email content + Jinja rendering
  canonicalize.py           conservative VL-typo canonicalization
  schema.sql / schema_pg.sql  SQLite / Postgres price schemas
  schema_users_pg.sql       lists, email prefs/log, RLS, public-key lockdown
templates/                  digest.html.j2 / _row.html.j2 / digest.txt.j2
tests/                      pytest unit tests (store plan, digest helpers)
run_weekly.py               hardened orchestrator (flock, stale-sweep, isolation)
notify_lists.py             Mi Lista digest sender (Mon/Thu, Resend)
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
  run_weekly (writes to Supabase) → notify_lists.py (Thursday digest).
- **Digest timer**: `pr-shopper-digest.timer` (Mon 07:30, Thu 11:00 fallback).
- **Backup timer**: `pr-shopper-backup.timer` (nightly 03:30) →
  `deploy/backup_db.sh`: every Postgres table + auth user ids/emails as CSV,
  schema files, verified row counts → mt03 `~/backups/plaza-pr/`, 14 days.
  Prove an archive restores (rolled back, safe on prod):
  `deploy/restore_db.py plaza-YYYYMMDD.tar.gz`; `--apply` restores into a
  fresh database.
- **Failure alerts**: OnFailure → pr-shopper-notify@.service → Telegram.
- **Secrets**: one file, `.env.supabase` (gitignored, chmod 600): DB password,
  DATABASE_URL, Resend key, Supabase service key. All three systemd units load
  it via `EnvironmentFile=`, so rotating a key is a single edit. Fly secrets hold
  DATABASE_URL + Supabase URL/anon key.
- **Public key**: the publishable key in dashboard.html can read price data
  but cannot write any table (see `normalize/schema_users_pg.sql`).

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
