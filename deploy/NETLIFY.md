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
