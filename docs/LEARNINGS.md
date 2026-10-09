# Learnings

Hard-won operational lessons from building PLAZA. Each is a mistake made and
fixed, or a non-obvious constraint discovered by probing the live sources.

## Data acquisition

1. **Probe the source before designing.** Every chain publishes differently:
   shared e-commerce platform (structured HTML), image-only PDF, Wix images,
   store-gated JS app, Firestore circular. The whole architecture fell out of
   mapping each chain's actual delivery mechanism first. Never assume "it's a
   PDF."

2. **"Shopper" PDFs are scanned images with no text layer.** `pdftotext`
   returns 0 chars. Classic OCR (tesseract) on dense multi-column Spanish
   layouts is error-prone; a local vision-language model is the right tool.

3. **The biggest chains hide behind interaction.** Econo's `/shopper` is a
   store locator gate — you must click "Make My Store" before the circular
   loads, then click category tabs. A generic image-harvester finds nothing;
   you need a per-chain Playwright interaction script.

4. **Playwright's actionability checks fight Angular apps.** Normal
   `locator.click()` and `scroll_into_view_if_needed()` time out on Econo's nav
   (elements present but "not visible"). A direct JS `el.click()` triggers the
   router reliably. Verified against the live site.

5. **Historical data is the real unlock — and it's not on the chains' sites.**
   Chains only serve the current week. The aggregator
   `cdn.shoppersdepuertorico.com` re-hosts every chain's official circular as
   dated assets (`/shopper-{chain}-{date}-pagina-NN.jpg`) needing only a
   `Referer` header. That gave 4+ weeks of real history the official sites
   don't expose — and got Agranel without scraping its Facebook-only shopper.
   HEAD requests 403 there; GET works.

6. **Some "sources" aren't the shopper.** Agranel's Shopify store is its full
   regular-price catalog (4,700 items, zero sale markers), not the weekly
   shopper. econotogo's API is auth-gated (401). Don't mistake an online store
   for the weekly ad.

## Vision-language extraction

7. **AWQ beats fp16 on a 16 GB card.** The 17 GB fp16 Qwen3-VL starved the KV
   cache (max usable seq len ~2272 tokens, too short for dense pages). The AWQ
   4-bit checkpoint (~5.5 GB) leaves ample KV headroom. vLLM's
   `--gpu-memory-utilization` must be tuned to actual free VRAM (0.92 OOM'd at
   startup, 0.80 left no KV, 0.82-0.86 works).

8. **Cap image size to fit context.** A 200 DPI page blew past the 8192-token
   context (12k vision tokens). Downscale to ~1568px long edge (~3,100 tokens)
   so image + 6144-token output fits. Per-chain DPI overrides matter (SuperMax's
   PDF is higher-res than Selectos').

9. **CMYK JPEGs crash PNG re-encode.** Some Wix images are CMYK; convert to RGB
   before saving as PNG or PIL throws "cannot write mode CMYK as PNG".

10. **The VL model handles Spanish + promo formats well** with a good prompt:
    `2/$5` -> 2.50, `Límite de N`, per-lb pricing, `2x87¢`. temperature=0 and a
    strict JSON-only instruction. It still truncates on very dense pages if
    max_tokens is too low.

## Data quality

11. **Most "near-duplicates" are real products.** Of hundreds of similar-name
    pairs, the vast majority are genuinely different (cheddar mild vs sharp,
    jello strawberry vs raspberry, charmin soft vs strong). Aggressive dedup
    would corrupt the data. Only dedup exact matches (same chain, product_norm,
    price, week) — those come from overlapping scrape pages (Econo home grid +
    10 category tabs produced 120 dup rows).

12. **Unit price is the honest comparison.** Sticker price misleads across pack
    sizes (a $16.97 family pack vs a $0.95/lb chicken breast). Parse sizes to a
    base unit and compare $/lb, $/100ml, $/un. ~88% of offers parse; the rest
    are count-only or unparsable and keep unit_price=NULL.

13. **Detect cycles on sticker price, grouped by (chain, product, size).**
    Corona stays $9.98 but its pack changes (6×12oz vs 12×7oz), swinging
    unit_price and faking a cycle. A promo cycle always shows in the sticker.
    And require a >=15% swing before claiming any cycle or sale, or flat
    products get mislabeled.

14. **Validity dates differ per chain and aren't always today+6.** Pueblo runs
    Wed-Tue, Amigo Thu-Wed, SuperMax Wed-Tue; mr-special/mi-gente run ~2 weeks;
    walmart ~4. Parse each source's printed dates (page text for structured
    chains, a VL read of page 1 for image chains), fallback to a default.

## Engineering / ops

15. **Long-running scrapes need a lock + idempotency.** A weekly timer and a
    manual run can overlap. A global flock (exit fast if held) plus idempotent
    upsert keys means re-running is always safe. Sweep runs left in "running"
    by killed processes to "stale".

16. **The terminal tool kills background processes on timeout.** Launch
    long-lived servers/jobs with a double-fork detach (setsid) so they survive
    the launching call, then poll their log/DB separately.

17. **Leaked PYTHONPATH breaks subprocess venvs.** When spawning the project
    venv's python from an agent shell, scrub PYTHONPATH/VIRTUAL_ENV from the
    env or the subprocess imports the wrong site-packages (pydantic_core
    mismatch).

18. **Netlify is static-only.** A server-rendered dashboard + `/api/*` backend
    can't just deploy there. Options: Netlify proxy `_redirects` to the live
    API (502'd against the Tailscale Funnel host) or — cleaner — enable CORS on
    the API and have the static frontend call the Funnel URL cross-origin.
    Detect the `*.netlify.app` host to switch API base.

19. **SQLite WAL handles concurrent readers** (API + a writing scrape) fine for
    this scale, but don't run two writers; the orchestrator lock prevents that.

20. **uv venvs don't ship pip.** Use `uv pip install --python .venv/bin/python`.
    And uv-managed Python 3.14 had no vLLM wheels — pin the project venv to
    Python 3.12.

## Postgres / Supabase migration

21. **SQLite's GROUP BY leniency hides bugs.** SQLite lets you select
    non-aggregated columns outside GROUP BY (picks an arbitrary row); Postgres
    17 errors. The API had four such queries (`price_basis`, `product_norm`).
    Wrapping them in `MIN()` is safe when the column is constant per group.
    Test every endpoint against Postgres before cutting over — 12 of 13
    worked, the one that failed was the one we didn't smoke-test first.

22. **Supabase pooler (Supavisor) only knows built-in roles.** Custom roles
    (`plaza_reader`/`plaza_writer`) get `EAUTHQUERY user not found` through
    the shared pooler no matter the grants. They work only on the direct
    connection (which needs the paid IPv4 add-on; without it db.*.supabase.co
    is IPv6-only and Fly can't reach it). For the beta we use the `postgres`
    role through the pooler; revisit least-privilege once IPv4 provisions.

23. **DB password resets don't propagate to the pooler instantly.** Two
    resets failed auth for 5+ minutes each. The Management API's
    `/database/query` endpoint runs SQL as `postgres` without the password —
    that's how the schema/roles/grants were applied. (It still can't
    ALTER ROLE postgres — Supabase's postgres isn't a superuser.)

24. **psycopg2 RealDictCursor breaks on statements without a result set when
    passed an empty params tuple** (IndexError). Pass `None` instead of `()`.
    Also: emulating sqlite's `lastrowid` via auto-appended `RETURNING id`
    must skip `ON CONFLICT` inserts (DO NOTHING returns zero rows).

25. **`GENERATED ALWAYS AS IDENTITY` needs `OVERRIDING SYSTEM VALUE`** when
    migrating explicit ids (scrape_runs) — plain INSERT fails. And reset the
    sequence with setval afterwards.

26. **Docker image size matters on Fly.** The full requirements.txt (torch,
    vllm, playwright) built a 3.6 GB image that exceeded the 8 GB unpack
    limit and deployed nothing. A slim `requirements-api.txt` (fastapi,
    uvicorn, psycopg2, pyyaml, requests) deploys in minutes. Fly's `mia`
    region is deprecated — use `dfw`.

27. **Supabase magic-link needs the site URL allowlist first.** Set
    `site_url` + `uri_allow_list` via the Management API
    (`/config/auth`) or the OTP email lands users on localhost:3000.
    The publishable key (sb_publishable_*) is safe to ship in the frontend.

28. **CORS `allow_methods=["GET"]` silently breaks every write from the browser.**
    The read-only API was fine until list endpoints appeared: the browser's
    preflight for POST/DELETE got `400` and the request never left the page.
    The UI swallowed the error, so "+lista" looked dead. Server logs show it as
    `OPTIONS ... 400`. Allow the write methods, and make the frontend show
    API errors instead of failing quietly.

29. **Netlify's `/app` → `/app/` 301 drops the URL hash**, which is where
    Supabase puts the magic-link tokens. Point `emailRedirectTo` at the site
    root and have the landing page forward `#access_token=…` to `/app/`.

## Email digest

30. **The Supabase publishable key was a write key.** Supabase's default
    privileges give `anon` full INSERT/UPDATE/DELETE on every new `public`
    table, and RLS was off on the price tables, so anyone could delete
    `offers` with the key in dashboard.html. Revoked writes on existing
    tables *and* in `ALTER DEFAULT PRIVILEGES` (otherwise every new table
    re-opens the hole). Probe with a DELETE on `id=eq.-999`: 401 is good,
    204 means writable.

31. **Unsubscribe links must not act on GET.** Outlook/Gmail/corporate
    scanners pre-fetch links, so a GET that unsubscribes silently opts people
    out. GET shows a one-button confirm page; the actual change is a POST.
    The RFC 8058 `List-Unsubscribe-Post` header gives Gmail/Yahoo their own
    one-click POST.

32. **Single-store verdicts almost never fire on real lists.** Lists pin
    exact products and sizes, so one chain rarely carries more than 2 of 6.
    The digest recommends the best 1- *or* 2-store plan. Break coverage ties
    on the cost of the whole list (plan stores + best price elsewhere for the
    rest), not the plan subtotal, or pairs that skip the expensive item win.

33. **Email HTML: tables, inline styles, and test at 390 px.**
    - `display:block` on a `<table>` leaves its row shrink-wrapped. To get a
      full-width mobile button, keep it a table at `width:100%` and make the
      `<a>` block.
    - Glue tokens with `&nbsp;` ("mié 21", "3 de 6") so phones don't split them.
    - Put the struck-through old price under the sale price, not in the meta
      line, where it reads as a unit price.
    - Render previews headless (Playwright `set_content` + screenshot) before
      sending; mail-tester.com gives SPF/DKIM/SpamAssassin results (10/10 here).

34. **systemd `EnvironmentFile` and bash `source` disagree on special chars.**
    A value like `PLAZA <x@y>` works in systemd but is a redirection in bash.
    Keep the shared `.env.supabase` to plain `KEY=value` with no spaces or
    `<>`, and put such defaults in code.

35. **Before dropping legacy tables in a reused Supabase project, check
    triggers on `auth.users`.** The old conGenAI app had `on_auth_user_created`
    → `handle_new_user()` → `INSERT INTO public.users`. Dropping `public.users`
    alone would have made every PLAZA magic-link sign-up fail. Order: back up
    (supabase db dump + CSV), drop the auth trigger (postgres can), drop the
    tables in one statement (no CASCADE, so surprises error out), drop orphaned
    functions, then prove sign-up still works with an admin `generate_link`
    for a throwaway address.

36. **mail-tester only reads DMARC from the exact From domain.** Receivers
    fall back to the parent domain's policy, but checkers flag "not fully
    authenticated" until the subdomain has its own `_dmarc` record.

37. **Moving the database means moving the backup.** After the Postgres
    cut-over the nightly job kept copying `db/shopper.db`. It still "succeeded"
    every night, but that file no longer changes, and the user tables were
    never in it. Check what a backup contains, not just its exit code. It now
    dumps Postgres.

38. **A backup isn't one until it has been restored.** The first restore test
    found that `events` had no DDL in any schema file (it was created ad hoc)
    and that alphabetical load order breaks foreign keys (`list_items` before
    `lists`). `deploy/restore_db.py` restores into a throwaway schema inside a
    transaction and rolls back, so it is safe to run against production. It
    loads in FK order and resets identity sequences, otherwise new rows collide
    with restored ids.
