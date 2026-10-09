# Historical Backfill Plan (up to 4+ weeks)

## Source
`cdn.shoppersdepuertorico.com` hosts dated shopper assets:
  - PDF:    `/shopper-{chain}-{YYYY-MM-DD}.pdf`
  - Images: `/shopper-{chain}-{YYYY-MM-DD}-pagina-{NN}.jpg`  (01-indexed, zero-padded)
Requires a `Referer: https://www.shoppersdepuertorico.com/` header (HEAD returns
403; GET works). These are the chains' official circulars re-hosted by the
aggregator — same content the chains publish.

## Verified availability (weeks back from 2026-10-08)
  econo        6   (weekly, Wednesdays)
  selectos     6
  amigo        6
  mr-special   4   (bi-weekly-ish)
  agranel      3
  mi-gente     3   (bi-weekly)
  walmart      1
  freshmart    1
  plaza-loiza  1
  pueblo       0   (structured, own site — no CDN copy)
  ralphs       0   (structured, own site)
  supermax     0   (own site PDF)

## Strategy per chain type
- structured (pueblo, amigo, ralphs): no historical endpoint; their own site only
  serves the current week. History accrues forward via the weekly timer.
  BUT amigo IS on the CDN (6 weeks) -> backfill amigo from CDN for history.
- CDN-covered (econo, selectos, amigo, mr-special, agranel, mi-gente, walmart,
  freshmart, plaza-loiza): backfill from dated CDN page images -> VL extraction.
- supermax: own-site PDF is current-only; history accrues forward.

## Validity windows
CDN filename date = week start (Wednesday). valid_from = that date,
valid_to = +6 days. mr-special/mi-gente run ~2 weeks -> valid_to = +13.

## Dedup with existing data
Offers are keyed (chain, product_norm, size_text, price_sale, valid_from).
Historical weeks have distinct valid_from, so no collision with current rows.

## Throughput note
Each week = 8-16 page images -> VL extraction. ~34 pages took ~3 min for Econo.
Backfilling ~25 chain-weeks (~250 pages) is a one-time ~25-40 min job, run as a
detached background process. New `backfill` scraper type + `backfill.py`
orchestrator (separate from run_weekly so it doesn't run on the weekly timer).

## Chain slug mapping (CDN name -> our slug)
  econo->econo  selectos->selectos  amigo->amigo  mr-special->mrspecial
  agranel->agranel  mi-gente->migente  walmart->walmart  freshmart->freshmart
  plaza-loiza->plazaloiza
