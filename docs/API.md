# API Reference

Base URL (production): `https://plaza-pr-api.fly.dev`
Base URL (local): `http://127.0.0.1:8200`

Public price endpoints are read-only GET. CORS is open (`allow_origins=["*"]`).
List/profile/assistant endpoints require a Supabase bearer token, and the
owner-scoped list/profile mutation routes require explicit user action.
Only offers where `valid_from <= today <= valid_to` appear in "current"
endpoints; history endpoints span all weeks.

**Release separation:** The new comparable-offers and Auth frontend changes
described below are under review on `release/full-readiness-20261017` and are
**not** on live Fly release 9 or the manually deployed Netlify dashboard.
Check `docs/RELEASE_READINESS_2026-10-17.md` before enabling providers or
publishing this version.

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
- `GET /api/history/{product}` -> minimum advertised price per normalized name,
  chain and edition (from `v_price_history`), for the dashboard search chart.
  Different packs, brands or purchase conditions may share that name; adjacent
  points are **not** verified same-item price changes.
- `GET /api/movers?direction=down|up&limit=N` -> legacy arithmetic changes in
  those minimum advertised prices (from `v_price_trend`). This endpoint remains
  for compatibility but is **not** a comparable-week price-drop or savings
  metric. The unreleased dashboard no longer displays its percentage ranking;
  it explains the history limitation beside the chart.

## Selected comparable advertised specials (unreleased candidate)

- `GET /api/analytics/comparable_offers` ->
  `{as_of, scope:"advertised_specials_only", active_offers, active_chains,
  matched_cohorts, rows:[{product_norm, brand, size_canonical, price_basis,
  chains:[{chain_slug, price_sale, valid_from, valid_to, source_url, promo}]}]}`.
- For this endpoint, `as_of` and the inclusive printed-date filter use the
  **America/Puerto_Rico calendar day**, computed in Python independently of
  the database session timezone (including a UTC session after UTC midnight).
- `active_offers` and `active_chains` count all date-valid positive-price
  advertised offers, including those with quantity-dependent promotions.
  `matched_cohorts` counts the **eligible** exact-name/normalized-brand/
  canonical-pack/price-basis matches across two or more distinct chains after
  excluding quantity-dependent multi-buy promos (`2/$4`, `2x$3`, `2x1`,
  `2 x 1`, `2 por 1`, prefixed wording such as `Oferta 2/$4`, and tested
  equivalents). `rows` is only the first **100**
  deterministically sorted cohorts, not the full matched set. Within each
  cohort, `price_sale` is the lowest currently recorded eligible offer per
  chain. A source link may be absent; validity and availability still require
  checking the printed announcement or store.
- Exact textual matching is a conservative heuristic, **not** verified SKU
  identity, full inventory coverage or a comparable whole basket. It says
  nothing about future weeks. The previously merged
  `/api/analytics/overview`, `/api/analytics/category_comparison` and
  `/api/analytics/basket_projections` endpoints return **410 Gone** in this
  candidate; none is present on the currently deployed Fly release.

## User lists (authenticated)

The currently deployed Auth journey is a Supabase email magic link. The
unreleased frontend defaults to that path and only exposes password signup
after public Auth settings confirm email ownership is required; Google is
hidden while its provider remains disabled. Password recovery and callback
identity review are candidate code paths, **not** successful protected-site
end-to-end tests. The frontend stores `access_token`/`refresh_token` in
localStorage and sends an `Authorization: Bearer …` header to the API; never
include an actual bearer token in logs or examples. The API validates it
against `{SUPABASE_URL}/auth/v1/user`; it never accepts a client-provided
user ID. Production signup confirmation and Google OAuth are not configured.

- `GET /api/list` -> the caller's list with per-item best offer, per-chain
  basket ranking, `verdict` (cheapest full basket this week) and
  `digest_enabled` (Mi Lista email on/off, default **false** until opt-in):
  ```
  { email, list_id, digest_enabled,
    items: [{item_id, product_norm, display_name, size, any_size, target_price,
             best: {chain_slug, price_sale, price_regular, promo, unit_price,
                    price_basis, ...} | null,
             on_sale, n_chains}],
    chains: [{chain, total, found, coverage}],
    verdict: {chain, total, saving_vs_next, message} | null }
  ```
- `POST /api/list/items?product_norm=N&display_name=D&size=S&any_size=B&target_price=T`
  -> upsert one item (idempotent per list+product+size); returns
  `{ok, item_id, count}`.
- `PATCH /api/list/items/{item_id}?any_size=B&target_price=T&clear_target=B`
  -> update one item.
- `DELETE /api/list/items/{item_id}` -> remove (scoped to the caller's list).
- `PATCH /api/list/prefs?digest=true|false` -> turn the Mon/Thu email on/off.

Returns `401 {"detail":"login requerido"}` without a valid token. The API
caches a validated token for 60 s.

## Completed profile and grounded assistant (authenticated)

- `GET /api/profile` -> `{preferred_chains:[slug], shopping_cadence,
  list_item_count, complete}` for the bearer-token owner. `complete=true`
  requires a saved item, at least one preferred chain, and a shopping cadence.
- `PATCH /api/profile` with JSON
  `{ "preferred_chains": ["pueblo"], "shopping_cadence": "weekly" }`
  (cadence: `weekly|biweekly|monthly`) validates chain slugs and updates only
  the owner. A missing list item keeps `complete=false`.
- `POST /api/assistant` with JSON `{ "message": "¿Dónde compro carne más barata?" }`
  returns `{kind, answer, offers:[], actions:[]}` (and `counts` for specials).
  It requires both a valid bearer token and a complete profile; otherwise
  401/403. The input is limited to 3–220 characters. There is **no external
  LLM**: supported intents cover current offer lookup, distinct product/size
  shopper counts, cautiously scoped meat/oat-milk comparisons, and Mi Lista
  edits. It may return `no_data` rather than a universal cheapest-store claim.
  Offer evidence includes source URL (when present), store, pack, price and
  validity; the source is current shopper `offers` only, never the fictitious
  projection or unreviewed archive.
- List mutations return `kind=list_proposal` with `actions[]` containing a
  label, method, owner-scoped list path, parameters and
  `requires_confirmation=true`. This POST never writes the list; after the
  user selects an exact product and confirms, the frontend calls the normal
  owner-scoped list endpoint and reloads Mi Lista. The API still checks the
  bearer on that write. Supported edits: price target and any-size matching.

## Email unsubscribe (no login; token from the email)

- `GET /u/{token}` -> confirm page with one button. Opening the link alone
  never unsubscribes (mail scanners pre-fetch links).
- `POST /u/{token}/confirm` -> unsubscribe, page offers "volver a recibirlo".
- `POST /u/{token}` -> RFC 8058 one-click unsubscribe (Gmail/Yahoo button,
  advertised in the `List-Unsubscribe` header).
- `POST /u/{token}/resubscribe` -> turn it back on.

## B2B analytics (public, synthetic data in beta)

- `GET /api/b2b/overview` -> `{synthetic:true, weekly_activity[], top_searches[],
  brand_weekly[], chain_engagement[], funnel[]}` over the `events` table.
- `GET /api/b2b/brand/{brand}` -> weekly attention, event-kind conversion,
  and the brand's current real offers (price position).

## Notes for consumers
- `unit_price` and `price_basis` help only when product identity, pack and
  units are independently comparable. OCR and merchant size labels can be
  ambiguous (a `23-27 Libras` meat entry was divided again as if the advertised
  per-pound price were a whole-package price); verify against the source before
  making a lowest-unit-price claim. The assistant limits meat to explicit
  one-pound labels and otherwise abstains.
- `sku` is the retailer SKU when the source exposes one (structured chains),
  else a stable generated key `chain:product_norm|size`.
- `size_canonical` is the normalized size (e.g. `15.5oz`, `12x10oz`, `3lbs`) —
  use it (not raw `size_text`) to group the same pack across weeks.
