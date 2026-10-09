# API Reference

Base URL (local): `http://127.0.0.1:8200`
Base URL (public demo): `https://menatech01-1.tail706cb2.ts.net`

All endpoints are read-only GET. CORS is open (`allow_origins=["*"]`).
Only offers where `valid_from <= today <= valid_to` appear in "current"
endpoints; history endpoints span all weeks.

## Dashboard
- `GET /` — the single-file dashboard HTML.

## System
- `GET /health` -> `{"status":"ok"}`
- `GET /chains` -> chains with active-offer counts.
- `GET /api/stats` -> dashboard metrics:
  `{total_active_offers, all_time_offers, distinct_products, weeks_of_history,
    chains_tracked, unit_price_coverage, unit_price_pct, history_points,
    per_chain[], last_runs[]}`

## Search & best price
- `GET /search?q=TERM&chain=SLUG&limit=N`
  Current offers matching TERM (case-insensitive substring on product_norm),
  cheapest first. Each result: `{chain_slug, product_raw, product_norm, sku,
  brand, size_text, size_canonical, price_sale, price_regular, promo,
  valid_from, valid_to, unit_price, price_basis}`.
- `GET /best/{product}` -> best sticker price per chain for a term.
- `GET /api/best_unit/{product}` -> best **unit** price per chain, grouped by
  `base_unit` (g / ml / un) so comparisons are like-for-like ($/lb vs $/lb).
- `GET /offers?chain=SLUG&limit=N&offset=M` -> latest offers, paginated.

## Filters
- `GET /api/filters?q=TERM` -> `{chains:[], sizes:[]}` actually carrying TERM
  this week; drives the dashboard filter dropdowns.

## Product detail (popup)
- `GET /api/product?name=NORM&size=SIZE` -> every offer row for one exact
  product_norm (optionally one size), all chains, all weeks.
- `GET /api/product_history?name=NORM&size=SIZE&chain=SLUG` -> weekly price
  points `{chain_slug, week, price, unit_price, price_basis}`, optionally
  filtered to one chain (drives the popup history chart).
- `GET /api/recommendation?name=NORM&size=SIZE` -> cycle-pattern verdict:
  ```
  { product, size,
    recommendation: {action, chain, value, basis, message,
                     (saving_pct|when)?} | null,
    chain_patterns: [{chain, n_weeks, current, low, high, mean, basis,
                      on_sale_now, alternating, cycle_weeks, trend,
                      position_pct, predicted_next, note}] }
  ```
  `action` is one of `buy_now | buy_soon | wait | buy_cheapest`.

## History & movers
- `GET /api/history/{product}` -> weekly best-price points across chains (from
  `v_price_history`), for the dashboard search chart.
- `GET /api/movers?direction=down|up&limit=N` -> biggest week-over-week price
  movers (from `v_price_trend`). Empty until >=2 weeks of history exist.

## Notes for consumers
- `unit_price` + `price_basis` give fair comparison (`$/lb`, `$/100ml`, `$/un`).
  Prefer these over `price_sale` when comparing across chains or pack sizes.
- `sku` is the retailer SKU when the source exposes one (structured chains),
  else a stable generated key `chain:product_norm|size`.
- `size_canonical` is the normalized size (e.g. `15.5oz`, `12x10oz`, `3lbs`) —
  use it (not raw `size_text`) to group the same pack across weeks.
