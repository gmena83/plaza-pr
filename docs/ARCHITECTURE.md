# Architecture

PLAZA is a pipeline: **ingest -> extract -> normalize -> store -> analyze ->
serve -> notify**. Each stage is isolated so a failure in one chain never
blocks the rest, and the public site keeps serving when the workstation that
scrapes is offline.

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
                    │   page images -> Qwen3-VL-8B (vLLM, local GPU)       │
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
   └──────────────────────────────────────────────────────────────────────┘
       │            everything above runs on menatech01 (needs the GPU)
       ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │        POSTGRES — Supabase (prod)   ·   SQLite db/shopper.db (dev)    │
   │  prices:  offers / products / chains / scrape_runs + 3 views          │
   │  users:   lists / list_items / email_prefs / email_log  (+ auth.users)│
   │  B2B:     events                                                      │
   └──────────────────────────────────────────────────────────────────────┘
       │                                          │
       ▼                                          ▼
   ┌─────────────────────────────┐     ┌────────────────────────────────┐
   │ ANALYZE (normalize/)        │     │ NOTIFY (notify_lists.py,       │
   │ cycle.py  cycles, trends,   │     │  menatech01, Mon + Thu)        │
   │           buy verdicts      │────▶│ digest.py + templates/ -> Resend│
   │ reco.py   per-product advice│     │ milista@plazapr.menatech.dev   │
   │ basket.py chain totals,     │     └────────────────────────────────┘
   │           1-/2-store plan   │
   └─────────────────────────────┘
       │
       ▼
   ┌─────────────────────────────┐        ┌────────────────────────────┐
   │ SERVE: FastAPI on Fly.io    │◀──────│ Netlify (static)            │
   │ plaza-pr-api (dfw)          │  CORS  │ /           landing         │
   │ public read API, list CRUD  │        │ /app/       dashboard + Mi Lista│
   │ (Supabase JWT), unsubscribe,│        │ /negocios   B2B demo        │
   │ B2B analytics               │        └────────────────────────────┘
   └─────────────────────────────┘                 │ magic link
                                                   ▼
                                           Supabase Auth
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

Production is Supabase Postgres (`normalize/schema_pg.sql` +
`normalize/schema_users_pg.sql`). `db.py` switches on `DATABASE_URL`; without
it everything runs against SQLite for local development. `pg_compat.py` makes
psycopg2 look like sqlite3 so the scrapers don't care which one they write to.

Prices:
- `offers` — one row per product offer per chain per week. Idempotent key:
  (chain_slug, product_norm, size_text, price_sale, valid_from). Never deleted,
  so history accumulates. Carries sku, canonical size, base_qty/base_unit,
  unit_price, price_basis.
- `products` — dimension table, one row per normalized product name, for
  cross-chain matching and display.
- `scrape_runs` — audit log per chain per run (status, offers_found, validity).
- `chains` — registry of tracked chains.
- Views: `v_price_history` (best price per product/chain/week),
  `v_price_trend` (week-over-week change), `v_best_prices` (current best).

Users (all keyed by `auth.users.id` from Supabase Auth):
- `lists`, `list_items` — a list item is a specific product (`product_norm`)
  and size, or any size (`any_size`), with an optional target price.
- `email_prefs` — digest on/off (opt-in by default) and the unsubscribe token.
- `email_log` — one row per user per digest slot; `UNIQUE(user_id, kind,
  period)` is the double-send guard.

B2B:
- `events` — search/view/list-add events by pseudonymous cohort. Synthetic
  in beta (`seed_b2b_demo.py`); `/api/b2b/*` queries are the real ones.

## Normalization — the hard part

Chains write sizes in incompatible ways. `units.py` parses multi-packs
("12 Latas de 10 oz" -> 12×10oz), ranges ("6-8 oz" -> midpoint), Spanish units
("3 LIBRAS", "1.75 Litro"), and price-per-unit strings that leak into the size
field ("95¢ LB."). Output: a canonical size, total content in a base unit
(g / ml / un), and a comparable unit price. ~88-91% of offers get one. This is
what makes cross-chain "cheapest" honest (a 3-lb bag at $0.59/lb beats a 1-lb
at $0.89 even though the sticker is higher).

## Recommendation engine (cycle.py, reco.py)

Groups history by (chain, product, size_canonical) so cycles are detected on
the same pack size (pack-size changes otherwise look like fake price swings).
Detects cycles on **sticker price** (promos show there; unit_price is noisy
across pack changes). Requires >=15% swing to claim a cycle or a sale — flat
products (e.g. Corona at $9.98 every week) are never mislabeled. Verdicts:
`buy_now` (at a low), `buy_soon` (rising trend), `wait` (alternating cycle, in
the high week), `buy_cheapest` (no cycle, pick current cheapest).

`reco.py` wraps the query + `cycle.recommend` for one product. Both
`/api/recommendation` (the dashboard popup) and the email digest call it, so
the website and the email never disagree.

## Lists and basket intelligence (basket.py)

For each list item, the best current offer per chain (exact size, or any size
by unit price). From that: per-chain basket totals with coverage, a
single-chain verdict when one chain carries the whole list, and `store_plan`,
the best one- or two-store plan. Real lists pin specific products, so one chain
rarely carries most of them; ties on coverage break on the cost of the whole
list, not the plan subtotal.

## Email digest (notify_lists.py + normalize/digest.py)

Monday and Thursday, one email per user with list items. Spanish, PLAZA's
dark monospace style, HTML (table layout, inline styles) + plain text, sent
through Resend from `milista@plazapr.menatech.dev` (DKIM/SPF/DMARC aligned),
replies to `contact@menatech.dev`.

Content: the store plan, then each item with price, unit price, old price,
valid-until and one advice line (target hit, real deal vs history, wait,
rising, dropped vs last circular), then items on offer elsewhere and items
with no offer this week.

Delivery rules:
- Thursday is sent by `refresh.sh` right after the 06:00 scrape; Monday by
  `pr-shopper-digest.timer` at 07:30, which also retries Thursday at 11:00.
- Idempotent: `email_log` row + Resend `Idempotency-Key` per user per slot.
- Freshness guard: no email if this week's scrape didn't succeed for 6+
  chains; a Telegram alert says why and how to re-run.
- Unsubscribe: footer link to a confirm page (GET never unsubscribes, because
  mail scanners pre-fetch links) plus RFC 8058 one-click for Gmail/Yahoo.

## Security model

- The browser talks to the Fly API and to Supabase Auth only. The API and the
  scraper connect as `postgres` through the Supabase pooler; that role owns
  the tables and bypasses RLS.
- The publishable (anon) key in `dashboard.html` can read public price data
  and nothing else: writes on every table are revoked, and so are the default
  privileges for future tables. `lists`/`list_items` also have owner-only RLS;
  `email_prefs`/`email_log` have RLS with no policies (API-only).
- List endpoints validate the Supabase JWT against Supabase Auth (cached 60 s).
- Secrets: `.env.supabase` on menatech01 (gitignored, chmod 600), loaded by
  every systemd unit through `EnvironmentFile=`; Fly secrets for the API.

## Orchestration & hardening (menatech01, systemd user units)

| Unit | When | What |
|------|------|------|
| `pr-shopper-scrape.timer` | Thu + Sun 06:00 | `refresh.sh`: start vLLM, `run_weekly`, Thursday digest |
| `pr-shopper-digest.timer` | Mon 07:30, Thu 11:00 | `notify_lists.py` (Monday send, Thursday fallback) |
| `pr-shopper-backup.timer` | daily 03:30 | `deploy/backup_db.sh` → mt03 |
| `pr-shopper-notify@.service` | OnFailure of all three | Telegram alert |

- `run_weekly.py` runs all enabled chains with a global flock (concurrent runs
  exit fast), a stale-run sweep, per-chain try/except isolation, non-zero exit
  on any chain failure, and idempotent upserts.
- `backfill.py` is a separate one-time job for historical weeks from the CDN.
- The VL server is started on demand by `refresh.sh` if it isn't already
  running; it is not stopped afterwards (GPU memory stays allocated).

## Backups

`deploy/backup_db.sh` takes one consistent snapshot (read-only REPEATABLE READ
transaction) of every `public` table plus `auth.users` id/email, writes CSVs +
the two schema files + a row-count manifest, verifies the counts, and ships
`plaza-YYYYMMDD.tar.gz` to mt03 `~/backups/plaza-pr/` (owner-only, 14 days).

`deploy/restore_db.py ARCHIVE` proves a backup is restorable: it rebuilds the
schema in a throwaway schema inside a transaction, loads every table in
foreign-key order, checks every count, resets identity sequences, inserts a
row, and rolls back. `--apply` does the same into `public` of a fresh project.
Supabase Auth users are not restored; they sign in again with the same email,
and `auth_users.csv` maps old ids to emails for re-owning their lists.

## Hosting & failure modes

- **Netlify** serves static files only (`deploy/netlify/`). Pages on
  `*.netlify.app` call `https://plaza-pr-api.fly.dev` cross-origin; served
  locally by FastAPI they call same-origin.
- **Fly.io** runs the API (slim image, `requirements-api.txt`, region dfw).
  Pushing to `main` should auto-deploy; if `/openapi.json` doesn't show a new
  route, run `flyctl deploy --remote-only`.
- **Supabase** holds the data and Auth. Connections go through the
  session pooler (`aws-1-us-east-1.pooler.supabase.com:5432`); the direct host
  is IPv6-only.
- **menatech01 down:** the site, search, lists and unsubscribe keep working;
  prices go stale (dashboard freshness badge) and digests skip with an alert.
- **Fly or Supabase down:** the site loads but shows no data.
