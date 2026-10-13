# Pueblo three-week flyer pilot — extraction audit (2026-10-13)

State: **local read-only capture complete; NOT approved for production import or prediction.**

Pueblo's archived printed circulars have eight JPEG pages each and visibly print validity Sep 16–22, Sep 23–29, and Sep 30–Oct 6, 2026.[6][7][8] These are curated weekly **specials**, not the ~935-item structured online shopper or a historical full priced catalog. `Referer: https://www.shoppersdepuertorico.com/` was required. The page 09 URL returned 404 for each week. The images were saved in `data/pages/pueblo_YYYY-MM-DD/page-NN.jpg`; raw local-Qwen3-VL extractions and checked manifests are in `data/catalog-pilots/pueblo-archive/YYYY-MM-DD/` (gitignored). `spikes/002-pueblo-history/archive.py` reruns from checksummed page caches, refuses empty/unparsed pages and uses overlapping halves/quadrants for dense ones.

| Edition | Pages/manifest | Raw offer rows | Missing size | Model `Reg.` below sale |
|---|---:|---:|---:|---:|
| Sep 16–22 | 8, complete | 229 | 1 | 8 |
| Sep 23–29 | 8, complete | 230 | 10 | 11 |
| Sep 30–Oct 6 | 8, complete | 236 | 43 | 6 |
| **Total** | **24** | **695** | **54** | **25** |

All manifest page checksums were rechecked against the 24 saved JPEGs; no mismatch. `complete` means all eight pages produced parseable rows, **not** that every transcribed offer is accurate. The Sep 30 edition also has 17 duplicate (normalized name, size, price) rows. On Sep 30 page 3, the model transcribed Rosina Meatballs as sale $6.49 / merchant `Reg.` $5.19; visual inspection of the actual image shows **sale $6.49 / `Reg.` $8.19**. This is a confirmed transcription error, not a valid discount calculation. Other inverted `Reg.` values are flags for manual review, not a measured error rate.

## Comparability and prediction

After basic accent/case/punctuation normalization (not fuzzy SKU matching), Sep 23 vs Sep 30 had **38** unambiguous same-name-and-size rows; none changed their advertised price. Sep 16 vs Sep 23 had **one** such row, also unchanged. There was no exact name+size string shared across all three weeks. Name-only joins are unsafe: for example, September's `Nestlé Klim Leche en Polvo` extraction shows $2.29 versus $22.99 with differing/unreliable packages, not a tenfold observed price swing. Against the Oct 7 structured Pueblo shopper (935 SKUs), name-only overlap with each archived edition was only **2–3** strings; images have no Pueblo SKU. These exact-string counts are lower-bound diagnostic signals, not proof that products never recur—VL names/pack strings vary and require human matching.

Archived flyers therefore add sale observations for a limited subset, **not** three weeks of regular prices for a stable product catalog. A raw 695-row import would contaminate price history and Mi Lista recommendations with false pack comparisons and visibly wrong `Reg.` values. Do not run `backfill.py pueblo` (it does not support Pueblo and generates Thursday dates). Do not train or publish best-week/day/month forecasts on this capture. The paired full-catalog follow-up timer remains valuable for later observed baseline data.

## Next quality gate

1. Sample every week and all eight pages, focusing on multi-buy, per-pound, size and price/regular-label anomalies; compare each row to its saved source image. Recover stable identities conservatively; do not invent missing SKUs or infer that an unadvertised SKU has its regular price.
2. Only after quantifying audit precision and match coverage, decide if a **manually curated** historical-sale subset merits production import. Log source image/page, transcription method, pack, validity and a correction record. Test staging import, dedup and rollback; keep ordinary catalog observations separate from `offers`.
3. For actual forecast evidence, collect consecutive paired catalog/shopper captures with same SKU/pack and run held-out walk-forward basket comparisons against simple rules. A historical flyer by itself cannot answer which day or month will be cheapest.

## Sources

[6] https://cdn.shoppersdepuertorico.com/shopper-pueblo-2026-09-30-pagina-01.jpg
[7] https://cdn.shoppersdepuertorico.com/shopper-pueblo-2026-09-23-pagina-01.jpg
[8] https://cdn.shoppersdepuertorico.com/shopper-pueblo-2026-09-16-pagina-01.jpg
