"""Backfill historical shoppers from the CDN into the DB.

Separate from run_weekly: this is a one-time / on-demand job, not part of the
weekly timer. For each CDN-covered chain and each available past week, download
the page images, run VL extraction, and upsert with that week's validity window.

Usage:
  python -m backfill                 # all CDN chains, all available weeks (<=6)
  python -m backfill econo selectos  # subset of chains
  python -m backfill --weeks 4       # limit weeks back
"""
import argparse
import logging
from datetime import date, timedelta

from normalize import db
from scrapers import cdn_fetch
from scrapers.common import ROOT, load_config
from scrapers.extract_vl import extract_images

log = logging.getLogger("pr-shopper.backfill")

# CDN chain name -> (our slug, week_length_days)
CDN_CHAINS = {
    "econo": ("econo", 7),
    "selectos": ("selectos", 7),
    "amigo": ("amigo", 7),
    "mr-special": ("mrspecial", 14),
    "agranel": ("agranel", 7),
    "mi-gente": ("migente", 14),
    "walmart": ("walmart", 28),
    "freshmart": ("freshmart", 30),
    "plaza-loiza": ("plazaloiza", 7),
}
# our slugs that must also exist in chains table
NAMES = {
    "econo": "Supermercados Econo", "selectos": "Supermercados Selectos",
    "amigo": "Supermercados Amigo", "mrspecial": "Mr. Special",
    "agranel": "Supermercados Agranel", "migente": "Supermercados Mi Gente",
    "walmart": "Walmart Puerto Rico", "freshmart": "Freshmart",
    "plazaloiza": "Supermercados Plaza Loíza",
}


def candidate_weeks(n: int) -> list[str]:
    """Wednesdays going back n weeks from the most recent one."""
    today = date.today()
    # CDN weeks start Thursday (verified: 2026-10-08, 10-01, 09-24 are Thursdays)
    offset = (today.weekday() - 3) % 7
    last_thu = today - timedelta(days=offset)
    return [(last_thu - timedelta(weeks=i)).isoformat() for i in range(n)]


def backfill_chain_week(conn, cfg, cdn_chain: str, slug: str, week: str,
                        week_len: int) -> dict:
    source = f"cdn:{cdn_chain}/{week}"
    vf = week
    vt = (date.fromisoformat(week) + timedelta(days=week_len - 1)).isoformat()
    run_id = db.start_run(conn, slug, source, vf, vt)
    try:
        out_dir = ROOT / "data" / "pages" / f"{slug}_{week}"
        images = cdn_fetch.fetch_week(cdn_chain, week, out_dir)
        offers = extract_images(images, slug, cfg)
        n = db.upsert_offers(conn, run_id, slug, offers, vf, vt)
        db.dedup_offers(conn, slug, vf)
        db.finish_run(conn, run_id, "ok", n)
        log.info("[%s %s] %d offers", slug, week, n)
        return {"chain": slug, "week": week, "offers": n, "status": "ok"}
    except Exception as e:  # noqa: BLE001
        log.exception("[%s %s] failed", slug, week)
        db.finish_run(conn, run_id, "error", 0, str(e))
        return {"chain": slug, "week": week, "status": "error", "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chains", nargs="*", help="cdn chain names (default: all)")
    ap.add_argument("--weeks", type=int, default=4, help="weeks back (default 4)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    db.init_db(conn)
    for slug, name in NAMES.items():
        db.ensure_chain(conn, slug, name)

    weeks = candidate_weeks(args.weeks)
    targets = args.chains or list(CDN_CHAINS.keys())
    results = []
    for cdn_chain in targets:
        slug, week_len = CDN_CHAINS[cdn_chain]
        for week in weeks:
            # skip the current week for chains the weekly timer already owns
            if cdn_fetch.week_exists(cdn_chain, week):
                results.append(
                    backfill_chain_week(conn, cfg, cdn_chain, slug, week, week_len))
            else:
                log.info("[%s %s] not on CDN, skip", cdn_chain, week)
    conn.close()

    print("\n==== BACKFILL SUMMARY ====")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"{ok}/{len(results)} chain-weeks ok")
    for r in results:
        if r["status"] != "ok":
            print("  FAIL:", r)


if __name__ == "__main__":
    main()
