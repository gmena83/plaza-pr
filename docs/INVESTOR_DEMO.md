# PLAZA projection concept inside the prototype

This is **not a separate demo site**. The same projection component is embedded immediately after the observed-price history chart in both `api/static/dashboard.html` and `deploy/netlify/app/index.html`. The two copies must remain byte-identical. Open the Netlify-ready local page with `xdg-open deploy/netlify/app/index.html` (or run the local API/dashboard). The card can be used without signing in; it is an illustrative concept, **not** the future personalized full-profile feature.

## What it demonstrates

- A four-product example basket can be edited with checkboxes; four hypothetical weekly totals and the smallest one recompute locally. Reset restores the example. Fixed integer-cent arrays in `DEMO_SAMPLE` are invented and never enter `offers`, historical charts, Mi Lista, browser storage, or network requests. It deliberately does not use the searched product or a signed-in user's actual list.
- A bright **PROTOTIPO · DATOS FICTICIOS** marker sits directly above the chart, with another **RESULTADO DE SIMULACIÓN · DATOS FICTICIOS** marker adjacent to the highlighted total; prose states that no model or measured accuracy exists. The observed-history area has its own title and is visually separated by a border and background. Keep both markers in any screenshot.
- Day/month forecasts remain pending instead of fabricating precision; the real personalized prediction, if validated, must be gated server-side for completed profiles.

For peers and investors: show the live observed-price search first, then scroll to the marked concept and toggle an example item. Explain that **only the interaction is being tested**. The simulated cheapest week and dollar difference are not claimed to be actual savings, forecast performance, or supermarket prices. The in-card **Compartir opinión** link opens an email to contact@menatech.dev; no feedback or clickstream is automatically collected by the concept. Ask what they understood, what confused them, and what would make a real list useful.

## Release boundary

The owner authorized shipping the integrated **demo-only** prototype to Netlify and will set a URL visitor password. Verify that password challenge before publishing the new UI; do not claim the site is private based on configuration metadata alone. The account-only assistant answers from observed current offers and asks for explicit confirmation before Mi Lista edits; it never uses the invented projection. The separate Sprint 5 real-prediction research remains incomplete (one paired edition, zero evaluation cutoffs) and no forecast is approved for release. An unpublished privacy-policy draft is local only, not a public policy.

Verification: `env -u PYTHONPATH -u PYTHONHOME .venv/bin/python -m pytest tests spikes/001-pueblo-catalog spikes/002-pueblo-history -q`, then live Netlify/Fly checks after deployment. Reviewed screenshots of the integrated history/demo card are in `docs/previews/projection-desktop.png` and `docs/previews/projection-mobile.png`; they include the marker, graph, result, and disclaimer. The demo component itself reads no API.
