# PLAZA demo deploy (Netlify + Tailscale Funnel)

Static frontend on Netlify, live API on menatech01 exposed via Tailscale Funnel.

## URLs
- Demo:      https://plaza-pr.netlify.app
- Live API:  https://menatech01-1.tail706cb2.ts.net  (Funnel -> localhost:8200)

## How it works
Netlify is static-only, so the frontend calls the API cross-origin:
- `api/static/dashboard.html` sets `API` to the Funnel URL when the page is
  served from `*.netlify.app`, else same-origin (local FastAPI).
- FastAPI has CORSMiddleware(allow_origins=["*"]) so the Netlify origin is accepted.
- Tailscale Funnel proxies public HTTPS -> localhost:8200 (the uvicorn API).

No Netlify proxy/rewrite is used (external-host proxying 502'd against the
Funnel host); direct cross-origin + CORS is simpler and reliable.

## Redeploy frontend
```bash
cp ~/pr-shopper-pipeline/api/static/dashboard.html ~/pr-shopper-pipeline/deploy/netlify/index.html
cd ~/pr-shopper-pipeline/deploy/netlify
netlify deploy --prod --dir=.
```

## Funnel (API exposure)
```bash
# enable (persists in background):
sudo tailscale funnel --bg --https=443 http://127.0.0.1:8200
# status / disable:
tailscale funnel status
tailscale funnel --https=443 off
```
Note: Funnel exposes the API publicly. It is read-only (GET endpoints), but
consider it public demo data. Disable with `funnel off` when the demo is done.

## Backend
The API runs as systemd user service `pr-shopper-api.service` (port 8200).
The weekly scrape timer `pr-shopper-scrape.timer` keeps data fresh; the demo
reflects new weeks automatically.
