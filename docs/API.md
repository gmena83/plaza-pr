# API Reference

Base URL (production): `https://plaza-pr-api.fly.dev`
Base URL (local): `http://127.0.0.1:8200`

Public endpoints are read-only GET. CORS is open (`allow_origins=["*"]`).
List endpoints are authenticated (Supabase bearer token).
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

## User lists (authenticated)

Auth: Supabase magic-link. The frontend stores `access_token` /
`refresh_token` in localStorage and sends `Authorization: Bearer <token>`.
The API validates the token against `{SUPABASE_URL}/auth/v1/user`.

- `GET /api/list` -> the caller's list with per-item best offer, per-chain
  basket ranking, and `verdict` (cheapest full basket this week):
  ```
  { email, list_id,
    items: [{item_id, product_norm, display_name, size, target_price,
             best: {chain_slug, price_sale, unit_price, price_basis, ...} | null,
             on_sale, n_chains}],
    chains: [{chain, total, found, coverage}],
    verdict: {chain, total, saving_vs_next, message} | null }
  ```
- `POST /api/list/items?product_norm=N&display_name=D&size=S&any_size=B&target_price=T`
  -> upsert one item (idempotent per list+product+size).
- `DELETE /api/list/items/{item_id}` -> remove (scoped to the caller's list).

Returns `401 {"detail":"login requerido"}` without a valid token.

## B2B analytics (public, synthetic data in beta)

- `GET /api/b2b/overview` -> `{synthetic:true, weekly_activity[], top_searches[],
  brand_weekly[], chain_engagement[], funnel[]}` over the `events` table.
- `GET /api/b2b/brand/{brand}` -> weekly attention, event-kind conversion,
  and the brand's current real offers (price position).

## Notes for consumers
- `unit_price` + `price_basis` give fair comparison (`$/lb`, `$/100ml`, `$/un`).
  Prefer these over `price_sale` when comparing across chains or pack sizes.
- `sku` is the retailer SKU when the source exposes one (structured chains),
  else a stable generated key `chain:product_norm|size`.
- `size_canonical` is the normalized size (e.g. `15.5oz`, `12x10oz`, `3lbs`) —
  use it (not raw `size_text`) to group the same pack across weeks.
