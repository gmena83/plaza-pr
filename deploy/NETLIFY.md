# Netlify static site (PLAZA frontend)

> Lives outside `deploy/netlify/` on purpose: everything in that folder is published.

Static files only. The API lives on Fly.io (`plaza-pr-api`), data and auth on
Supabase. See `docs/ARCHITECTURE.md` for the whole picture.

## URLs
- Landing:    https://plaza-pr.netlify.app/
- Dashboard:  https://plaza-pr.netlify.app/app/   (search + Mi Lista)
- B2B demo:   https://plaza-pr.netlify.app/negocios.html
- API:        https://plaza-pr-api.fly.dev

## Files
| Deployed file | Source of truth | Notes |
|---|---|---|
| `index.html` | this folder | landing page; also forwards magic-link `#access_token=…` to `/app/` |
| `app/index.html` | `api/static/dashboard.html` | copy before deploying |
| `negocios.html` | `api/static/negocios.html` | copy before deploying |
| `_redirects`, `netlify.toml` | this folder | catch-all to landing; security headers |

Pages pick their API base at runtime: on `*.netlify.app` (or `file:`) they call
`https://plaza-pr-api.fly.dev` cross-origin (the API's CORS allows
GET/POST/PATCH/DELETE); served by local FastAPI they call same-origin.

Magic-link requests from `/app/` redirect to that exact slash-terminated
pathname; root-landed legacy token links are forwarded by the landing page.
Do not change `/app/` to `/app`: the slash redirect can drop the URL hash
carrying Supabase tokens. A fresh magic-link round trip through Netlify's
visitor-password page remains **unverified** and is assigned to the owner for
browser testing; a challenge/redirect could affect the hash.

## Demo release gate (visitor password)

This Netlify site is deployed manually, not linked to GitHub builds. A GitHub
push does **not** redeploy it. On 2026-10-13 the owner enabled a site-wide
visitor password; unauthenticated GETs to `/` and `/app/` returned the Netlify
password form with HTTP 401 both before and after production deployment.
Recheck after any access-setting change: `password_context=all` without a
real challenge is **not** protection. Never place a visitor password, Supabase
keys or DB connection strings in this repo, deploy logs or chat. The Fly API
does not inherit the site password; its assistant and profile routes require a
valid magic-link session, and the assistant also requires completed profile.

The integrated app includes observed specials and a clearly marked
**DATOS FICTICIOS** browser-only illustration, not a validated forecast. The
assistant is restricted to current recorded offers and confirmed list edits.
The privacy-policy draft stays unpublished. Sprint 5 real-prediction validation
is a separate release gate.

## Published demo and verification (2026-10-13)

- GitHub code release `37be323` on `main`; Fly image deployed with
  `/api/profile` and `/api/assistant` present in `/openapi.json`. A temporary
  Supabase magic-link account exercised profile completion, current-offer
  questions and confirmed Mi Lista edit/remove against **live Fly**, then was
  deleted; anonymous profile/assistant calls returned 401 and CORS preflight
  returned 200.
- Netlify published deploy `6ace6372311b38f1bbdc6c3f` (`ready`), not a
  GitHub auto-build. Its `/app/index.html` SHA-1
  `9fc1ae921dd19e3644854abb182e80ad43e2fa52` matched the committed
  dashboard and Fly-served HTML at release. The unauthenticated landing and
  app paths returned 401 after publication. On the byte-identical Fly-served
  page, observed-offer search and the **DATOS FICTICIOS** checkbox worked at
  320px/375px without page-level horizontal overflow. The project suite had
  76 passing tests.
- **Still open, owner-run:** in a fresh/private browser open `/app/`, pass the
  visitor gate, request a *new* magic link, return to `/app/` with the session
  intact, complete the profile and confirm one proposed Mi Lista edit only
  after explicitly choosing it. This tests a redirect behavior that source
  parity, API QA and HTTP 401 cannot establish. Do not record the password or
  token in screenshots, scripts or this repo. If the link loses its session,
  preserve only the URL path and error behavior (not the token hash).

## Pending full release — October 17, 2026

GitHub `main` at documentation commit `13fcdf1` (code-bearing predecessor `7776f31`) is **not** the deployed app: Netlify is a manually published static site and Fly still runs release 9 from October 13. The merged candidate includes password signup/sign-in, Google OAuth UI, market analytics and batch database writes. The owner selected **review and configure all new features for a later full release**, rather than deploying that candidate as-is. At this check, live Supabase Auth reported email enabled, Google **disabled**, signup allowed and email auto-confirmation **enabled**. Publishing the old visible Google button would lead to a disabled provider; exposing password signup without a provider gate would bypass the previously documented confirmation/recovery/rate-limit and existing-user checks. Work continues on `release/full-readiness-20261017`, not in production; `docs/API.md` describes its new comparable-offers contract.

The code-bearing `main` candidate's `/api/analytics/basket_projections` totals take minimum *advertised* sale prices for loosely matched staple names with unequal per-chain coverage, then multiply the current total by 2 and 4. Those numbers are not a validated future-price forecast or comparable full basket; the dashboard's unqualified “Proyección de Canasta Básica” label must not be released as-is. The release branch retires that route and displays only dated, exact-name/brand/pack/basis matched advertised specials, excluding quantity-dependent multi-buy prices. The separate **DATOS FICTICIOS** browser-only illustration remains the only approved projection presentation. Full-release review must cover source/pack comparability, missing items, defensible labels or removal, and chronological evaluation before any real timing prediction.

The latest verified committed-`main` bundle is `~/Backups/plaza-pr/plaza-pr-20261017-13fcdf1.bundle`, independently copied to mt03 as `~/backups/plaza-pr/plaza-pr-20261017-13fcdf1.bundle`. Both `git bundle verify` checks found complete history and both SHA-256 digests matched `fdf8ce41acd39ee07669f3de555d43b63f17b2b2e22880f0062f48a4599262f4`. This main-only bundle does **not** include the separate release branch, ignored runtime data, environment credentials or the local-only unpublished `docs/PRIVACY_DRAFT.md`. The Pueblo snapshot data have their separate mt03→mt01 daily sync; neither Git bundle nor snapshot sync is a full production database backup.

**Release gates:** review/fix and test the merged Auth, analytics and batch-write paths; configure Google OAuth through Supabase/Google without recording secrets in this repo; verify email confirmation/recovery and provider redirects through the visitor-password challenge with throwaway accounts; ensure both dashboard copies match; run the full test suite and staging smoke tests; then deploy Fly and the password-gated Netlify static site and read back the exact release, paths and HTTP 401 protection. The branch's latest full local suite passed 174 tests (33 skipped) after dashboard synchronization; focused isolated PostgreSQL checks passed 82 (4 skipped). These are not staging or protected-page QA. The branch removes the misleading legacy “Mayores bajas de la semana” widget; `/api/movers` remains an unsuitable same-item savings metric. The new comparable route uses a Puerto Rico calendar date and scoped read connection, but legacy routes still initialize schema on GET, and the offer-identity migration is draft-only. Keep the current production release in place until these gates pass. The owner-run protected-page magic-link round trip remains unverified. The [release-readiness review](../docs/RELEASE_READINESS_2026-10-17.md) records concrete blocking code paths, tests and external configuration decisions.

For future releases: test and review staging; commit/push GitHub; deploy and
smoke-test Fly; verify Netlify's password challenge; production-deploy static
files from this directory; read back the exact published deploy and challenge.

## Redeploy
```bash
cd ~/pr-shopper-pipeline
cp api/static/dashboard.html deploy/netlify/app/index.html
cp api/static/negocios.html  deploy/netlify/negocios.html
cd deploy/netlify && netlify deploy --prod --dir=.
```

Supabase Auth configuration for Email/Password and Google OAuth:
- Redirect allow-list: `https://plaza-pr.netlify.app/**` (and `http://127.0.0.1:8200/**` for local dev); site_url `https://plaza-pr.netlify.app`.
- **Google OAuth Setup in Supabase Auth**:
  1. Go to Supabase Dashboard -> **Authentication** -> **Providers** -> **Google**.
  2. Enable Google authentication.
  3. Create an OAuth 2.0 Client ID in Google Cloud Console (APIs & Services -> Credentials).
  4. In Google Cloud Console, add `https://<your-supabase-project-id>.supabase.co/auth/v1/callback` under **Authorized redirect URIs**.
  5. Copy Client ID and Client Secret into Supabase Google Provider configuration and save.
