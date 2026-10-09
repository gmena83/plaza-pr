# Anchor Files — the load-bearing pieces

Read these first to understand or modify the system.

## Entry points
- `run_weekly.py` — orchestrator. Weekly scrape of all enabled chains.
  Hardened (flock, stale sweep, per-chain isolation). The systemd timer calls
  `refresh.sh` which calls this.
- `backfill.py` — one-time historical backfill from the CDN (see BACKFILL.md).
- `api/main.py` — FastAPI app: all JSON endpoints + serves the dashboard at `/`.

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
- `db.py` — schema access, upsert, `dedup_offers`, products dimension.
- `cycle.py` — price-cycle/trend detection + buy recommendation verdicts.
- `canonicalize.py` — conservative VL-typo fixes. Keep the map SHORT.
- `schema.sql` — tables + history views. Migrate live DB with ALTER on change.

## Serving / deploy
- `api/static/dashboard.html` — the whole frontend (single file). The colleague
  reskins THIS.
- `serve_vl.sh` — launches Qwen3-VL via vLLM on :8100 (AWQ, tuned for 16 GB).
- `refresh.sh` — weekly wrapper: ensures VL up, runs run_weekly.
- `deploy/*.service|*.timer` — systemd user units (API, VL, scrape timer).
- `deploy/netlify/` — static demo deploy (index.html + README with redeploy).

## Docs
- `docs/ARCHITECTURE.md` — full design + data-flow diagram.
- `docs/API.md` — every endpoint with shapes.
- `docs/LEARNINGS.md` — 20 operational lessons. Read before changing scrapers.
- `BACKFILL.md` — historical-data strategy + CDN availability map.
