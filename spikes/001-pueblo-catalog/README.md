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

## Step 4: compare after the next shopper changes (scheduled)

`followup.py` checks Pueblo's printed shopper validity window and waits until it advances beyond the 2026-10-07 edition. It then captures one complete shopper and catalog pair into `data/catalog-pilots/pueblo-shopper-<edition-start-YYYYMMDD>/` and `pueblo-<edition-start-YYYYMMDD>/`, verifies the edition did not change mid-capture, and writes `week_compare.json` into the catalog directory. The comparison uses Pueblo SKU plus unchanged package size, categorizes SKUs that left/entered/remained on the shopper, and measures price changes only for comparable items. It does **not** call a catalog-only price a regular price or a two-snapshot difference a historical average. The report includes full transition records and counts of missing or changed-size SKUs; selected examples still need product-detail review before interpreting promotion status or availability.

The one-off user-systemd timer in `deploy/pr-shopper-pueblo-pilot.{service,timer}` is installed and enabled for Thu 2026-10-15 09:00 AST with Fri 2026-10-16 09:00 AST fallback. It has no future recurrence. Each capture is rate-limited to 1.25 seconds per page, caches responses for resumable retries, and writes only under the gitignored pilot directory. The second invocation skips work if a report already exists. If both dates fail, run manually after the shopper changes:

    .venv/bin/python spikes/001-pueblo-catalog/followup.py --check
    .venv/bin/python spikes/001-pueblo-catalog/followup.py
    journalctl --user -u pr-shopper-pueblo-pilot.service --no-pager

This CLI session receives no automatic result notification. As of 2026-10-13 11:30 AST, Pueblo still displayed the 2026-10-07 edition, so no cross-week findings exist yet. A same-edition dry comparison validated the parser against all 20,175 catalog SKUs and 935 shopper SKUs, yielding zero transitions as expected.

## Separate Sprint 5 prospective prediction study

The owner clarified that **Sprint 5 prediction research** (not this pilot's step 5 go/no-go) is the gate for a **real forecasting feature**. A separate demo-only Netlify release was authorized; its invented card does not satisfy this study. `research.py` uses the same lock and paired snapshot format but recurs across future shopper editions; `evaluate.py` computes offline, leakage-free item-price baselines and always refuses to approve a public prediction. The read-only `deploy/pr-shopper-pueblo-research.{service,timer}` is enabled for Thu, Fri and Sun 11:00 AST, with a successful no-op service run and evaluation readback on 2026-10-13. Full protocol and limitations: [`docs/PREDICTION_STUDY.md`](../../docs/PREDICTION_STUDY.md). The one-off timer remains installed for the first next-edition comparison; both services share a lock and skip a completed edition.
