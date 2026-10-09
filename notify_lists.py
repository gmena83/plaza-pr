"""Send the Mi Lista digest (Monday + Thursday) to every opted-in user.

Usage:
  notify_lists.py                     send for the current slot (cron mode)
  notify_lists.py --dry-run           build everything, send nothing, log nothing
  notify_lists.py --preview DIR       write HTML/text per user into DIR, send nothing
  notify_lists.py --only EMAIL        restrict to one user (combine with the above)
  notify_lists.py --force             send even on a non-slot day / stale data / already sent
  notify_lists.py --test-to EMAIL     send the first user's digest to EMAIL (no logging)
  notify_lists.py --after-scrape      called by refresh.sh right after run_weekly

Env: DATABASE_URL, RESEND_API_KEY, RESEND_FROM (default PLAZA <milista@plazapr.menatech.dev>),
     PLAZA_API_BASE (unsubscribe links), PLAZA_REPLY_TO (default contact@menatech.dev),
     PLAZA_POSTAL_ADDRESS (footer, default 410 Francisco Sein, San Juan, PR 00917).

Scheduling: refresh.sh sends Thursday's digest right after the Thursday scrape;
pr-shopper-digest.timer sends Monday's and retries Thursday's later in the day
(no-op if already sent). A missed slot may be sent up to MAX_CATCHUP_DAYS late.

Safety rails:
  - email_log UNIQUE(user_id, kind, period) + Resend Idempotency-Key => one email
    per user per slot even when the scrape service is re-run.
  - opted-out (email_prefs.enabled = false) users are never emailed.
  - aborts the whole run (Telegram alert, exit 0) when the data isn't fresh:
    Thursday needs this week's scrape to have succeeded for most chains;
    every slot needs most chains to have current offers.
  - a timer run while the scrape is still running defers to refresh.sh.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from normalize import db, digest

log = logging.getLogger("pr-shopper.notify")

KIND = "list_digest"
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "PLAZA <milista@plazapr.menatech.dev>")
REPLY_TO = os.environ.get("PLAZA_REPLY_TO", "contact@menatech.dev")
API_BASE = os.environ.get("PLAZA_API_BASE", "https://plaza-pr-api.fly.dev").rstrip("/")
SITE = os.environ.get("PLAZA_SITE", "https://plaza-pr.netlify.app/app/")
FEEDBACK = ("https://docs.google.com/forms/d/e/"
            "1FAIpQLScl3O3hQQ9HNRN0GeubG6_0bbMXV6LM4Zmw4mHNF4SeQidnQg/viewform")
POSTAL = os.environ.get("PLAZA_POSTAL_ADDRESS", "410 Francisco Sein, San Juan, PR 00917")
MIN_FRESH_CHAINS = int(os.environ.get("PLAZA_MIN_FRESH_CHAINS", "6"))
MAX_CATCHUP_DAYS = 1
SEND_INTERVAL_S = 0.6            # Resend default limit is 2 requests/second


def telegram(msg: str) -> None:
    """Best-effort ops ping via the forja bot (same channel as scrape failures)."""
    env = Path.home() / ".hermes/profiles/forja/.env"
    try:
        kv = dict(line.split("=", 1) for line in env.read_text().splitlines()
                  if "=" in line and not line.lstrip().startswith("#"))
        token = kv.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = kv.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()
        if token and chat:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": msg}, timeout=15)
    except Exception as e:  # noqa: BLE001 - alerting must never break the run
        log.warning("telegram ping failed: %s", e)


def fresh_chains(c) -> int:
    r = c.execute("SELECT COUNT(DISTINCT chain_slug) n FROM offers "
                  "WHERE date('now') BETWEEN date(valid_from) AND date(valid_to)").fetchone()
    return r["n"]


def scraped_chains_since(c, since: dt.date) -> int:
    """Chains with a successful, non-empty scrape since `since` 00:00 PR time."""
    cutoff = dt.datetime.combine(since, dt.time(0), tzinfo=digest.PR_TZ).isoformat()
    r = c.execute("SELECT COUNT(DISTINCT chain_slug) n FROM scrape_runs "
                  "WHERE status = 'ok' AND offers_found > 0 AND started_at >= ?",
                  (cutoff,)).fetchone()
    return r["n"]


def freshness_problem(c, slot: dt.date) -> str | None:
    n = fresh_chains(c)
    if n < MIN_FRESH_CHAINS:
        return f"only {n} chains have current offers (min {MIN_FRESH_CHAINS})"
    if slot.weekday() == 3:   # Thursday promises "shoppers nuevos de esta semana"
        since = slot - dt.timedelta(days=1)
        s = scraped_chains_since(c, since)
        if s < MIN_FRESH_CHAINS:
            return (f"only {s} chains scraped OK since {since} (min {MIN_FRESH_CHAINS}); "
                    f"this week's circulars aren't in yet")
    return None


def scrape_running() -> bool:
    """Side-effect free check (never touches run_weekly's lock)."""
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "pr-shopper-scrape.service"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() in ("active", "activating")
    except Exception:  # noqa: BLE001
        return False


def recipients(c, only: str | None) -> list[dict]:
    """Users with a non-empty list who haven't opted out. Creates prefs rows
    (opt-in by default) for new users so each has an unsubscribe token."""
    c.execute("INSERT INTO email_prefs(user_id) SELECT DISTINCT l.user_id FROM lists l "
              "JOIN list_items i ON i.list_id = l.id ON CONFLICT (user_id) DO NOTHING")
    c.commit()
    sql = ("SELECT l.id AS list_id, l.user_id, u.email, p.unsub_token "
           "FROM lists l JOIN auth.users u ON u.id = l.user_id "
           "JOIN email_prefs p ON p.user_id = l.user_id "
           "WHERE p.enabled AND u.email IS NOT NULL AND u.deleted_at IS NULL "
           "AND u.email_confirmed_at IS NOT NULL "
           "AND EXISTS (SELECT 1 FROM list_items i WHERE i.list_id = l.id) ")
    params: list = []
    if only:
        sql += "AND lower(u.email) = lower(?) "
        params.append(only)
    sql += "ORDER BY l.id"
    rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    seen, out = set(), []
    for r in rows:                      # one digest per user (default list)
        if r["user_id"] not in seen:
            seen.add(r["user_id"])
            out.append(r)
    return out


def already_sent(c, user_id: str, slot: str) -> bool:
    return c.execute("SELECT 1 FROM email_log WHERE user_id = ? AND kind = ? AND period = ? "
                     "AND status = 'sent'", (user_id, KIND, slot)).fetchone() is not None


def record(c, user_id: str, slot: str, status: str, d: dict | None = None,
           resend_id: str | None = None, error: str | None = None) -> None:
    d = d or {}
    c.execute(
        "INSERT INTO email_log(user_id, kind, period, status, resend_id, subject, n_items, "
        "n_deals, summary, error) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (user_id, kind, period) DO UPDATE SET status = excluded.status, "
        "resend_id = excluded.resend_id, subject = excluded.subject, n_items = excluded.n_items, "
        "n_deals = excluded.n_deals, summary = excluded.summary, error = excluded.error, "
        "created_at = now()",
        (user_id, KIND, slot, status, resend_id, d.get("subject"), d.get("n_items"),
         d.get("n_deals"), json.dumps(d.get("summary") or {}), error))
    c.commit()


def send(to: str, d: dict, html: str, text: str, unsub_url: str,
         idem_key: str | None) -> tuple[bool, str]:
    if not RESEND_API_KEY:
        return False, "RESEND_API_KEY not set"
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    payload = {"from": RESEND_FROM, "to": [to], "subject": d["subject"],
               "html": html, "text": text,
               "headers": {"List-Unsubscribe": f"<{unsub_url}>",
                           "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
               "tags": [{"name": "kind", "value": KIND},
                        {"name": "slot", "value": d["slot"].replace("-", "")}]}
    if REPLY_TO:
        payload["reply_to"] = REPLY_TO
    err = "unknown error"
    for attempt in range(3):
        try:
            r = requests.post("https://api.resend.com/emails", headers=headers,
                              json=payload, timeout=20)
        except requests.RequestException as e:
            err = str(e)
        else:
            if r.status_code < 300:
                return True, r.json().get("id", "")
            err = f"{r.status_code} {r.text[:300]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                return False, err
        time.sleep(2 * (attempt + 1))
    return False, err


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview", metavar="DIR")
    ap.add_argument("--only", metavar="EMAIL")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--test-to", metavar="EMAIL")
    ap.add_argument("--after-scrape", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    today = digest.today_pr()
    slot = digest.slot_for(today)
    slot_s = slot.isoformat()
    real_send = not (a.dry_run or a.preview)
    cron = real_send and not a.test_to and not a.force
    if cron and (today - slot).days > MAX_CATCHUP_DAYS:
        log.info("today (%s) is not a digest day (lun/jue, +%dd catch-up); nothing to do",
                 today, MAX_CATCHUP_DAYS)
        return 0
    if cron and not a.after_scrape and scrape_running():
        log.info("scrape still running; refresh.sh will send the digest when it finishes")
        return 0

    c = db.connect(os.environ["DATABASE_URL"])
    problem = freshness_problem(c, slot)
    n_fresh = fresh_chains(c)
    if problem and not a.force:
        msg = (f"PLAZA digest SKIPPED for {slot_s}: {problem}. "
               f"Check the scrape, then re-run: systemctl --user start pr-shopper-digest.service")
        log.error(msg)
        if real_send:
            telegram(msg)
        return 0

    names = digest.chain_names(c)
    users = recipients(c, a.only)
    if a.test_to:
        users = users[:1]
    log.info("slot %s · %d recipient(s) · %d fresh chains · mode=%s", slot_s, len(users), n_fresh,
             "test" if a.test_to else "preview" if a.preview else "dry-run" if a.dry_run else "send")
    stats = {"sent": 0, "skipped": 0, "already": 0, "failed": 0}
    failures: list[str] = []

    for u in users:
        if real_send and not a.test_to and not a.force and already_sent(c, u["user_id"], slot_s):
            stats["already"] += 1
            continue
        try:
            d = digest.build_digest(c, u["list_id"], today=today, slot=slot, names=names)
        except Exception as e:  # noqa: BLE001 - one bad list must not stop the run
            c.rollback()
            log.exception("build failed for %s", u["email"])
            stats["failed"] += 1
            failures.append(f"{u['email']}: build {e}")
            continue
        if not d["send"]:
            stats["skipped"] += 1
            if real_send and not a.test_to:
                record(c, u["user_id"], slot_s, "skipped", d, error=d["reason"])
            continue

        unsub = f"{API_BASE}/u/{u['unsub_token']}"
        html, text = digest.render_digest(d, unsubscribe_url=unsub, site_url=SITE,
                                          feedback_url=FEEDBACK, postal_address=POSTAL,
                                          can_reply=bool(REPLY_TO))
        if a.preview:
            out = Path(a.preview)
            out.mkdir(parents=True, exist_ok=True)
            stem = u["email"].replace("@", "_at_")
            (out / f"{stem}.html").write_text(html)
            (out / f"{stem}.txt").write_text(text)
            log.info("preview %s -> %s.html (%s)", u["email"], out / stem, d["subject"])
            continue
        if a.dry_run:
            log.info("dry-run %s: %s", u["email"], d["subject"])
            continue

        to = a.test_to or u["email"]
        idem = None if a.test_to else f"{KIND}-{u['user_id']}-{slot_s}"
        if a.test_to:
            d = {**d, "subject": "[PRUEBA] " + d["subject"]}
        ok, info = send(to, d, html, text, unsub, idem)
        time.sleep(SEND_INTERVAL_S)
        if ok:
            stats["sent"] += 1
            log.info("sent %s -> %s (%s)", d["subject"], to, info)
            if not a.test_to:
                record(c, u["user_id"], slot_s, "sent", d, resend_id=info)
        else:
            stats["failed"] += 1
            failures.append(f"{to}: {info}")
            log.error("send failed %s: %s", to, info)
            if not a.test_to:
                record(c, u["user_id"], slot_s, "failed", d, error=info)

    log.info("done %s", stats)
    if real_send and not a.test_to and (stats["sent"] or stats["failed"]):
        line = (f"PLAZA digest {slot_s}: {stats['sent']} sent, {stats['skipped']} nothing-to-say, "
                f"{stats['already']} already sent, {stats['failed']} failed.")
        if failures:
            line += "\n" + "\n".join(failures[:5])
        telegram(line)
    return 1 if stats["failed"] and not stats["sent"] else 0


if __name__ == "__main__":
    sys.exit(main())
