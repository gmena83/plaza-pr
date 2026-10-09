# PLAZA — Puerto Rico Supermarket Price Intelligence

Extracts weekly discount circulars ("shoppers") from Puerto Rico supermarket
chains, normalizes them into a queryable database, computes fair unit prices,
detects price cycles, and serves a live dashboard + API for finding the best
price on any product across stores — and when to buy it.

**Live demo:** https://plaza-pr.netlify.app

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
- **Serves** a FastAPI JSON API + a minimalist dark dashboard, deployable as a
  static frontend on Netlify pointed at the live API.

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

~5,000+ active offers/week; 8,000+ offers with history back to 2026-09-17.

## Quick start

```bash
cd pr-shopper-pipeline
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
sudo apt install -y poppler-utils      # pdftoppm / pdftotext

# serve the VL model (needed for PDF/image/browser chains)
bash serve_vl.sh                        # Qwen3-VL on :8100

# scrape all chains
PYTHONPATH=. .venv/bin/python -m run_weekly

# backfill ~4 weeks of history from the CDN (optional, one-time)
PYTHONPATH=. .venv/bin/python -m backfill --weeks 4

# serve the API + dashboard
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8200
# open http://127.0.0.1:8200/
```

## Repo layout

```
api/main.py                 FastAPI: search, best, best_unit, product detail,
                            product history, recommendation, stats, dashboard
api/static/dashboard.html   single-file dashboard (dark, monospace)
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
  db.py                     SQLite layer, dedup, products dimension
  cycle.py                  price-cycle / trend detection + buy recommendation
  canonicalize.py           conservative VL-typo canonicalization
  schema.sql                offers / chains / scrape_runs / products + views
run_weekly.py               hardened orchestrator (flock, stale-sweep, isolation)
backfill.py                 historical backfill from the CDN (see BACKFILL.md)
serve_vl.sh                 launch vLLM OpenAI server for Qwen3-VL
refresh.sh                  weekly wrapper (ensures VL up, runs scrape)
deploy/                     systemd user units + timer, netlify deploy
docs/                       ARCHITECTURE, API, LEARNINGS
```

## Scheduling (systemd user)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/*.service deploy/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pr-shopper-scrape.timer   # Thu+Sun 06:00
systemctl --user enable --now pr-shopper-api.service    # API on :8200
```

See `docs/ARCHITECTURE.md` for the full design, `docs/API.md` for endpoints,
`docs/LEARNINGS.md` for operational lessons, and `BACKFILL.md` for the
historical-data strategy.
