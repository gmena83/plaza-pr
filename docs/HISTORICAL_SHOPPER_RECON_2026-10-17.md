# Puerto Rico historic circular reconnaissance — 2026-10-17 AST

Read-only; no database imports. Browser-origin and Python `urllib` real GETs for CDN assets, with `Referer: https://www.shoppersdepuertorico.com/` and `User-Agent: Mozilla/5.0`. A first-page HTTP 200 with a valid image content type, nonzero length and matching file signature is evidence of a dated flyer, not complete pages; the CDN sometimes negotiates `image/webp` for a `.jpg` URL. Boundary page completeness below means sequential GETs 01 through N returned valid images and N+1 returned 404. The suffix date is treated as a candidate edition start, not a substitute for reading printed validity on historical pages. Current landing pages explicitly print their validity windows. The tested candidate set was 15 weekly dates per chain from each currently observed weekday, plus July–October month-start and nearby-date probes for monthly/irregular chains; this is not a proof that no other historical editions or differently named media exist.

| Chain | Earliest and latest first pages verified (HTTP 200) | Distinct CDN editions found | Boundary page completeness | History assessment |
|---|---|---:|---|---|
| Pueblo | 2026-07-08[1] → 2026-10-14[2] | 15 weekly | 07-08, 07-15, 10-14: 8/8, page 09 = 404 | Yes: 14 uninterrupted Wednesday starts 07-15–10-14 (91 days between starts); 15 including 07-08. |
| Amigo | 2026-07-09[3] → 2026-10-15[4] | 14, with 07-30 missing on CDN | 8/8 at both boundaries | Yes, but CDN alone misses 07-30; an independent eight-page publisher-hosted edition bridges it.[28] |
| Econo | 2026-07-09[5] → 2026-10-15[6] | 15 weekly | 16/16 at both boundaries | Yes, dated flyer archive spans 98 days. |
| Selectos | 2026-07-09[7] → 2026-10-15[8] | 15 weekly | 12/12 at both boundaries | Yes, dated flyer archive spans 98 days; official current PDF is a separate source.[29] |
| Ralph's (`ralphs` in CDN) | 2026-07-10[9] → 2026-10-16[10] | 15 weekly | 8/8 at both boundaries | Yes, dated flyer archive spans 98 days. |
| SuperMax | 2026-07-08[11] → 2026-10-14[12] | 12 first-page hits on weekly Wednesday grid | 12/12 at both boundaries | Yes as dated flyers spanning 98 days, **not** 15 verified weekly editions; missing candidate starts 07-22, 08-19, 09-16. Current flyer is 14 days.[24] |
| Mi Gente | 2026-07-09[13] → 2026-10-15[14] | 7 fortnightly-style hits | 8/8 at both boundaries | Quarter-spanning but a 09-03→10-01 start gap; current landing says no shopper even while dated 10-15 asset answers 200.[27] Printed intervals need verification. |
| Mr. Special | 2026-07-02[15] → 2026-10-08[16] | 13 hits on weekly Thursday grid | 12/12 earliest; 16/16 latest | Quarter-spanning, irregular editions; current flyer is 14 days. |
| Agranel | 2026-07-02[17] → 2026-10-08[18] | 8 every-other-Thursday hits | 8/8 at both boundaries | Quarter-spanning at a fortnightly cadence, not eight weekly observations. |
| Freshmart | 2026-07-01[19] → 2026-10-01[20] | 4 monthly starts (07, 08, 09, 10) | **Unverified historic full page count:** 429 interrupted 07-01 at page 05. Current landing *lists* 8 pages and 01–31 Oct validity.[25] | 92 days between edition starts, but four monthly observations, not 13 weeks. |
| Walmart | 2026-07-08[21] → 2026-09-30[22] | 4 starts every 28 days | **Unverified historic full page count:** 429 at 07-08 page 02; current landing *lists* 20 pages and 30 Sep–27 Oct validity.[26] | 84 days between starts, but four four-week editions may cover July–October. Do not count as 13 weekly observations. |

## Exact response checks and validity

- Pueblo 2026-07-15: `https://cdn.shoppersdepuertorico.com/shopper-pueblo-2026-07-15-pagina-01.jpg` GET 200 `image/jpeg`, 457693 bytes, JPEG magic; `...-pagina-02.jpg` GET 200, 461222 bytes in the saved page-audit run; pages 01–08 GET 200/JPEG and `...-pagina-09.jpg` GET 404. A contemporary independent post states 15–21 July validity.[31] Current landing prints 14–20 October for the 2026-10-14 edition.[23]
- Amigo `https://cdn.shoppersdepuertorico.com/shopper-amigo-2026-07-30-pagina-01.jpg` GET 404, **not** proof no flyer was printed: El Vocero's [30 July–5 August 2026 publication](https://issuu.com/vocero.com/docs/amigo_v_lido_julio_30_-_agosto_05) GET 200 and embedded metadata says `pageCount: 8`, with printed validity in extracted page text.[28]
- Selectos [official shopper page](https://selectospr.com/shopper/) links `https://selectospr.com/wp-content/uploads/2026/10/Shopper-10-15-2026.pdf`, GET 200 `application/pdf`, `Content-Length: 9256486`; 7/9, 7/16, 7/23, 7/30 PDF guesses using this naming convention under `/2026/07/` returned 404, **not** exhaustive proof the official archive lacks them.[29]
- `https://cdn.shoppersdepuertorico.com/shopper-freshmart-2026-07-01-pagina-05.jpg` and `https://cdn.shoppersdepuertorico.com/shopper-walmart-2026-07-08-pagina-02.jpg` returned HTTP 429 after repeated page scans; do not reinterpret them as 404. A subsequent cooldown probe still returned 429. The freshmart July edition's page 01 initially returned 200 `image/jpeg`, 510695 bytes.[19]
- Printed current windows observed directly on the aggregator: Pueblo 14–20 Oct[23] and SuperMax 14–27 Oct[24]. Freshmart lists 1–31 Oct[25] and Walmart 30 Sep–27 Oct[26]. Other currently advertised landing windows: Amigo/Econo/Selectos 15–21 Oct, Ralph's 16–22 Oct, Mr. Special/Agranel 8–21 Oct. Walmart's own `/publicaciones/` page surfaced an older 10 June–7 July edition, not a verified current or comprehensive archive.[30] These are landing-page assertions, **not** a visual transcription of every historical first page.

## Archived website versions: no complete SKU-linked historical pair found

A separate Wayback CDX query for Pueblo's `controllers/products.html*` returned **29** indexed HTTP-200 endpoint snapshots: **0** `type=all` catalog pages, **1** `type=shopper` page 1 (August 12, 2024), **21** narrow `type=search` pages, and **7** `type=similar` pages.[32] The shopper replay has 18 SKU-linked cards with pack and displayed price, but no archived page 2 in that endpoint index.[33] A broader 2026 Pueblo URL index was also checked and did not expose a complete paginated catalog.[34] The October 6 archived `/shopper` landing page displayed the September 30–October 6 flyer images without product SKUs.[35] Archived `home-data.html` carousels are small subsets, not the ~20,000-SKU `type=all` feed. Exact Common Crawl index queries returned 404 or 5xx on the tested indexes; archive.ph responded 404, so their absence is **not** established.[36]

This is a negative finding about the specific archive indexes checked, not a proof that no private or differently indexed snapshot exists. A bounded repeat of exact Common Crawl endpoint queries is reasonable if that service becomes responsive; continue only if dated `type=all` **and** shopper pagination can be completed for the same week. Until then, the 14 candidate consecutive Pueblo flyer first pages are **sale-only evidence**, not 14 complete paired catalog observations. Only the July 8/15 and October 14 Pueblo editions had all eight image pages and a page-09 404 verified in this scan; audit each middle edition before calling it complete. The three September editions already transcribed locally contain 695 raw rows with known OCR/pack errors and remain unimported (`spikes/002-pueblo-history/AUDIT.md`).

## Interpretation and bounded next actions

There is enough discoverable dated *circular* history to investigate a 90-day flyer-specials corpus now for several chains, particularly Pueblo, Econo, Selectos, and Ralph's; Amigo's one CDN gap has an independent publisher copy. This does **not** backfill a 90-day SKU-linked full catalog or regular-price series. Flyers advertise selected items, OCR/vision may miss products or sizes, and 13 weekly starts inside the last 90 calendar days are not interchangeable with 14 consecutive complete SKU-paired weekly snapshots. A flyer-only corpus cannot establish a daily full assortment or baseline pricing.

1. Stop CDN probing until 429 subsides; then verify all pages for candidate editions, prioritize Freshmart/Walmart boundary files and anomalies, and save response/status/content-type/length/actual image signature and checksum in a read-only manifest.
2. Visually validate printed validity, page ordering, and offer/pack transcription for a stratified sample (especially Pueblo's eight-page July flyer); check edition overlap for 14/28/31-day specials. Use publisher Issuu for known CDN gaps, with independent date and page-count checks.
3. Compare against complete SKU-linked `type=all` and `type=shopper` captures only when such archived snapshots actually exist. The official current pages and Wayback `available` lookups for Pueblo/Selectos/aggregator/SuperMax near 2026-07-20 yielded no verified historical complete catalog snapshot; do not label the flyers full catalog.

Read-only response logs are preserved in `docs/evidence/2026-10-17/{cdn-weekly-probes.json,cdn-monthly-probes.json,cdn-page-audit-20261017.json}`. These record the tested URLs/statuses and selected page sequences; they are not product/price transcriptions. This research did not alter production offers or the Pueblo paired-snapshot evaluator.

## Sources

[1] https://cdn.shoppersdepuertorico.com/shopper-pueblo-2026-07-08-pagina-01.jpg
[2] https://cdn.shoppersdepuertorico.com/shopper-pueblo-2026-10-14-pagina-01.jpg
[3] https://cdn.shoppersdepuertorico.com/shopper-amigo-2026-07-09-pagina-01.jpg
[4] https://cdn.shoppersdepuertorico.com/shopper-amigo-2026-10-15-pagina-01.jpg
[5] https://cdn.shoppersdepuertorico.com/shopper-econo-2026-07-09-pagina-01.jpg
[6] https://cdn.shoppersdepuertorico.com/shopper-econo-2026-10-15-pagina-01.jpg
[7] https://cdn.shoppersdepuertorico.com/shopper-selectos-2026-07-09-pagina-01.jpg
[8] https://cdn.shoppersdepuertorico.com/shopper-selectos-2026-10-15-pagina-01.jpg
[9] https://cdn.shoppersdepuertorico.com/shopper-ralphs-2026-07-10-pagina-01.jpg
[10] https://cdn.shoppersdepuertorico.com/shopper-ralphs-2026-10-16-pagina-01.jpg
[11] https://cdn.shoppersdepuertorico.com/shopper-supermax-2026-07-08-pagina-01.jpg
[12] https://cdn.shoppersdepuertorico.com/shopper-supermax-2026-10-14-pagina-01.jpg
[13] https://cdn.shoppersdepuertorico.com/shopper-mi-gente-2026-07-09-pagina-01.jpg
[14] https://cdn.shoppersdepuertorico.com/shopper-mi-gente-2026-10-15-pagina-01.jpg
[15] https://cdn.shoppersdepuertorico.com/shopper-mr-special-2026-07-02-pagina-01.jpg
[16] https://cdn.shoppersdepuertorico.com/shopper-mr-special-2026-10-08-pagina-01.jpg
[17] https://cdn.shoppersdepuertorico.com/shopper-agranel-2026-07-02-pagina-01.jpg
[18] https://cdn.shoppersdepuertorico.com/shopper-agranel-2026-10-08-pagina-01.jpg
[19] https://cdn.shoppersdepuertorico.com/shopper-freshmart-2026-07-01-pagina-01.jpg
[20] https://cdn.shoppersdepuertorico.com/shopper-freshmart-2026-10-01-pagina-01.jpg
[21] https://cdn.shoppersdepuertorico.com/shopper-walmart-2026-07-08-pagina-01.jpg
[22] https://cdn.shoppersdepuertorico.com/shopper-walmart-2026-09-30-pagina-01.jpg
[23] https://www.shoppersdepuertorico.com/pueblo
[24] https://www.shoppersdepuertorico.com/supermax
[25] https://www.shoppersdepuertorico.com/freshmart
[26] https://www.shoppersdepuertorico.com/walmart
[27] https://www.shoppersdepuertorico.com/mi-gente
[28] https://issuu.com/vocero.com/docs/amigo_v_lido_julio_30_-_agosto_05
[29] https://selectospr.com/shopper
[30] https://www.walmartpr.com/publicaciones
[31] http://ahorrosdiariosusandocupones.blogspot.com/2026/07/en-los-supermercados-pueblo-del-15-al.html
[32] https://web.archive.org/cdx/search/cdx?url=puebloweb.com%2Fcontrollers%2Fproducts.html%2A&output=json&filter=statuscode%3A200&fl=timestamp%2Coriginal%2Cmimetype%2Cstatuscode%2Clength&limit=20000
[33] https://web.archive.org/web/20240812005729id_/https://puebloweb.com/controllers/products.html?type=shopper&page=1&sort=&query=&category_id=
[34] https://web.archive.org/cdx/search/cdx?url=puebloweb.com%2F%2A&output=json&from=2026&to=2026&filter=statuscode%3A200&fl=timestamp%2Coriginal%2Cmimetype%2Cstatuscode%2Clength&limit=20000
[35] https://web.archive.org/web/20261006224246id_/https://www.puebloweb.com/shopper
[36] https://index.commoncrawl.org/CC-MAIN-2026-30-index?url=www.puebloweb.com%2Fcontrollers%2Fproducts.html%2A&output=json&filter=status%3A200 ; https://index.commoncrawl.org/CC-MAIN-2026-39-index?url=www.puebloweb.com%2Fcontrollers%2Fproducts.html%2A&output=json&filter=status%3A200 ; https://archive.ph/newest/https%3A%2F%2Fwww.puebloweb.com%2Fcontrollers%2Fproducts.html%3Ftype%3Dall%26page%3D1%26sort%3Dname%26query%3D%26category_id%3D
