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
