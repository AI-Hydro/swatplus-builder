# Vendored dashboard libraries

Inlined into every `dashboard.html` by `output/dashboard.py::_vendor_assets`
so the dashboard opens offline and never depends on a CDN. Only the
OpenStreetMap basemap tiles still need a network; offline, the map shows the
embedded model layers on a blank background with a notice.

| File | Library | Version | Source | License | SHA-256 |
|---|---|---|---|---|---|
| `plotly.min.js` | plotly.js | 3.0.1 | `plotly/package_data/plotly.min.js` from the Python `plotly` 6.2.0 wheel | MIT (`LICENSE.plotly`) | `a32e817bb121e9e89016ce4cee85ee3f1c66f6a6c95c4b53a5f488f77756d7a4` |
| `leaflet.js` | Leaflet | 1.9.4 | https://unpkg.com/leaflet@1.9.4/dist/leaflet.js | BSD-2-Clause (`LICENSE.leaflet`) | `db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a` |
| `leaflet.css` | Leaflet | 1.9.4 | https://unpkg.com/leaflet@1.9.4/dist/leaflet.css | BSD-2-Clause (`LICENSE.leaflet`) | `a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6` |

The Leaflet files match the Subresource Integrity hashes published by the
Leaflet project for 1.9.4 (`leaflet.js`
`sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=`, `leaflet.css`
`sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=`).

The dashboard previously loaded plotly.js 2.32.0 from the CDN. Plotly 3 no
longer accepts string axis titles, so the dashboard passes `{ text: ... }`
objects, which both versions accept. Leaflet's marker and layers-toggle
images are not vendored: the dashboard draws circle markers and keeps the
layer list expanded, so it never requests them.
