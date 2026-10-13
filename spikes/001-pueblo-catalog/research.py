"""Read-only paired-snapshot collection for the PLAZA prediction study."""
from __future__ import annotations

import argparse
import fcntl
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from followup import (BASE, BASELINE_CATALOG, BASELINE_EDITION,
                      BASELINE_SHOPPER, ROOT, complete, current_edition, run_probe)


def previous_pair(base: Path, edition: str, baseline_edition: str,
                  baseline_catalog: Path, baseline_shopper: Path) -> tuple[str, Path, Path]:
    """Select the newest older *fully compared* pair, not an interrupted crawl."""
    if not complete(baseline_catalog, "all") or not complete(baseline_shopper, "shopper"):
        raise ValueError("incomplete original Pueblo baseline")
    previous = (baseline_edition, baseline_catalog, baseline_shopper)
    for catalog in sorted(base.glob("pueblo-[0-9]*")):
        match = re.fullmatch(r"pueblo-(\d{8})", catalog.name)
        if not match:
            continue
        key = match[1]
        observed = date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:]}").isoformat()
        shopper = base / f"pueblo-shopper-{key}"
        if (baseline_edition < observed < edition and
                (catalog / "week_compare.json").exists() and
                complete(catalog, "all") and complete(shopper, "shopper")):
            previous = (observed, catalog, shopper)
    return previous


def run_once(base: Path, baseline_edition: str, baseline_catalog: Path,
             baseline_shopper: Path) -> Path | None:
    """Check the printed shopper edition; leave baseline-week data untouched."""
    edition = current_edition()
    print(f"Pueblo live edition={edition}; study baseline={baseline_edition}", flush=True)
    if edition <= baseline_edition:
        print("No new shopper edition; no capture.", flush=True)
        return None
    if date.fromisoformat(edition) > date.today():
        raise ValueError("shopper edition starts in the future; refusing capture")
    key = edition.replace("-", "")
    catalog = base / f"pueblo-{key}"
    shopper = base / f"pueblo-shopper-{key}"
    report = catalog / "week_compare.json"
    base.mkdir(parents=True, exist_ok=True)
    # Share the one-off follow-up's lock so manually triggered and timed captures
    # cannot write to the same resumable page cache at once.
    with (base / ".pueblo-followup.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Pueblo pilot is running; no capture.", flush=True)
            return None
        if report.exists():
            if not complete(catalog, "all") or not complete(shopper, "shopper"):
                raise ValueError(f"comparison exists but paired snapshots are incomplete: {report}")
            print(f"Already captured and compared: {report}", flush=True)
            return report
        prior_edition, old_catalog, old_shopper = previous_pair(
            base, edition, baseline_edition, baseline_catalog, baseline_shopper)
        print(f"Comparing new edition {edition} with prior complete edition {prior_edition}", flush=True)
        if not complete(shopper, "shopper"):
            run_probe(shopper, "shopper", 100)
        if not complete(catalog, "all"):
            run_probe(catalog, "all", 1800)
        if current_edition() != edition:
            raise RuntimeError("Shopper edition changed during capture; comparison withheld")
        cmd = [sys.executable, str(Path(__file__).with_name("compare.py")),
               "--old-catalog", str(old_catalog), "--old-shopper", str(old_shopper),
               "--new-catalog", str(catalog), "--new-shopper", str(shopper),
               "--out", str(report)]
        subprocess.run(cmd, cwd=ROOT, check=True)
        if not report.exists():
            raise RuntimeError("comparison command did not write a report")
        print(f"Prediction study observation saved: {report}", flush=True)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only check live edition; no capture")
    args = parser.parse_args()
    if args.check:
        print(f"Pueblo live edition={current_edition()}; study baseline={BASELINE_EDITION}")
        return
    run_once(BASE, BASELINE_EDITION, BASELINE_CATALOG, BASELINE_SHOPPER)


if __name__ == "__main__":
    main()
