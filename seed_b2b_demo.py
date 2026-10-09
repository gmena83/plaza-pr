"""Seed the events table with 8 weeks of plausible synthetic user activity.

For the B2B demo dashboard (/negocios) until real users generate real events.
Cohorts are fake ids; no real user data involved. Idempotent: deletes prior
synthetic rows before inserting a fresh 8-week window.

Usage: DATABASE_URL=... .venv/bin/python seed_b2b_demo.py
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

from normalize import db

random.seed(42)

COHORTS = [f"demo-{i:03d}" for i in range(1, 121)]  # 120 synthetic users
# realistic PR shopping search weights
TOP_PRODUCTS = [
    ("arroz", 0.14), ("leche", 0.10), ("pollo", 0.10), ("huevos", 0.08),
    ("habichuelas", 0.07), ("aceite", 0.06), ("café", 0.06), ("pan", 0.05),
    ("cerveza corona", 0.05), ("papel toalla", 0.04), ("detergente", 0.04),
    ("chuleta", 0.04), ("pasta", 0.04), ("atún", 0.04), ("jugo de naranja", 0.03),
    ("queso cheddar", 0.03), ("yogurt", 0.02), ("mantequilla", 0.02),
]
BRANDS = ["Goya", "Coco López", "Tres Monjitas", "Suiza", "Borden", "Maggi",
          "Bustelo", "Yaucono", "Corona", "Medalla", "Charmin", "Dawn",
          "Tide", "Raeford", "Pilgrim's", "Great Value"]
CHAINS = ["pueblo", "amigo", "econo", "ralphs", "selectos", "supermax",
          "mrspecial", "migente", "freshmart", "agranel", "walmart"]
# campaign: a brand pushes heavy ads some weeks -> search/list_add lift
CAMPAIGNS = [
    {"brand": "Goya", "weeks": {2, 3}, "lift": 2.2},
    {"brand": "Tres Monjitas", "weeks": {5}, "lift": 2.8},
    {"brand": "Corona", "weeks": {6, 7}, "lift": 1.9},
]


def weighted_product() -> str:
    r = random.random()
    acc = 0.0
    for p, w in TOP_PRODUCTS:
        acc += w
        if r <= acc:
            return p
    return TOP_PRODUCTS[-1][0]


def brand_for(product: str, week_idx: int) -> str:
    for camp in CAMPAIGNS:
        if week_idx in camp["weeks"] and random.random() < 0.35:
            return camp["brand"]
    if "café" in product:
        return random.choice(["Bustelo", "Yaucono"])
    if "corona" in product:
        return "Corona"
    if "leche" in product:
        return random.choice(["Tres Monjitas", "Suiza"])
    return random.choice(BRANDS)


def main() -> None:
    c = db.connect(os.environ["DATABASE_URL"])
    c.execute("DELETE FROM events WHERE user_cohort LIKE 'demo-%'")
    c.commit()

    now = datetime.now(timezone.utc)
    rows = []
    for cohort in COHORTS:
        # each synthetic user active on 3-10 random days over 8 weeks
        active_days = random.sample(range(56), k=random.randint(3, 10))
        for d in active_days:
            week_idx = d // 7
            ts = now - timedelta(days=d, hours=random.randint(0, 14),
                                 minutes=random.randint(0, 59))
            n_events = random.randint(1, 6)
            for _ in range(n_events):
                kind = random.choices(
                    ["search", "list_add", "basket_view", "offer_click"],
                    weights=[0.45, 0.25, 0.15, 0.15])[0]
                product = weighted_product() if kind != "basket_view" else None
                brand = brand_for(product, week_idx) if product else None
                chain = random.choice(CHAINS) if kind in ("offer_click", "basket_view") else None
                rows.append((ts.isoformat(), kind, cohort, product, chain, brand,
                             json.dumps({})))
    # batch insert
    import psycopg2.extras
    cur = c._conn.cursor() if hasattr(c, "_conn") else None
    if cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO events(ts, kind, user_cohort, product_norm, chain_slug, brand, meta) "
            "VALUES %s", rows, page_size=500)
        c.commit()
    else:  # sqlite fallback
        for r in rows:
            c.execute(
                "INSERT INTO events(ts, kind, user_cohort, product_norm, chain_slug, brand, meta) "
                "VALUES(?,?,?,?,?,?,?)", r)
        c.commit()
    n = db.connect(os.environ["DATABASE_URL"]).execute("SELECT COUNT(*) c FROM events").fetchone()
    print(f"seeded {len(rows)} synthetic events (total in table: {n['c']})")


if __name__ == "__main__":
    main()
