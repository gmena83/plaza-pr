"""One-off next-edition read-only Pueblo catalog/shopper follow-up.

Run with --check to verify the current shopper without changing anything. The
systemd timer invokes the default run on two dates; successful work is skipped
on a retry, while interrupted page caches resume within the same edition key.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scrapers.validity import _spanish_range  # noqa: E402

BASELINE_EDITION = "2026-10-07"
BASELINE_CATALOG = ROOT / "data/catalog-pilots/pueblo-20261013"
BASELINE_SHOPPER = ROOT / "data/catalog-pilots/pueblo-shopper-20261013"
BASE = ROOT / "data/catalog-pilots"
SHOPPER_URL = "https://www.puebloweb.com/shopper"


def edition_date(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    headings = " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h3"))
    dates = _spanish_range(headings)
    if not dates:
        raise ValueError("Pueblo shopper heading has no parseable printed validity")
    return dates[0]


def is_new_edition(value: str) -> bool:
    return date.fromisoformat(value) > date.fromisoformat(BASELINE_EDITION)


def current_edition() -> str:
    s = requests.Session()
    s.headers["User-Agent"] = "PLAZA-catalog-feasibility/1.0 (+https://plaza-pr.netlify.app)"
    for attempt in range(3):
        try:
            response = s.get(SHOPPER_URL, timeout=25)
            response.raise_for_status()
            return edition_date(response.text)
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def complete(directory: Path, mode: str) -> bool:
    manifest = directory / "manifest.json"
    if not manifest.exists():
        return False
    data = json.loads(manifest.read_text())
    return bool(data.get("complete") and data.get("mode") == f"type={mode}")


def run_probe(out: Path, mode: str, max_pages: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).with_name("probe.py")),
           "--type", mode, "--out", str(out), "--max-pages", str(max_pages),
           "--interval", "1.25"]
    log_path = out / "capture.log"
    print(f"Starting {mode} capture; progress log {log_path}", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        completed = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=9600, check=False)
    if completed.returncode or not complete(out, mode):
        raise RuntimeError(f"{mode} capture incomplete (exit {completed.returncode}): {log_path}")


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--check", action="store_true", help="only print the live edition")
    options = args.parse_args()
    edition = current_edition()
    print(f"Pueblo live edition={edition}; pilot baseline={BASELINE_EDITION}", flush=True)
    if options.check:
        return
    if not is_new_edition(edition):
        print("No shopper change yet; nothing fetched. The fallback timer will retry.", flush=True)
        return
    if date.fromisoformat(edition) > date.today():
        raise ValueError("shopper edition starts in the future; refusing capture")
    key = edition.replace("-", "")
    catalog = BASE / f"pueblo-{key}"
    shopper = BASE / f"pueblo-shopper-{key}"
    report = catalog / "week_compare.json"
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE / ".pueblo-followup.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Pueblo follow-up is running; skipped.", flush=True)
            return
        if report.exists():
            print(f"Already compared this edition: {report}", flush=True)
            return
        if not complete(shopper, "shopper"):
            run_probe(shopper, "shopper", 100)
        if not complete(catalog, "all"):
            run_probe(catalog, "all", 1800)
        if current_edition() != edition:
            raise RuntimeError("Shopper edition changed during capture; report withheld")
        cmd = [sys.executable, str(Path(__file__).with_name("compare.py")),
               "--old-catalog", str(BASELINE_CATALOG),
               "--old-shopper", str(BASELINE_SHOPPER),
               "--new-catalog", str(catalog), "--new-shopper", str(shopper),
               "--out", str(report)]
        subprocess.run(cmd, cwd=ROOT, check=True)
        if not report.exists():
            raise RuntimeError("comparison did not write a report")
        print(f"Follow-up complete: {report}", flush=True)


if __name__ == "__main__":
    main()
