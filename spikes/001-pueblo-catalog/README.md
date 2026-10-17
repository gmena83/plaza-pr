# Pueblo online catalog snapshot — read-only pilot

Question: Can PLAZA collect a complete, reproducible snapshot of Pueblo's public online catalog before attempting shopper matching or regular-price estimates?

Run from repo root with the project venv:

    .venv/bin/python spikes/001-pueblo-catalog/probe.py --out data/catalog-pilots/pueblo-YYYYMMDD --max-pages 1600 --interval 1.25

For a same-day shopper snapshot, use `--type shopper --out data/catalog-pilots/pueblo-shopper-YYYYMMDD --max-pages 65`. Keep separate output directories so cached `type=all` pages cannot be mistaken for shopper pages.

The run is resumable: completed response pages are cached as compressed HTML with SHA-256 checksums and retrieval timestamps; rerunning reuses and verifies them. `catalog.csv` and `manifest.json` are regenerated at the end from cached responses. An interrupted run can resume without re-requesting completed pages. No database, API, alerts, or production offers are modified. `data/` is gitignored.

Completion is declared only on two consecutive empty pages or a repeated whole-page SKU sequence, not on the configured page limit. Inspect `manifest.json` for `complete: true` before treating the CSV as complete. The scraper saves raw displayed price text as well as a parsed per-item price; multi-buy prices are divided by advertised quantity and cents are converted to dollars. The displayed online price is NOT presumed to be an in-store price or a regular/non-sale price.

## Verdict: VALIDATED for read-only catalog capture

On 2026-10-13, the endpoint returned 1,121 populated pages followed by two consecutive HTTP 200/empty-body pages. The finished snapshot contains 20,175 rows and 20,175 unique Pueblo SKUs; every row has a name, size, and parsed displayed price. Page 1, page 500, and the final populated page (1,121: 15 cards) retained the same SKU order and displayed prices when checked again after the crawl. The capture window was 12:29:36–12:55:07 UTC, not a single atomic price instant. This validates a complete capture of the *public endpoint's visible products at that time*, not Pueblo's entire physical inventory or the correctness of every price.

Artifacts (gitignored): `data/catalog-pilots/pueblo-20261013/catalog.csv`, `manifest.json`, and `pages/*.html.gz` with page metadata/checksums. The endpoint's end-of-results response has a **zero-byte body** rather than an HTML no-results page; the probe treats two such pages as completion. A completed repeat from cache used zero network requests and reproduced the same counts. The production database was not touched. The project suite plus spike contract tests passed (18 tests).

## Same-day shopper cross-check

On 2026-10-13 at 13:04–13:05 UTC, a separate read-only shopper capture completed (52 populated pages and two empty pages): 935 unique shopper SKUs. All 935 were present in the earlier catalog snapshot, with *identical* displayed names, sizes and prices. The catalog had 19,240 additional SKUs not in that shopper. The grid CSV has only the *current displayed price*; it does not include the separate merchant `Reg.` label that appears on some product detail pages. Catalog-only means absent from this shopper, **not** necessarily regular-priced or in stock. Nothing was inserted into `offers` or other production tables.

A stratified 20-detail audit and a duplicate-name/size check are recorded in [AUDIT.md](AUDIT.md). They found non-shopper promotions, out-of-stock items, product-specific validity dates, and different SKUs hidden by identical display names/sizes. Repeated snapshots remain necessary for an independently observed regular-price baseline. PLAZA currently aims at noncommercial comparison of public product/price facts, without copying images or branding. Pueblo's terms about proprietary site material are a consideration for later substantial republication or commercial arrangements, not a blocker to continued technical testing; see [AUDIT.md](AUDIT.md).

## Step 4: first cross-edition comparison (completed)

The October 14 printed shopper edition was captured on October 15 in `data/catalog-pilots/pueblo-shopper-20261014/` and `pueblo-20261014/` (both complete). `week_compare.json` compares it with the October 7 baseline by Pueblo SKU and unchanged pack. The catalog grew from 20,175 to 20,215 distinct SKUs and shopper membership from 935 to 954; 37 SKUs left and 56 entered the advertised shopper. Of the 37 with comparable next catalog display prices, 36 increased and one stayed the same. Those catalog prices are **not** verified regular prices, inventory or in-store prices. Selected detail pages still need review before causal/promotion claims.

The initial one-off pilot timer was disabled on mt01 after this comparison. The continuing read-only job now runs on `menatech03`; see `docs/PREDICTION_STUDY.md` for its verified service/timer and backup status. Both hosts retain the two paired snapshots, and the new mt03 daily sync to mt01 is best-effort when mt01 is online.

## Separate Sprint 5 prospective prediction study

The owner clarified that **Sprint 5 prediction research** (not this pilot's step 5 go/no-go) is the gate for a **real forecasting feature**. A separate demo-only Netlify release was authorized; its invented card does not satisfy this study. `research.py` uses the same nonblocking lock and paired snapshot format but recurs across future shopper editions; `evaluate.py` computes offline, leakage-free item-price baselines and always refuses to approve a public prediction. The research timer and a daily best-effort sync timer are enabled on mt03; the duplicate mt01 research and one-off pilot timers are disabled. The October 17 mt03 run passed but found the already captured October 14 edition, so a first *new* edition on mt03 is still to be verified. Full protocol, archive limits and release gate: [`docs/PREDICTION_STUDY.md`](../../docs/PREDICTION_STUDY.md) and [`docs/HISTORICAL_SHOPPER_RECON_2026-10-17.md`](../../docs/HISTORICAL_SHOPPER_RECON_2026-10-17.md).
