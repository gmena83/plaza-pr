"""Post-scrape digest: email each user the best offers on their list + basket verdict.

Run after run_weekly (same env: DATABASE_URL, RESEND_API_KEY, RESEND_FROM).
Only emails users whose list has at least one item with a current offer;
one digest per scrape day (jue/dom).
"""
import logging
import os

import requests

from normalize import basket, db

log = logging.getLogger("pr-shopper.notify")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "PLAZA <alertas@plaza-pr.menatech.dev>")
SITE = "https://plaza-pr.netlify.app/app/"


def _dsn() -> str:
    return os.environ["DATABASE_URL"]


def send(email: str, subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY not set; would email %s: %s", email, subject)
        return False
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={"from": RESEND_FROM, "to": [email], "subject": subject, "html": html},
        timeout=20)
    if r.status_code >= 300:
        log.error("resend %s -> %s: %s", r.status_code, email, r.text[:200])
        return False
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    c = db.connect(_dsn())
    # every list with items
    lists = c.execute(
        "SELECT l.id, l.user_id, COUNT(i.id) n "
        "FROM lists l JOIN list_items i ON i.list_id = l.id "
        "GROUP BY l.id, l.user_id").fetchall()
    if not lists:
        log.info("no user lists; nothing to send")
        return

    # resolve emails from auth.users via the service-role API
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    supa = os.environ.get("SUPABASE_URL", "https://blluhfmfslxpmacnqkox.supabase.co")
    sent = 0
    for lst in lists:
        uid = lst["user_id"]
        r = requests.get(f"{supa}/auth/v1/admin/users/{uid}",
                         headers={"apikey": service_key,
                                  "Authorization": f"Bearer {service_key}"}, timeout=15)
        if r.status_code != 200:
            log.warning("no email for user %s", uid)
            continue
        email = r.json().get("email")
        if not email:
            continue

        items = basket.list_items(c, lst["id"])
        result = basket.optimize(c, items)
        deals = [it for it in result["items"] if it["best"]]
        if not deals:
            continue

        rows = "".join(
            f"<tr><td style='padding:6px 12px'>{it['display_name'] or it['product_norm']}</td>"
            f"<td style='padding:6px 12px'><b>${it['best']['price_sale']:.2f}</b></td>"
            f"<td style='padding:6px 12px'>{it['best']['chain_slug']}</td>"
            f"<td style='padding:6px 12px'>"
            + (f"{it['best']['unit_price']:.3f} {it['best']['price_basis']}"
               if it["best"]["unit_price"] else "—")
            + "</td></tr>"
            for it in deals)
        verdict = result.get("verdict")
        verdict_html = (f"<p style='background:#fff8e1;border-left:4px solid #ffd400;"
                        f"padding:12px 16px'><b>Canasta de la semana:</b> {verdict['message']}</p>"
                        if verdict else "")
        html = (f"<div style='font-family:monospace;max-width:640px'>"
                f"<h2>PLAZA — tu lista esta semana</h2>{verdict_html}"
                f"<table style='border-collapse:collapse;font-size:14px'>"
                f"<tr><th align='left'>producto</th><th>precio</th><th>cadena</th><th>$/unidad</th></tr>"
                f"{rows}</table>"
                f"<p><a href='{SITE}'>Abrir mi lista en PLAZA</a></p>"
                f"<p style='color:#888;font-size:12px'>Datos de shoppers públicos · "
                f"actualización jue/dom</p></div>")
        if send(email, f"PLAZA: {len(deals)} ofertas en tu lista esta semana", html):
            sent += 1
            log.info("sent digest to %s (%d deals)", email, len(deals))
    log.info("done: %d digest(s) sent", sent)


if __name__ == "__main__":
    main()
