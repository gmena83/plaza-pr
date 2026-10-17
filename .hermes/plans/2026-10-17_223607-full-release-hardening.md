# PLAZA full-release hardening implementation plan

> **For Hermes:** Implement task-by-task with `test-driven-development`, `pr-shopper-scraping`, `web-data-pipeline`, review and browser-QA skills. This plan implements the owner's October 17 choices for a **later** full release; it does not authorize deploying current raw main, changing production Supabase Auth before staging/account checks, or shipping a real forecast.

**Goal:** Make the merged authentication, observed-specials analytics and batch ingestion safe and testable, then configure Google/email providers and verify a protected staging browser journey before a later production release.

**Architecture:** Keep the existing Supabase Auth + Fly API + manually deployed password-gated Netlify prototype. Replace the unvalidated future-week basket table with exact-name/brand/pack/basis matched current advertised specials, showing source dates and coverage without a basket forecast. Fix ingestion consistency with transaction-safe fallback and pack-aware deduplication. Gate password signup and Google button on verified provider settings until external configuration passes; never put secrets in Git or chat.

**Tech Stack:** Existing FastAPI, psycopg2 compat wrapper, SQLite/Postgres, standalone dashboard HTML/JS, Supabase GoTrue Auth, Netlify CLI, Fly CLI, pytest. No paid tool or new hosted app.

---

## Evidence and release boundary

- `main` code review at `7776f31` found unverified signup while `mailer_autoconfirm=true`, Google UI while `external.google=false`, incorrect raw REST redirect handling, uncorrelated callback pending writes, unlabeled 2×/4× current-sale “projections”, Postgres-incompatible two-arg `ROUND(double precision, n)`, failed-batch transaction bugs and size-blind dedup. Details: `docs/RELEASE_READINESS_2026-10-17.md`.
- Read-only production query on October 17: 5,068 date-valid advertised rows across 9 chains, **235** exact `(product_norm, normalized brand, size_canonical, price_basis)` cohorts present at ≥2 chains and **none** at ≥3. Of 472 underlying matched rows, 112 have a nonblank promo; numeric multi-buy conditions such as `2/$4.00` make the derived per-item `price_sale` conditional on purchase quantity. Excluding those leaves **179** comparable single-item cohorts across ≥2 chains, zero at ≥3. A limited current-only comparison is feasible, not a whole-basket or nine-chain coverage claim. It must show missing coverage explicitly.
- Owner's decisions: require email confirmation **after staging/existing-account checks**; replace 2–4 week figures with matched dated current specials and coverage; use Google Cloud project `gen-lang-client-0507313380` (number `734247762212`) for the OAuth client. This is a project identifier, not a client credential.
- Keep current Fly release 9 and Netlify deploy `6ace6372311b38f1bbdc6c3f` live until the later full-release gate. The protected Netlify magic-link journey remains owner-run and unverified. A verified complete Git bundle of source `13fcdf1` exists on mt01 and mt03; ignored data, secrets and local privacy draft are excluded.

## Task 1 — consistent ingestion (independent write scope)

**Files:** `normalize/db.py`, `normalize/pg_compat.py`, `tests/test_db.py`, new isolated DB tests if necessary; `run_weekly.py` only if transaction boundary requires it.

1. Write failing tests for valid–invalid–valid batch (SQLite and isolated Postgres), product rows and actual `offers_found`, duplicate replay with nullable fields, and two distinct pack sizes at the same name/price. Prove the current failures before editing code. Keep tests off production DB.
2. Implement savepoint/rollback around batch attempts and individual-row failure isolation; count only stored rows, preserve the outer transaction or document the atomicity boundary. Make dedup conservative by canonical pack and brand/SKU when available; never delete an uncertain distinct product.
3. Run focused tests red→green, the full suite and Postgres integration against a temporary schema. Read back exact row counts, run status and next-chain behavior. A data migration or production reprocess requires separate decision.

## Task 2 — observed-specials API (independent write scope)

**Files:** `api/main.py`, `tests/test_analytics.py`, optional focused API tests. Do not touch dashboard files in this task.

1. Write failing tests for Postgres numeric aggregate semantics and null prices; unequal basket coverage must not create 1/2/4-week totals. Verify RED; use isolated database fixtures.
2. Replace misleading `/api/analytics/basket_projections` and category-cheapest/public dispersion claims with one `/api/analytics/comparable_offers` response. Contract: `{as_of, scope: "advertised_specials_only", active_offers, active_chains, matched_cohorts, rows:[{product_norm, brand, size_canonical, price_basis, chains:[{chain_slug, price_sale, valid_from, valid_to, source_url, promo}]}]}`. Include only positive date-valid prices, nonempty normalized name/brand/canonical size/basis, **exclude numeric multi-buy promos**, and require cohorts with at least **two distinct chains**. Pick the lowest currently advertised price per chain/cohort; never claim identical in-store stock or future price. Return a bounded, deterministic sample plus the truthful eligible-cohort count.
3. Return generic public 500 bodies while logging details. Verify API responses against SQLite and isolated Postgres, including null data and source validity. If the old routes remain for compatibility, return a clear unsupported status rather than misleading projections. Confirm deployed older frontend does not call these new routes.

## Task 3 — dashboard and Auth (single frontend write scope)

**Files:** `api/static/dashboard.html`, `tests/test_dashboard_static.py`, new focused browser/JS tests. Only after this task, copy the verified source to `deploy/netlify/app/index.html` and hash-compare both copies. No independent worker edits the Netlify copy.

1. Write failing tests for provider gate defaults, request `redirect_to` shape, password recovery, unexpected callback fragments never triggering pending writes, and current-only analytics wording/escaping/error state. Run RED first. Use the existing PLAZA tokens/components; do not create a generic dashboard.
2. Gate signup and Google tabs on live public Auth settings, default to the existing magic-link path, and keep sign-in/recovery discoverable for verified accounts. Handle failed OAuth fragments, prevent uncorrelated account-switch list mutations, support secure password reset and server-side logout. Never log a token or password. Test same-email and stale-session behavior with fixtures, then throwaway staging accounts.
3. Render `/api/analytics/comparable_offers` as a dated, selected-specials-only comparison with each cohort's brand/pack, per-chain offer validity and any non-quantity promo restriction, plus total coverage and a conspicuous non-forecast/multi-buy-exclusion caveat. No 2×/4× table, category “cheapest” over unlike items or empty error-as-zero state. Escape all source data.
4. Run focused JS/API/static tests and full suite. Exercise the integrated page at 320/375px and desktop with real-like long item names; inspect screenshot, console and overflow. Compare both dashboard copies byte-for-byte.

## Task 4 — external Auth configuration and release verification (gated)

1. Inventory the named Google Cloud project/consent screen and existing OAuth clients **read-only** using the owner's authorized browser session. Browser profile access was blocked while Brave holds its Login Data write lock; do not quit their browser without permission. Do not guess credentials or enter secrets in chat. Configure a new Google OAuth client in that project only after confirming allowed brand/domain, callback and project access; keep its secret in the Google/Supabase consoles or approved vault.
2. Stage email-confirmation policy and test existing magic-link users, new password signup, recovery, rate limits, duplicate-email handling, Google same-email identity linking, failed/cancelled OAuth and protected Netlify redirects. Only after those checks, change production Auth settings with explicit owner approval; provider settings must read back as intended.
3. Run full tests and staging smoke checks; review source/DB safety. When all gates pass and owner approves a specific release commit, deploy Fly **before** manual Netlify static files. Read back Fly release ID/image and health/new endpoints; verify Netlify visitor-password HTTP 401 both paths before/after, exact dashboard hash and protected browser login. Do not claim the user-run gate passed until the owner confirms it.

## Follow-up gates from adversarial review

- Browser Auth tests must cover a new-tab email return and root-landed query/hash forwarding, verified same-user versus different-user callback transitions, recovery with an existing session, and access-token expiry with a valid refresh token. A mocked `file://` browser pass is not a protected Netlify round trip.
- Exclude all observed quantity-dependent promotions (`N/$X`, `2x1` and verified variants) from single-item price ranking; add API and browser regression fixtures rather than broadening a regex blindly.
- The existing `(chain, normalized name, size_text, price, edition)` uniqueness key silently drops distinct brand/SKU/promo variants; nullable size permits replay duplicates, and cross-run dedup can invalidate completed run counts. Inventory current data read-only, build an isolated full-schema migration and verify no information loss before seeking approval to apply it. Production preflight: 12,776 rows, 829 missing size text, 735 missing brand, 3,761 missing SKU, and zero groups duplicated by a conservative stable identity (not proof of migration safety).
- Database-wide fallback failures must fail the run, not record `ok`/zero; collector completeness must reject an unexplained empty intermediate page or empty weekly result. The API must not run schema DDL on every read or leak connections. None of these findings authorizes a production rewrite or retroactive data import.

## Risks and stop conditions

- Postgres sandbox unavailable, Google project access missing, OAuth consent/app verification, or unavailable owner browser QA: stop and report a blocker, do not substitute mock success.
- Analytics covers only 179 two-chain single-item matched cohorts today after excluding multi-buy terms, with no matched cohorts at three or more chains. If later QA finds identity mismatch, withhold comparison rather than broaden matching to create more rows.
- A passing local suite or deployed API does not authorize a real shopper forecast, historical offer import or commercial behavioral analytics.
