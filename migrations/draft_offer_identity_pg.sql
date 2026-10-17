-- DRAFT ONLY: exercise against an isolated Postgres copy, never against production
-- without backup, write freeze, conflict audit, and explicit release approval.
-- Evidence preflight (read-only, 2026-10-17): 12,776 rows; 829 NULL size_text,
-- 735 NULL brand, 3,761 NULL sku; zero NULL product_norm/price_sale/valid_from;
-- 0 duplicate groups under the conservative identity below. Repeat the audit
-- against a fresh snapshot immediately before approval. Previously discarded
-- brand/SKU/promo variants cannot be recovered from offers alone; inspect raw
-- captures for restoration before declaring historical coverage complete.
--
-- Rollout plan: (1) take and restore-test a consistent DB backup to an isolated
-- Postgres >=15 instance; (2) review all duplicate groups plus NULL-SKU rows
-- against source evidence, quarantine ambiguous records rather than deleting;
-- (3) rehearse this transaction on the copy and verify row counts, old/new
-- indexes, replay and distinct variants; (4) freeze writers, repeat preflight,
-- gain owner approval, then run once in a maintenance window; (5) read back
-- counts/indexes/run metadata and smoke test writes; rollback via the verified
-- backup if required. This file is NOT wired to init_db or automatic startup.
-- Live writer still fails closed for an inferred SKU colliding with a legacy
-- NULL SKU; this draft alone cannot reconcile those 3,761 rows. SQLite retains
-- its legacy key and requires its own audited migration before feature parity.
--
-- This transactional replacement retains SKU/brand/promo variants; page and
-- source_url are provenance, not identity. No DELETE/UPDATE of offer rows.
-- PostgreSQL >= 15 is required for NULLS NOT DISTINCT.
BEGIN;
LOCK TABLE offers IN ACCESS EXCLUSIVE MODE;
DO $$
DECLARE
    old_definition TEXT;
    duplicate_count BIGINT;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO old_definition
      FROM pg_constraint
     WHERE conrelid = 'offers'::regclass
       AND conname = 'offers_chain_slug_product_norm_size_text_price_sale_valid_f_key';
    IF old_definition IS DISTINCT FROM
       'UNIQUE (chain_slug, product_norm, size_text, price_sale, valid_from)' THEN
        RAISE EXCEPTION 'Unexpected or missing legacy offers unique constraint: %', old_definition;
    END IF;
    SELECT count(*) INTO duplicate_count FROM (
        SELECT 1 FROM offers
         GROUP BY chain_slug, product_raw, product_norm, sku, brand, size_text,
                  price_sale, price_regular, promo, category, valid_from, valid_to
        HAVING count(*) > 1
    ) conflicts;
    IF duplicate_count <> 0 THEN
        RAISE EXCEPTION 'Offer identity audit failed: % duplicate groups; quarantine/review, do not merge automatically', duplicate_count;
    END IF;
END $$;
CREATE UNIQUE INDEX offers_identity_v2
    ON offers (chain_slug, product_raw, product_norm, sku, brand, size_text,
               price_sale, price_regular, promo, category, valid_from, valid_to)
    NULLS NOT DISTINCT;
ALTER TABLE offers DROP CONSTRAINT offers_chain_slug_product_norm_size_text_price_sale_valid_f_key;
COMMIT;
