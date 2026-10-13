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
carrying Supabase tokens. Test a new magic link end to end after enabling site
password protection; a challenge/redirect could affect the hash.

## Demo release gate (visitor password)

This Netlify site is deployed manually, not linked to GitHub builds. A GitHub
push does **not** redeploy it. The owner will enable a visitor password for the
entire site. Before `netlify deploy --prod`, verify that unauthenticated
requests to `/` and `/app/` get a real password challenge, not HTTP 200.
`password_context=all` without an active password is **not** protection.
Never place a visitor password, Supabase keys or DB connection strings in
this repo, deploy logs or chat. The Fly API does not inherit the site password;
its assistant and profile routes require a valid magic-link session, and the
assistant also requires completed profile.

The integrated app includes observed specials and a clearly marked
**DATOS FICTICIOS** browser-only illustration, not a validated forecast. The
assistant is restricted to current recorded offers and confirmed list edits.
The privacy-policy draft stays unpublished. Sprint 5 real-prediction validation
is a separate release gate.

Release order: test and review staging; commit/push GitHub; deploy and smoke-
test Fly; verify Netlify's password challenge; production-deploy static files
from this directory; read back the exact published deploy and challenge.
For protected UI QA, use a signed-in browser session after the visitor-password
prompt without printing/storing its value in scripts.

## Redeploy
```bash
cd ~/pr-shopper-pipeline
cp api/static/dashboard.html deploy/netlify/app/index.html
cp api/static/negocios.html  deploy/netlify/negocios.html
cd deploy/netlify && netlify deploy --prod --dir=.
```

Supabase Auth must list the site in its redirect allow-list
(`https://plaza-pr.netlify.app/**`; site_url `https://plaza-pr.netlify.app`).
