# PLAZA development sprints — 2026-10-13

## Product constraints and decisions

- Current PLAZA compares public shopper specials, with Supabase email magic-link accounts and Mi Lista. The app is served from Netlify `/app/`, backed by Fly API and Supabase. There is no full catalog in production and no real event collector; the B2B activity demo is synthetic. The account-only assistant is constrained to current offers; it is not a general-purpose agent or forecast.
- Preserve the difference between observed online catalog prices, verified weekly shopper membership, merchant-claimed `Reg.`, and independently measured non-promo prices. Missing from a circular means **price unknown**, not regular price.
- Full profile minimum: saved Mi Lista item, preferred stores, shopping cadence; no legal name. Password login remains deferred: magic-link Auth is the tested account method. Commercial reporting: optional opt-in and reviewed aggregate reports only, never individual records. Say PLAZA is free now, not "free forever." Operator/privacy contact: Menatech LLC, contact@menatech.dev.
- No analytics sale or production event collection begins before consent controls and an accurate published policy. Digest preferences are separate from profile completion and default **off** for new accounts.

## Sprint 0 — Historical source and quality gate (capture done; import deferred)

**Goal:** recover the 2026-09-30, 09-23 and 09-16 Pueblo flyers without pretending they are full historical catalogs.

1. Download and preserve all eight dated JPEG pages per week from `cdn.shoppersdepuertorico.com` with required Referer, source URL, week, SHA-256 and page count; see `spikes/002-pueblo-history/archive.py` and gitignored `data/pages/pueblo_YYYY-MM-DD/`.
2. Transcribe locally with the existing Qwen3-VL server; cache raw page-level JSON, retry dense/truncated pages with tiles, and refuse an incomplete manifest. Do not write to `offers` until quality is checked. Test with `env -u PYTHONPATH -u PYTHONHOME .venv/bin/python -m pytest spikes/002-pueblo-history -q` (Hermes injects an incompatible site-packages path otherwise).
3. The structural audit in `spikes/002-pueblo-history/AUDIT.md` found 695 raw rows, 54 missing sizes, 25 inverted merchant `Reg.` fields, a visually confirmed transcription error and negligible direct string overlap with the current structured shopper. The owner chose on 2026-10-13 to **keep the archive local** and prioritize forward snapshots/accounts/mobile rather than manually matching historical offers now. A future import would require stratified image QA, stable identity/pack evidence, staging, rollback and source-page provenance. Existing `backfill.py` assumes Thursdays and excludes Pueblo—do not run it unchanged.
4. Keep the next-edition paired catalog/shopper timer from `deploy/pr-shopper-pueblo-pilot.{service,timer}`; its output is a separate current-vs-next full-catalog comparison, not historical archive backfill.

**Exit:** three structurally complete flyer captures and documented quality/matching limitations; **no-go for production ingestion or prediction on raw rows**. The three flyers cover promoted subsets only, not a month of every product's price. Defer manual curation until later ROI review.

## Sprint 1 — Mobile trust and discovery (integrated demo deployed)

**Goal:** useful 320–430px mobile search/list flows and visible source coverage before more features.

- The mobile-first search/list, profile onboarding and conversational UI are deployed in both byte-identical dashboard copies. Local fixture QA covered signed-in onboarding/assistant layout at 320px and 375px; browser QA against the byte-identical Fly-served production dashboard exercised live observed-offer search and the fictional projection at 320px/375px with no page-level overflow. This does **not** prove a signed-in Netlify browser session through the visitor gate.
- Continue: the owner will test a fresh magic-link round trip through the protected Netlify `/app/` page. Then validate signed-in search, filters, per-product modal/history, list edits and errors one-handed, including slow connections, long names, Spanish labels and no-data states.
- Include coverage caveat for Walmart, freshness indicator and weekly validity; do not market historical predictions as already available.

**Exit:** no page-level horizontal overflow; ≥44px touch targets; visible add/remove feedback; list/search/history reachable without long-scroll friction; human visual review of real mobile screenshots.

## Sprint 2 — Account and completed profile

**Goal:** owner-scoped lists, a completed-profile gate, and a tested account flow; password signup is a separate future Auth change.

- The **deployed** and tested account flow remains Supabase email magic links; the password/Google tabs merged to GitHub on October 17 but have **not** been published to the manually deployed Netlify site. The live `/auth/v1/settings` read on October 17 returned `disable_signup=false`, `mailer_autoconfirm=true`, `external.email=true`, and `external.google=false`. Do **not** publish password signup or Google buttons until email confirmation, recovery, rate limits, existing-user compatibility, OAuth provider/callback configuration, and the site-password redirect are checked with throwaway accounts. Never store plaintext passwords in PLAZA's DB or browser. The owner chose a reviewed/configured **later full release**, not the merged source as-is; see `deploy/NETLIFY.md`.
- `profiles` schema was migrated to the target database with RLS enabled, no `anon` SELECT grant, no `authenticated` INSERT grant, and `email_prefs.enabled` default false. `GET/PATCH /api/profile` and `/api/assistant` are deployed on Fly, and both dashboard copies implement onboarding. A full profile means an authenticated account with ≥1 saved list item, ≥1 preferred chain and cadence; `/api/assistant` enforces it server-side. A temporary account exercised magic-link login, profile completion, offer questions and confirmed list edit/remove against **live Fly**, followed by admin-user deletion and DB cleanup readback. Netlify's protected-page browser login remains for the owner to test.
- Target-price editing, size matching and digest opt-in are independent; the assistant produces proposals, never automatic writes. The normal authenticated list endpoints enforce ownership after user confirmation.

**Exit for this demo scope:** magic-link users retain owner-scoped lists, only the owner edits profile/list, and incomplete profiles can still use public search and Mi Lista. Password signup/recovery requires a later Auth decision and test.

## Sprint 3 — Useful recommendations before forecasting

**Goal:** recommend similar *currently verified* on-sale alternatives without claiming future prices.

- Use comparable category, pack and unit price plus conservative brand/variant matching from `normalize/basket.py`, `normalize/reco.py`, `api/main.py`; explicitly label substitutes and exclude uncertain sizes or dietary variants. Present a reason/source week for each recommendation and let users dismiss it.
- Add list-level price watch and digest choice; suppress stale offers, duplicates and wrong-size alerts. Test exact items, pack differences, no-match, missing price and unsubscribed users.

**Exit:** a saved list gets actionable current specials and defensible alternatives with source and validity, not invented baseline savings.

## Sprint 4 — Privacy controls and policy before commercial analytics

**Goal:** earn trust before collecting/selling behavioral insights.

- Use `docs/PRIVACY_DRAFT.md` as an **unpublished** working draft. Confirm provider/log inventory, active DB retention, backup behavior, export/deletion workflow, age approach, versioning and counsel review. Build a separate, default-off reporting choice with equal 'Sí' / 'No, gracias' controls; refusal leaves core app usable. Explain free service and planned statistical-report model at signup and in persistent settings; do not claim zero reidentification risk.
- Only after consent is verifiable, collect a minimal allowlisted event schema; separate it from account/list tables; retain raw source events for a defined short interval, support future withdrawal/deletion of linkable source data and audit access. Buyer exports are reviewed aggregate reports only—no individual rows, IDs, lists, precise location or raw clickstream. Suppress small/rare/overlapping cells and contractually prohibit reidentification/secondary transfers. Keep the synthetic `/negocios` demo distinguishable from real data and require authenticated authorization before exposing real analytics.
- Tests: refuse ⇒ no commercial events; consent ⇒ minimal events; withdraw ⇒ no future events; deletion and aggregate export safety; privacy notice matches code. Legal review is a release gate, not a legal conclusion by this plan.

**Exit:** published policy and UX accurately match measured behavior; opt-in audit works end to end; no raw or reidentifiable buyer export is possible; owner approves actual recipients and retention periods.

## Sprint 5 — Prediction research, then conditional feature

**Goal:** determine whether a shopping-timing estimate adds value beyond present-week deals.

- The owner requested the **integrated PLAZA prototype** (both dashboard copies) show a synthetic projection card directly after observed price history for ally/sponsor/investor feedback, not a separate site. Fixed invented basket/week totals remain exclusively in browser code, outside `offers`, Mi Lista, analytics and prediction evaluation; **DATOS FICTICIOS** sits next to both chart and result. The demo-only release was published to Netlify on 2026-10-13 after the site-wide visitor-password challenge was verified on `/` and `/app/`. This **does not** waive the separate Sprint 5 gate for any real prediction. See `docs/PREDICTION_STUDY.md` and `deploy/NETLIFY.md` for the remaining owner-run protected-browser login check.

- A **read-only Sprint 5 study is active on menatech03**: `spikes/001-pueblo-catalog/research.py` preserves complete paired catalog/shopper snapshots and `evaluate.py` scores item-price research baselines chronologically. The Thu/Fri/Sun 11:00 UTC mt03 timer and daily non-deleting backup to mt01 were installed and exercised against an unchanged edition on 2026-10-17; mt01's duplicate research timers are disabled, while its ordinary multi-chain scrape timer remains active. The evaluator currently has **2 complete paired editions** (October 7 and 14), **0 untouched evaluation cutoffs**, and `prediction_release_approved=false`. A first genuinely new mt03 capture and sync have not yet been observed. Historical July–October flyer first pages may support a separate advertised-specials corpus after page/date/pack QA, but they cannot fill missing complete Pueblo catalog weeks; see `docs/PREDICTION_STUDY.md` and `docs/HISTORICAL_SHOPPER_RECON_2026-10-17.md`.
- Collect consecutive paired shopper **and full catalog** observations per chain/store/channel for the same SKU and unchanged pack, record availability and promo status. Archived flyers add advertised history but cannot fill missing regular-price observations. Instrument only the minimum needed to assess basket coverage (not commercial behavior before opt-in).
- Start with current cheapest verified offer, buy-now and last-observed-price baselines. Freeze basket and information at each cutoff; expanding-window walk-forward test on later weeks. Report item/basket coverage, price error, decision accuracy, realized cost or regret where both choices are independently observable, abstention and confidence. No row-randomized train/test split across the same shopper edition.
- Proposed review gate: approximately 8–12 consecutive paired editions plus ≥4 untouched evaluation cutoffs, meaningful coverage of target baskets, and a predeclared material advantage after extraction/QA costs. Numbers are a proposed study design, **not** evidence of accuracy or a product launch date. If the evidence fails, keep 'insufficient history' rather than a forecast. Weekly data cannot justify 'best day'; seasonal 'best month' requires far longer history.
- Only after the gate passes, add the completed-profile-gated prediction section beside price history, with a concrete horizon, range/confidence and disclaimer: **«Estimación basada en precios observados, no una garantía ni una mirada al futuro. Las ofertas, inventario y precios pueden cambiar.»** Enforce eligibility server-side; do not imply future store inventory is known.

**Exit:** a reproducible held-out evaluation beats simple baselines with adequate coverage and honest uncertainty, or a documented no-go. No forecast is published merely because a model produces a number.

## Sprint 6 — Rollout/ROI review

Validate demand with real shoppers and potential buyers for aggregate insights before scaling event collection. Track opt-in rate, repeat-use/list retention, savings utility and support burden—without treating synthetic demo events as traction. Release by feature flag, monitor source freshness and scrape accuracy, run a privacy/security review, and verify Netlify/Fly/Supabase live readback. No commitment to 'lots of views' or perpetual free service can be supported by current evidence.

## Remaining human inputs at the appropriate gates

- Demo release: the owner chose to test the protected Netlify `/app/` magic-link round trip personally, then profile completion, a grounded answer and one explicitly confirmed Mi Lista edit. Report any lost session without sharing token hashes or passwords. A successful API account test and HTTP 401 challenge do not establish this browser behavior.
- Sprint 0: no further archive import decision is needed now; owner chose to keep it local until match quality/ROI improves.
- Sprint 2: confirm cadence choices (weekly/biweekly/monthly) and which stores are selectable; confirm password-email templates and owner approval for production Auth config.
- Sprint 4: set retention per data category, minimum cohort/report granularity, buyer categories, allowed category/region reporting, and exact deletion/export service process; provide counsel sign-off before publishing the policy. Menatech LLC and contact@menatech.dev are provided.
- Sprint 5: approve the held-out evaluation metric/threshold and product copy once actual coverage is measured. No choice is needed now to collect more observations.
