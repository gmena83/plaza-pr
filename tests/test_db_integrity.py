"""Offer integrity regressions. Postgres runs only with an explicit loopback test DSN."""
import os
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from normalize import db

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "draft_offer_identity_pg.sql"


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    if request.param == "sqlite":
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        db.ensure_chain(conn, "testchain", "Test Chain")
        try:
            yield conn
        finally:
            conn.close()
        return

    dsn = os.environ.get("PLAZA_TEST_PG_DSN")
    if not dsn:
        pytest.skip("isolated PLAZA_TEST_PG_DSN not set")
    parsed = urlsplit(dsn)
    if parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
        pytest.fail("PLAZA_TEST_PG_DSN must point to an explicit loopback port")
    schema = "test_ingest_" + uuid.uuid4().hex
    conn = db.connect(dsn)
    try:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        db.init_db(conn)
        db.ensure_chain(conn, "testchain", "Test Chain")
        yield conn
    finally:
        conn.rollback()
        conn.execute('SET search_path TO public')
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        conn.commit()
        conn.close()


def offer(raw, norm, size: str | None = "1 lb", price: float | str | None = 1.99, **extra):
    return {"product_raw": raw, "product_norm": norm, "size_text": size,
            "price_sale": price, "brand": "Marca", **extra}


@pytest.mark.parametrize("variant", [
    {"brand": "Otra"}, {"sku": "stock-2"}, {"promo": "2x1"},
])
def test_legacy_unique_collision_fails_closed_without_losing_variant(store, variant):
    first = offer("Arroz", "arroz", sku="stock-1", promo="regular")
    run1 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, run1, "testchain", [first],
                            "2025-01-01", "2025-01-07") == 1
    db.finish_run(store, run1, "ok", 1)
    run2 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    with pytest.raises(RuntimeError, match="identity collision"):
        db.upsert_offers(store, run2, "testchain", [first | variant],
                         "2025-01-01", "2025-01-07")
    db.finish_run(store, run2, "error", 0, "identity collision")
    assert [(r["status"], r["offers_found"]) for r in store.execute(
        "SELECT status, offers_found FROM scrape_runs ORDER BY id").fetchall()] == [
            ("ok", 1), ("error", 0)]
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 1


def test_concurrent_legacy_writers_do_not_publish_silent_variant_loss(store):
    if isinstance(store, sqlite3.Connection):
        pytest.skip("concurrent legacy writers require isolated Postgres")
    schema = store.execute("SELECT current_schema() AS name").fetchone()["name"]
    peer = db.connect(os.environ["PLAZA_TEST_PG_DSN"])
    try:
        peer.execute(f'SET search_path TO "{schema}"')
        runs = [db.start_run(conn, "testchain", "test", "2025-01-01",
                             "2025-01-07") for conn in (store, peer)]
        barrier = threading.Barrier(2)

        def write(conn, run_id, brand):
            original = conn.execute

            def synchronized_execute(sql, params=None):
                # Both full prechecks have passed when this savepoint begins.
                if sql.strip() == "SAVEPOINT offer_batch":
                    barrier.wait(timeout=10)
                return original(sql, params)

            conn.execute = synchronized_execute
            try:
                try:
                    count = db.upsert_offers(conn, run_id, "testchain",
                                             [offer("Arroz", "arroz", brand=brand)],
                                             "2025-01-01", "2025-01-07")
                except db.OfferIdentityConflict as exc:
                    db.finish_run(conn, run_id, "error", 0, str(exc))
                    return "error", 0, brand
                db.finish_run(conn, run_id, "ok", count)
                return "ok", count, brand
            finally:
                conn.execute = original

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, conn, run, brand) for conn, run, brand in
                       zip((store, peer), runs, ("Marca Roja", "Marca Azul"))]
            results = [future.result(timeout=20) for future in futures]

        assert sorted((status, count) for status, count, _ in results) == [
            ("error", 0), ("ok", 1)]
        winner = next(brand for status, _, brand in results if status == "ok")
        assert [tuple(r[k] for k in ("brand", "run_id")) for r in store.execute(
            "SELECT brand, run_id FROM offers").fetchall()] == [
                (winner, runs[("Marca Roja", "Marca Azul").index(winner)])]
        assert sorted((r["status"], r["offers_found"]) for r in store.execute(
            "SELECT status, offers_found FROM scrape_runs").fetchall()) == [
                ("error", 0), ("ok", 1)]
    finally:
        peer.close()


def test_draft_migration_retains_variants_and_stabilizes_nullable_replay(store):
    if isinstance(store, sqlite3.Connection):
        pytest.skip("Postgres-only migration draft")
    store.commit()
    store.executescript(MIGRATION.read_text())
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    variants = [offer("Arroz", "arroz", sku="stock-1", promo="regular"),
                offer("Arroz", "arroz", sku="stock-2", promo="regular"),
                offer("Arroz", "arroz", sku="stock-1", promo="2x1"),
                offer("Arroz", "arroz", sku="stock-1", brand="Otra", promo="regular")]
    assert db.upsert_offers(store, run, "testchain", variants,
                            "2025-01-01", "2025-01-07") == 4
    db.finish_run(store, run, "ok", 4)
    missing = offer("Leche", "leche", size=None, page=1, source_url="first")
    replay = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, replay, "testchain", [missing],
                            "2025-01-01", "2025-01-07") == 1
    db.finish_run(store, replay, "ok", 1)
    replay2 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, replay2, "testchain", [
        missing | {"page": 2, "source_url": "second"}],
        "2025-01-01", "2025-01-07") == 0
    db.finish_run(store, replay2, "ok", 0)
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 5


def test_migrated_store_refuses_legacy_null_sku_replay_without_audit(store):
    if isinstance(store, sqlite3.Connection):
        pytest.skip("Postgres-only migration draft")
    store.commit()
    store.executescript(MIGRATION.read_text())
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    store.execute("""INSERT INTO offers(run_id,chain_slug,product_raw,product_norm,
                   sku,brand,size_text,price_sale,valid_from,valid_to)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (run, "testchain", "Arroz", "arroz", None, "Marca",
                   "1 lb", 1.99, "2025-01-01", "2025-01-07"))
    db.finish_run(store, run, "ok", 1)
    replay = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    with pytest.raises(RuntimeError, match="identity collision"):
        db.upsert_offers(store, replay, "testchain", [offer("Arroz", "arroz")],
                         "2025-01-01", "2025-01-07")
    db.finish_run(store, replay, "error", 0, "legacy null SKU")
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 1


def test_draft_migration_aborts_atomically_on_existing_nullable_duplicates(store):
    if isinstance(store, sqlite3.Connection):
        pytest.skip("Postgres-only migration draft")
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    # Legacy nullable uniqueness permits two rows with identical stable identity.
    store.execute("""INSERT INTO offers(run_id,chain_slug,product_raw,product_norm,
                   size_text,price_sale,valid_from,valid_to)
                   VALUES(?,?,?,?,?,?,?,?)""",
                  (run, "testchain", "Arroz", "arroz", None, 1.99,
                   "2025-01-01", "2025-01-07"))
    store.execute("""INSERT INTO offers(run_id,chain_slug,product_raw,product_norm,
                   size_text,price_sale,valid_from,valid_to)
                   VALUES(?,?,?,?,?,?,?,?)""",
                  (run, "testchain", "Arroz", "arroz", None, 1.99,
                   "2025-01-01", "2025-01-07"))
    store.commit()
    with pytest.raises(Exception, match="audit failed"):
        store.executescript(MIGRATION.read_text())
    store.rollback()
    assert store.execute("""SELECT 1 FROM pg_constraint WHERE conrelid='offers'::regclass
                            AND conname='offers_chain_slug_product_norm_size_text_price_sale_valid_f_key'""").fetchone()
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 2


def test_failed_batch_rolls_back_valid_rows_and_marks_error(store):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    with pytest.raises(Exception):
        db.upsert_offers(store, run, "testchain", [
            offer("Arroz", "arroz"), offer(None, "rejected"), offer("Leche", "leche")
        ], "2025-01-01", "2025-01-07")
    db.finish_run(store, run, "error", 0, "rejected offer")
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 0
    assert store.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 0
    assert [(r["status"], r["offers_found"]) for r in store.execute(
        "SELECT status, offers_found FROM scrape_runs").fetchall()] == [("error", 0)]


def test_weekly_run_rejects_partial_capture_without_publishing(store, monkeypatch):
    import run_weekly

    cfg = {"chains": {"testchain": {"type": "structured", "shopper_page": "test"}}}
    monkeypatch.setattr(run_weekly.validity, "detect", lambda *args: (
        "2025-01-01", "2025-01-07"))
    monkeypatch.setattr(run_weekly.structured, "scrape", lambda *args: [
        offer("Arroz", "arroz"), offer(None, "rejected"), offer("Leche", "leche")])
    result = run_weekly.run_chain(store, cfg, "testchain")
    assert result["status"] == "error"
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 0
    assert store.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 0
    assert [(r["status"], r["offers_found"]) for r in store.execute(
        "SELECT status, offers_found FROM scrape_runs").fetchall()] == [("error", 0)]


def test_every_rejected_offer_does_not_complete_empty_run(store):
    # A persistent constraint failure used to be downgraded to an empty ok run.
    if isinstance(store, sqlite3.Connection):
        store.execute("""CREATE TRIGGER reject_offers BEFORE INSERT ON offers
                         BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END""")
    else:
        store.execute("""CREATE FUNCTION reject_offer() RETURNS trigger LANGUAGE plpgsql AS $$
                         BEGIN RAISE EXCEPTION 'storage unavailable' USING ERRCODE='23514'; END $$""")
        store.execute("""CREATE TRIGGER reject_offers BEFORE INSERT ON offers
                         FOR EACH ROW EXECUTE FUNCTION reject_offer()""")
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    with pytest.raises(Exception, match="storage unavailable|all offers rejected"):
        db.upsert_offers(store, run, "testchain", [offer("Arroz", "arroz")],
                         "2025-01-01", "2025-01-07")
    db.finish_run(store, run, "error", 0, "storage unavailable")
    assert store.execute("SELECT status FROM scrape_runs WHERE id=?", (run,)).fetchone()["status"] == "error"


def test_unparseable_offer_fails_run_not_empty_success(store):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    with pytest.raises(TypeError, match="unsupported operand"):
        db.upsert_offers(store, run, "testchain", [offer("Arroz", "arroz", price="bad")],
                         "2025-01-01", "2025-01-07")
    db.finish_run(store, run, "error", 0, "bad input")
    assert store.execute("SELECT status FROM scrape_runs WHERE id=?", (run,)).fetchone()["status"] == "error"


def test_dedup_never_deletes_an_older_completed_run(store):
    first = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    db.upsert_offers(store, first, "testchain", [
        offer("Arroz", "arroz", "1 lb")], "2025-01-01", "2025-01-07")
    db.finish_run(store, first, "ok", 1)
    second = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    db.upsert_offers(store, second, "testchain", [
        offer("Arroz", "arroz", "1 LB")], "2025-01-01", "2025-01-07")
    db.dedup_offers(store, "testchain", "2025-01-01", run_id=second)
    db.finish_run(store, second, "ok", 1)
    assert store.execute("SELECT COUNT(*) AS n FROM offers WHERE run_id=?",
                         (first,)).fetchone()["n"] == 1
    assert store.execute("SELECT offers_found FROM scrape_runs WHERE id=?",
                         (first,)).fetchone()["offers_found"] == 1


def test_dedup_preserves_different_packs_and_brands(store):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    entries = [offer("Arroz 1 lb", "arroz", "1 lb"),
               offer("Arroz 2 lb", "arroz", "2 lb"),
               offer("Arroz otra marca", "arroz", "1 LB", brand="Otra")]
    db.upsert_offers(store, run, "testchain", entries, "2025-01-01", "2025-01-07")
    removed = db.dedup_offers(store, "testchain", "2025-01-01")
    assert removed == 0
    assert [(r["size_canonical"], r["brand"]) for r in store.execute(
        "SELECT size_canonical, brand FROM offers ORDER BY id").fetchall()] == [
            ("1lb", "Marca"), ("2lb", "Marca"), ("1lb", "Otra")]


def test_dedup_preserves_distinct_promotions(store):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    db.upsert_offers(store, run, "testchain", [
        offer("Arroz sencillo", "arroz", "1 lb", promo="regular"),
        offer("Arroz dos por uno", "arroz", "1 LB", promo="2x1")
    ], "2025-01-01", "2025-01-07")
    assert db.dedup_offers(store, "testchain", "2025-01-01") == 0
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 2


@pytest.mark.parametrize("difference", ["product_raw", "category"])
def test_dedup_keeps_uncertain_printed_variants(store, difference):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    first = offer("Arroz rojo", "arroz", "1 lb", category="Granos")
    second = first | {"size_text": "1 LB", difference:
                      "Arroz azul" if difference == "product_raw" else "Ofertas"}
    assert db.upsert_offers(store, run, "testchain", [first, second],
                            "2025-01-01", "2025-01-07") == 2
    assert db.dedup_offers(store, "testchain", "2025-01-01", run_id=run) == 0
    assert store.execute("SELECT COUNT(*) AS n FROM offers WHERE run_id=?",
                         (run,)).fetchone()["n"] == 2


@pytest.mark.parametrize("missing", ["size_text", "price_sale", "product_norm"])
def test_incomplete_offer_exact_replay_is_idempotent(store, missing):
    entry = offer("Arroz", "arroz", "1 lb", 1.99)
    entry[missing] = None
    run1 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, run1, "testchain", [entry],
                            "2025-01-01", "2025-01-07") == 1
    db.finish_run(store, run1, "ok", 1)
    run2 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, run2, "testchain", [entry],
                            "2025-01-01", "2025-01-07") == 0
    db.finish_run(store, run2, "ok", 0)
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 1


def test_complete_offer_replay_is_idempotent(store):
    entry = offer("Arroz", "arroz", sku="stock-1")
    run1 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, run1, "testchain", [entry],
                            "2025-01-01", "2025-01-07") == 1
    db.finish_run(store, run1, "ok", 1)
    run2 = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, run2, "testchain", [entry],
                            "2025-01-01", "2025-01-07") == 0
    db.finish_run(store, run2, "ok", 0)
    assert [(r["status"], r["offers_found"]) for r in store.execute(
        "SELECT status, offers_found FROM scrape_runs ORDER BY id").fetchall()] == [
            ("ok", 1), ("ok", 0)]
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 1


@pytest.mark.parametrize("missing", ["size_text", "price_sale", "product_norm"])
def test_incomplete_replay_ignores_page_and_source_location(store, missing):
    entry = offer("Arroz", "arroz", page=1, source_url="https://example.org/old")
    entry[missing] = None
    first = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, first, "testchain", [entry],
                            "2025-01-01", "2025-01-07") == 1
    db.finish_run(store, first, "ok", 1)
    replay = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    assert db.upsert_offers(store, replay, "testchain", [
        entry | {"page": 3, "source_url": "https://example.org/new"}],
        "2025-01-01", "2025-01-07") == 0
    db.finish_run(store, replay, "ok", 0)
    assert store.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"] == 1


def test_failed_chain_rolls_back_offers_before_next_chain(store, monkeypatch):
    import run_weekly

    cfg = {"chains": {"testchain": {"type": "structured", "shopper_page": "test"}}}
    monkeypatch.setattr(run_weekly.validity, "detect", lambda *args: (
        "2025-01-01", "2025-01-07"))
    monkeypatch.setattr(run_weekly.structured, "scrape", lambda *args: [
        offer("Arroz", "arroz")])
    real_upsert = db.upsert_offers
    attempts = 0

    def fail_after_insert(*args, **kwargs):
        nonlocal attempts
        result = real_upsert(*args, **kwargs)
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected failure after ingest")
        return result

    monkeypatch.setattr(db, "upsert_offers", fail_after_insert)
    assert run_weekly.run_chain(store, cfg, "testchain")["status"] == "error"
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 0
    assert store.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"] == 0
    assert run_weekly.run_chain(store, cfg, "testchain")["status"] == "ok"
    assert [(r["status"], r["offers_found"]) for r in store.execute(
        "SELECT status, offers_found FROM scrape_runs ORDER BY id").fetchall()] == [
            ("error", 0), ("ok", 1)]
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 1


def test_run_reports_only_surviving_offers_after_dedup(store, monkeypatch):
    import run_weekly

    cfg = {"chains": {"testchain": {"type": "images", "shopper_page": "test"}}}
    monkeypatch.setattr(run_weekly.image_fetch, "fetch_images", lambda *args: ["page"])
    monkeypatch.setattr(run_weekly.validity, "detect", lambda *args, **kwargs: (
        "2025-01-01", "2025-01-07"))
    monkeypatch.setattr(run_weekly, "extract_images", lambda *args: [
        offer("Arroz", "arroz", "1 lb"),
        offer("Arroz", "arroz", "1 LB")])
    result = run_weekly.run_chain(store, cfg, "testchain")
    assert result["status"] == "ok"
    assert result["offers"] == 1
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 1
    assert store.execute("SELECT offers_found FROM scrape_runs").fetchone()["offers_found"] == 1


def test_structured_collection_dedups_identical_pack(store, monkeypatch):
    import run_weekly

    cfg = {"chains": {"testchain": {"type": "structured", "shopper_page": "test"}}}
    monkeypatch.setattr(run_weekly.validity, "detect", lambda *args: (
        "2025-01-01", "2025-01-07"))
    monkeypatch.setattr(run_weekly.structured, "scrape", lambda *args: [
        offer("Arroz", "arroz", "1 lb", sku="stock-1"),
        offer("Arroz", "arroz", "1 LB", sku="stock-1")])
    assert run_weekly.run_chain(store, cfg, "testchain")["offers"] == 1
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 1


def test_finish_failed_run_discards_uncommitted_offers(store):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    db.upsert_offers(store, run, "testchain", [offer("Arroz", "arroz")],
                     "2025-01-01", "2025-01-07")
    db.finish_run(store, run, "error", 0, "downstream failed")
    assert store.execute("SELECT COUNT(*) AS c FROM offers").fetchone()["c"] == 0
    assert store.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"] == 0
    assert store.execute("SELECT status FROM scrape_runs WHERE id=?", (run,)).fetchone()["status"] == "error"


def test_finish_success_records_actual_surviving_rows(store):
    run = db.start_run(store, "testchain", "test", "2025-01-01", "2025-01-07")
    db.upsert_offers(store, run, "testchain", [offer("Arroz", "arroz")],
                     "2025-01-01", "2025-01-07")
    db.finish_run(store, run, "ok", 3)
    assert store.execute("SELECT offers_found FROM scrape_runs WHERE id=?",
                         (run,)).fetchone()["offers_found"] == 1
