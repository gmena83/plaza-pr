# Architecture

PLAZA is a pipeline: **ingest -> extract -> normalize -> store -> analyze ->
serve**. Each stage is isolated so a failure in one chain never blocks the rest.

```
                        ┌────────────────────────────────────────────┐
                        │              SOURCES (11 chains)            │
                        └────────────────────────────────────────────┘
   structured        pdf          images       browser_interactive      cdn
  (Pueblo, Amigo, (Selectos,    (Mi Gente)       (Econo)             (history:
   Ralph's)        SuperMax)                                          8 chains)
       │              │             │                │                  │
       │ HTML         │ pdftoppm    │ download       │ Playwright       │ dated
       │ grid         │ 200dpi      │ full-res       │ store-gate +     │ page
       │ parse        │             │ Wix imgs       │ category click   │ images
       ▼              ▼             ▼                ▼                  ▼
   [structured.py]  ┌──────────────────────────────────────────────────────┐
                    │        VL EXTRACTION (extract_vl.py)                 │
                    │   page images -> Qwen3-VL-8B (vLLM, local)           │
                    │   -> strict JSON rows {product,brand,size,price,...} │
                    └──────────────────────────────────────────────────────┘
       │                                  │
       ▼                                  ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                    NORMALIZE (normalize/)                             │
   │  units.py    size string -> canonical size + base_qty (g/ml/un)      │
   │              + unit_price ($/lb, $/100ml, $/un)                       │
   │  db.py       upsert (idempotent key), dedup_offers, products dim      │
   │  canonicalize.py  conservative VL-typo fixes                          │
   │  validity.py (scrapers) per-source validity-date detection            │
   └──────────────────────────────────────────────────────────────────────┘
       │
       ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │              SQLite (db/shopper.db)                                   │
   │  offers / chains / scrape_runs / products                             │
   │  views: v_price_history, v_price_trend, v_best_prices                 │
   └──────────────────────────────────────────────────────────────────────┘
       │
       ▼
   ┌───────────────────────────┐        ┌─────────────────────────────┐
   │  ANALYZE (cycle.py)       │        │  SERVir (api/main.py)        │
   │  alternating-cycle, trend,│        │  FastAPI JSON + dashboard    │
   │  position-in-cycle,       │───────▶│  + CORSMiddleware            │
   │  buy_now/soon/wait verdict│        │                              │
   └───────────────────────────┘        └─────────────────────────────┘
                                                  │
                          ┌───────────────────────┼───────────────────┐
                          ▼                       ▼                   ▼
                    local dashboard      Tailscale Funnel       Netlify static
                    (same-origin)        (public API proxy)     (cross-origin UI)
```

## Source types (one Python module per type)

- **structured** — the chain runs a shared e-commerce platform exposing a
  paginated product grid at `/controllers/products.html?type=shopper&page=N`.
  We parse server-rendered HTML cards (SKU, brand, name, size, price). No OCR.
  Used by Pueblo, Amigo, Ralph's.
- **pdf** — the chain publishes an image-only PDF. We render pages with
  `pdftoppm` and run VL extraction. Used by Selectos, SuperMax.
- **images** — the chain embeds full-resolution page images (Wix) in a page. We
  harvest the originals and run VL extraction. Used by Mi Gente.
- **browser_interactive** — the circular is a JS app behind interaction. Econo
  requires selecting a store, then clicking category tabs; we screenshot each
  view and run VL extraction on the screenshots. Reference: `econo_fetch.py`.
- **cdn** — `cdn.shoppersdepuertorico.com` re-hosts each chain's official
  circular as dated page images, giving **historical** weeks the chains' own
  sites don't expose. Used by `backfill.py` for 8 chains.

## Vision-language extraction

Image-based circulars (scanned PDFs, hosted images, screenshots) go to a
**local Qwen3-VL-8B-Instruct (AWQ 4-bit)** served by vLLM with an
OpenAI-compatible API on `:8100`. AWQ fits the 16 GB RTX 5070 Ti with KV-cache
headroom; the fp16 checkpoint did not. Each page is downscaled so its vision
tokens fit the 8192 context, then the model returns a strict JSON array of
products. A Spanish prompt instructs price handling (`2/$5` -> 2.50, promos,
limits). Rows are validated (must have product + numeric price) before insert.

## Data model

- `offers` — one row per product offer per chain per week. Idempotent key:
  (chain_slug, product_norm, size_text, price_sale, valid_from). Never deleted,
  so history accumulates. Carries sku, canonical size, base_qty/base_unit,
  unit_price, price_basis.
- `products` — dimension table, one row per normalized product name, for the
  cross-chain matching and display.
- `scrape_runs` — audit log per chain per run (status, offers_found, validity).
- `chains` — registry of tracked chains.
- Views: `v_price_history` (best price per product/chain/week),
  `v_price_trend` (week-over-week change), `v_best_prices` (current best).

## Normalization — the hard part

Chains write sizes in incompatible ways. `units.py` parses multi-packs
("12 Latas de 10 oz" -> 12×10oz), ranges ("6-8 oz" -> midpoint), Spanish units
("3 LIBRAS", "1.75 Litro"), and price-per-unit strings that leak into the size
field ("95¢ LB."). Output: a canonical size, total content in a base unit
(g / ml / un), and a comparable unit price. ~88-91% of offers get one. This is
what makes cross-chain "cheapest" honest (a 3-lb bag at $0.59/lb beats a 1-lb
at $0.89 even though the sticker is higher).

## Recommendation engine (cycle.py)

Groups history by (chain, product, size_canonical) so cycles are detected on
the same pack size (pack-size changes otherwise look like fake price swings).
Detects cycles on **sticker price** (promos show there; unit_price is noisy
across pack changes). Requires >=15% swing to claim a cycle or a sale — flat
products (e.g. Corona at $9.98 every week) are never mislabeled. Verdicts:
`buy_now` (at a low), `buy_soon` (rising trend), `wait` (alternating cycle, in
the high week), `buy_cheapest` (no cycle, pick current cheapest).

## Orchestration & hardening

- `run_weekly.py` runs all enabled chains. Hardened with a global flock
  (concurrent runs exit fast), a stale-run sweep, per-chain try/except
  isolation, non-zero exit on any chain failure, and idempotent upserts.
- `backfill.py` is a separate one-time job for historical weeks from the CDN —
  not part of the weekly timer.
- systemd user units run the scrape (Thu+Sun 06:00, when PR chains publish) and
  the API. The VL server is started on demand by `refresh.sh`.

## Deployment

The dashboard is a single static HTML file. Locally FastAPI serves it
same-origin. For the public demo, the static file is deployed to Netlify and
the live API is exposed via Tailscale Funnel; the frontend detects the
`*.netlify.app` host and points its API base at the Funnel URL, with CORS
enabled on the API. See `deploy/netlify/README.md`.
