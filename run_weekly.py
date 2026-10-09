"""Orchestrator: fetch all chains -> extract -> normalize -> upsert -> report.

Hardened:
  - Global file lock so a timer tick and a manual run never overlap.
  - Per-chain try/except already isolates failures; a locked run exits fast.
  - 'running' runs left behind by a killed process are swept to 'stale' on startup.
  - run_weekly is idempotent: offer upserts key on (chain, product_norm, size,
    price_sale, valid_from), so re-running the same week never duplicates.

Usage:
  python -m run_weekly                 # all configured chains
  python -m run_weekly pueblo amigo    # subset
"""
import argparse
import fcntl
import logging
import os
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from normalize import db
from scrapers import (browser_fetch, econo_fetch, image_fetch, pdf_fetch,
                      structured, validity)
from scrapers.common import ROOT, load_config
from scrapers.extract_vl import extract_images, extract_pdf

log = logging.getLogger("pr-shopper.run")

LOCK_PATH = ROOT / "data" / ".run_weekly.lock"


@contextmanager
def global_lock():
    """Exclusive non-blocking lock for the whole orchestrator run."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.seek(0)
        pid = fd.read().strip() or "unknown"
        print(f"Another run_weekly is in progress (pid {pid}); exiting.", file=sys.stderr)
        fd.close()
        sys.exit(3)
    fd.seek(0)
    fd.truncate()
    fd.write(str(os.getpid()))
    fd.flush()
    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            fd.close()


def run_chain(conn, cfg, slug: str) -> dict:
    chain = cfg["chains"][slug]
    source = chain.get("shopper_page", "")
    offers: list[dict] = []
    run_id = None
    try:
        ctype = chain["type"]
        if ctype == "structured":
            valid_from, valid_to = validity.detect(chain, slug, cfg)
            run_id = db.start_run(conn, slug, source, valid_from, valid_to)
            offers = structured.scrape(chain)
        elif ctype == "pdf":
            pdf_path = pdf_fetch.fetch_pdf(chain, slug)
            valid_from, valid_to = validity.detect(chain, slug, cfg, pdf_path)
            run_id = db.start_run(conn, slug, source, valid_from, valid_to)
            offers = extract_pdf(pdf_path, slug, cfg)
        elif ctype == "images":
            image_paths = image_fetch.fetch_images(chain, slug)
            valid_from, valid_to = validity.detect(
                chain, slug, cfg, image_path=image_paths[0] if image_paths else None)
            run_id = db.start_run(conn, slug, source, valid_from, valid_to)
            offers = extract_images(image_paths, slug, cfg)
        elif ctype == "browser":
            image_paths = browser_fetch.fetch_shopper_images(chain, slug)
            valid_from, valid_to = validity.detect(
                chain, slug, cfg, image_path=image_paths[0] if image_paths else None)
            run_id = db.start_run(conn, slug, source, valid_from, valid_to)
            offers = extract_images(image_paths, slug, cfg)
        elif ctype == "browser_interactive":
            image_paths = econo_fetch.fetch_shopper_images(chain, slug)
            valid_from, valid_to = validity.detect(
                chain, slug, cfg, image_path=image_paths[0] if image_paths else None)
            run_id = db.start_run(conn, slug, source, valid_from, valid_to)
            offers = extract_images(image_paths, slug, cfg)
        else:
            raise ValueError(f"unknown chain type {ctype}")

        n = db.upsert_offers(conn, run_id, slug, offers, valid_from, valid_to)
        if ctype in ("browser", "browser_interactive", "images", "pdf"):
            db.dedup_offers(conn, slug, valid_from)
        db.finish_run(conn, run_id, "ok", n)
        log.info("[%s] DONE: %d offers upserted (%s -> %s)", slug, n, valid_from, valid_to)
        return {"chain": slug, "status": "ok", "offers": n,
                "valid_from": valid_from, "valid_to": valid_to}
    except Exception as e:  # noqa: BLE001
        log.exception("[%s] FAILED", slug)
        if run_id is not None:
            db.finish_run(conn, run_id, "error", 0, str(e))
        return {"chain": slug, "status": "error", "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chains", nargs="*", help="chain slugs (default: all)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    with global_lock():
        cfg = load_config()
        conn = db.connect(db.dsn_from_env(cfg))
        db.init_db(conn)
        db.sweep_stale_runs(conn)
        for slug, c in cfg["chains"].items():
            db.ensure_chain(conn, slug, c["name"])

        all_slugs = [s for s, c in cfg["chains"].items() if c.get("enabled", True)]
        targets = args.chains or all_slugs
        results = [run_chain(conn, cfg, slug) for slug in targets]
        conn.close()

    print("\n==== RUN SUMMARY ====")
    for r in results:
        print(r)
    # non-zero exit if any chain failed, so systemd/cron marks the run
    if any(r["status"] != "ok" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
