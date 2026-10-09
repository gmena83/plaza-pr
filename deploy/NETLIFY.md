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

Magic links redirect to the site root, not `/app`. Netlify's `/app` → `/app/`
301 drops the URL hash that carries the Supabase tokens.

## Redeploy
```bash
cd ~/pr-shopper-pipeline
cp api/static/dashboard.html deploy/netlify/app/index.html
cp api/static/negocios.html  deploy/netlify/negocios.html
cd deploy/netlify && netlify deploy --prod --dir=.
```

Supabase Auth must list the site in its redirect allow-list
(`https://plaza-pr.netlify.app/**`; site_url `https://plaza-pr.netlify.app`).
