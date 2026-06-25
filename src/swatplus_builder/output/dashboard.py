"""Self-contained interactive HTML dashboard for SWAT+ model evidence.

Generates a single ``dashboard.html`` that hydrologists can open directly in a
browser — no server, no install, no external dependencies beyond Plotly's CDN.

The dashboard reads every artifact the pipeline writes (evidence summary,
metrics, alignment, calibration provenance, physical gates, water balance,
etc.) and presents them as interactive Plotly charts, metric cards, gate
status panels, and evidence tables in a modern, responsive layout.

Architecture
------------
:func:`build_dashboard` is the sole public entry point.  Give it a run
directory and it returns the path to the generated HTML file.  The dashboard
is self-contained: all data is embedded as ``<script type="application/json">``
blocks and all styling is inline CSS.  Plotly is loaded from CDN (the only
external resource).

Typical usage::

    from swatplus_builder.output.dashboard import build_dashboard
    html_path = build_dashboard(run_dir)

Integration
-----------
Called from ``orchestrate.run_pipeline`` (lightweight runs) and
``usgs_e2e.run_usgs_workflow`` (full governance runs) so every pipeline
execution produces a dashboard automatically.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Public API ────────────────────────────────────────────────────────────────


def build_dashboard(run_dir: Path | str) -> Path:
    """Generate a self-contained interactive dashboard for a completed run.

    Args:
        run_dir: Pipeline output directory (contains ``run_config.json``,
            ``outputs/``, ``reports/``, etc.).

    Returns:
        Path to the generated ``dashboard.html`` file.
    """
    run_dir = Path(run_dir).expanduser().resolve()
    data = _collect_all_data(run_dir)
    html = _render_html(data)
    out = run_dir / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    log.info("Dashboard written: %s", out)
    return out


# ── Data collection ───────────────────────────────────────────────────────────


def _collect_all_data(run_dir: Path) -> dict[str, Any]:
    """Read every available artifact and return a structured data dict."""
    data: dict[str, Any] = {
        "run_dir": str(run_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    # ── run_config.json ──────────────────────────────────────────────────
    rc = _load_json(run_dir / "run_config.json")
    if rc:
        data["run_config"] = rc
        data["usgs_id"] = rc.get("usgs_id", "")
        data["status"] = rc.get("status", "UNKNOWN")
        data["start_date"] = rc.get("start_date", "")
        data["end_date"] = rc.get("end_date", "")
        data["model_family"] = rc.get("model_family", "")
        data["warmup_years"] = rc.get("warmup_years", 0)
        data["hru_mode"] = rc.get("hru_mode_requested", "")
        data["locked_calibration_ready"] = rc.get("locked_calibration_ready", False)

    # ── evidence_summary.json ────────────────────────────────────────────
    ev = _load_json(run_dir / "evidence_summary.json")
    if ev:
        data["evidence"] = ev
        data["claim_tier"] = ev.get("claim_tier", "")
        data["effective_claim_tier"] = ev.get("effective_claim_tier", "")
        data["blocker_class"] = ev.get("blocker_class", "")
        data["gates_passed"] = ev.get("gates_passed", [])
        data["gates_failed"] = ev.get("gates_failed", [])
        data["allowed_claims"] = ev.get("allowed_claims", [])
        data["blocked_claims"] = ev.get("blocked_claims", [])

    # ── metrics.json ─────────────────────────────────────────────────────
    metrics = _load_json(run_dir / "reports" / "metrics.json")
    if not metrics:
        metrics = _load_json(run_dir / "benchmark" / "metrics.json")
    if metrics:
        data["metrics"] = _coerce_metrics(metrics)

    # ── alignment.csv (observed vs simulated daily flow) ─────────────────
    alignment_csv = run_dir / "outputs" / "alignment.csv"
    if alignment_csv.is_file():
        data["alignment"] = _read_alignment(alignment_csv)
    # Also check alternates from calibration
    for alt in [
        run_dir / "benchmark" / "alignment.csv",
        run_dir / "benchmark" / "alignment_calibration.csv",
    ]:
        if alt.is_file() and not data.get("alignment"):
            data["alignment"] = _read_alignment(alt)
            data["alignment_source"] = str(alt)
    # Build seasonal (monthly) aggregation from alignment data
    if data.get("alignment"):
        data["seasonal"] = _build_seasonal(data["alignment"])

    # ── physical_gates.json ──────────────────────────────────────────────
    phys = _load_json(run_dir / "physical_gates.json")
    if phys:
        data["physical_gates"] = phys
        data["physical_gates_status"] = phys.get("status", "unknown")

    # ── routing_flow_gates.json ──────────────────────────────────────────
    rout = _load_json(run_dir / "routing_flow_gates.json")
    if rout:
        data["routing_gates"] = rout
        data["routing_gates_status"] = rout.get("status", "unknown")

    # ── calibration_provenance.json ──────────────────────────────────────
    cal = _load_json(run_dir / "calibration_provenance.json")
    if cal:
        data["calibration"] = cal
        data["calibration_status"] = cal.get("status", "not_attempted")
        provenance = cal.get("provenance", {}) if isinstance(cal.get("provenance"), dict) else {}
        data["calibration_success"] = cal.get("success", False)
        data["calibration_delta_nse"] = provenance.get("delta_nse")
        data["calibration_delta_kge"] = provenance.get("delta_kge")
        data["calibration_final_nse"] = provenance.get("final_nse")
        data["calibration_final_kge"] = provenance.get("final_kge")
        data["calibration_final_pbias"] = provenance.get("final_pbias")

    # ── parameter_screen.json ────────────────────────────────────────────
    ps = _load_json(run_dir / "parameter_screen.json")
    if ps:
        data["parameter_screen"] = ps

    # ── Calibration history and best solution ────────────────────────────
    history_csv = run_dir / "calibration" / "reports" / "history.csv"
    if history_csv.is_file():
        data["calibration_history"] = _read_history_csv(history_csv)
    best_sol = _load_json(run_dir / "calibration" / "reports" / "best_solution.json")
    if best_sol:
        data["best_solution"] = best_sol

    # ── Water balance (reuse existing module) ────────────────────────────
    try:
        from .plots.water_balance import summarize_water_balance as _summarize_wb

        wb = _summarize_wb(run_dir)
        data["water_balance"] = {
            "precip": wb.precip,
            "et": wb.et,
            "surq_gen": wb.surq_gen,
            "latq": wb.latq,
            "perc": wb.perc,
            "wateryld": wb.wateryld,
            "residual": wb.residual,
            "source_file": wb.source_file,
            "n_years": len(wb.years),
        }
    except Exception as exc:
        log.debug("Water balance from existing module failed: %s", exc)
        data["water_balance"] = _collect_water_balance_fallback(run_dir)

    # ── Spatial overview plot (embed as resized base64 if available) ─────
    for name in ("fig_08_basin_spatial_overview.png",):
        img = run_dir / "plots" / name
        if img.is_file():
            try:
                data["spatial_overview_base64"] = _image_to_base64_resized(img, max_width=1200)
            except Exception as exc:
                log.debug("Could not embed spatial overview: %s", exc)
            break

    # ── Land use composition ─────────────────────────────────────────────
    landuse_json = run_dir / "reports" / "landuse_fidelity.json"
    if not landuse_json.is_file():
        landuse_json = run_dir / "landuse_fidelity.json"
    if landuse_json.is_file():
        data["landuse_fidelity"] = _load_json(landuse_json)

    # ── Soil report ──────────────────────────────────────────────────────
    soil_json = run_dir / "reports" / "soil_report.json"
    if soil_json.is_file():
        data["soil_report"] = _load_json(soil_json)

    # ── Metadata ─────────────────────────────────────────────────────────
    meta = _load_json(run_dir / "metadata.json")
    if meta:
        data["metadata"] = meta

    # ── Basin delineation area ───────────────────────────────────────────
    delin_json = run_dir / "delin" / "validation_result.json"
    if delin_json.is_file():
        data["delineation"] = _load_json(delin_json)

    return data


def _build_seasonal(alignment: dict[str, Any]) -> dict[str, Any] | None:
    """Build monthly aggregation from daily alignment data.

    Returns ``{months: [...], obs_mean: [...], sim_mean: [...], obs_total: [...], sim_total: [...]}``.
    """
    dates = alignment.get("dates", [])
    obs = alignment.get("obs", [])
    sim = alignment.get("sim", [])
    if not dates or not obs or not sim or len(dates) != len(obs):
        return None
    # Aggregate by month
    month_obs_sum: dict[int, float] = {}
    month_sim_sum: dict[int, float] = {}
    month_count: dict[int, int] = {}
    for i, ds in enumerate(dates):
        try:
            # Parse date; format varies (ISO or YYYY-MM-DD)
            m = int(str(ds).split("-")[1]) if "-" in str(ds) else None
            if m is None or m < 1 or m > 12:
                continue
        except (ValueError, IndexError):
            continue
        month_obs_sum[m] = month_obs_sum.get(m, 0.0) + float(obs[i] or 0)
        month_sim_sum[m] = month_sim_sum.get(m, 0.0) + float(sim[i] or 0)
        month_count[m] = month_count.get(m, 0) + 1
    if not month_count:
        return None
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return {
        "months": [month_names[m - 1] for m in sorted(month_count)],
        "obs_mean": [month_obs_sum[m] / max(month_count[m], 1) for m in sorted(month_count)],
        "sim_mean": [month_sim_sum[m] / max(month_count[m], 1) for m in sorted(month_count)],
        "obs_total": [month_obs_sum[m] for m in sorted(month_count)],
        "sim_total": [month_sim_sum[m] for m in sorted(month_count)],
    }


# ── HTML rendering ────────────────────────────────────────────────────────────


def _render_html(data: dict[str, Any]) -> str:
    """Render the complete self-contained dashboard HTML."""
    data_json = json.dumps(data, default=str, indent=None)
    usgs_id = str(data.get("usgs_id", ""))
    # HTML-escape the title text
    title_text = usgs_id.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SWAT+ Dashboard — USGS {title_text}</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
{_css()}
</style>
</head>
<body>
<div id="dashboard-root"></div>
<script type="application/json" id="dashboard-data">
{data_json}
</script>
<script>
{_javascript()}
</script>
</body>
</html>"""


# ── CSS ───────────────────────────────────────────────────────────────────────


def _css() -> str:
    return """
:root {
  --bg: #f4f6f9;
  --card-bg: #ffffff;
  --text: #1a2332;
  --text-muted: #5a6c7d;
  --border: #e2e8f0;
  --accent: #2563eb;
  --accent-light: #dbeafe;
  --success: #059669;
  --success-bg: #d1fae5;
  --warning: #d97706;
  --warning-bg: #fef3c7;
  --danger: #dc2626;
  --danger-bg: #fee2e2;
  --info: #7c3aed;
  --info-bg: #ede9fe;
  --radius: 12px;
  --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
  --shadow-lg: 0 4px 12px rgba(0,0,0,.10);
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}

/* ── Layout ─────────────────────── */
.container { max-width: 1400px; margin: 0 auto; padding: 24px 20px 40px; }

/* ── Hero Header ───────────────── */
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #1a2a4a 100%);
  color: #f1f5f9;
  border-radius: var(--radius);
  padding: 32px 36px;
  margin-bottom: 24px;
  box-shadow: var(--shadow-lg);
}
.hero-top { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px; }
.hero-basin { font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; }
.hero-usgs { font-size: 1rem; color: #94a3b8; margin-top: 4px; }
.hero-date { font-size: 0.875rem; color: #94a3b8; margin-top: 2px; }
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.badge-success { background: var(--success-bg); color: var(--success); }
.badge-warning { background: var(--warning-bg); color: var(--warning); }
.badge-danger { background: var(--danger-bg); color: var(--danger); }
.badge-info { background: var(--info-bg); color: var(--info); }
.badge-neutral { background: rgba(255,255,255,.12); color: #cbd5e1; }

.hero-metrics { display: flex; gap: 24px; margin-top: 20px; flex-wrap: wrap; }
.hero-metric { text-align: center; min-width: 80px; }
.hero-metric .val { font-size: 2rem; font-weight: 800; line-height: 1.1; }
.hero-metric .val.good { color: #34d399; }
.hero-metric .val.warn { color: #fbbf24; }
.hero-metric .val.bad { color: #f87171; }
.hero-metric .lbl { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-top: 2px; }

/* ── Grid layout ───────────────── */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 20px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
@media (max-width: 1024px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } .grid-4 { grid-template-columns: 1fr 1fr; } }
@media (max-width: 640px) { .grid-4 { grid-template-columns: 1fr; } }

/* ── Cards ─────────────────────── */
.card {
  background: var(--card-bg); border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 24px;
  border: 1px solid var(--border);
}
.card-full { grid-column: 1 / -1; }
.chart-container { min-height: 400px; }

/* ── No-data placeholder ───────── */
.no-data {
  display: flex; align-items: center; justify-content: center;
  min-height: 300px; color: var(--text-muted); font-size: 0.9rem;
  background: #f8fafc; border-radius: 8px; border: 2px dashed var(--border);
}

/* ── Gate cards ────────────────── */
.gate-card {
  display: flex; align-items: center; gap: 12px; padding: 16px 18px;
  background: var(--card-bg); border-radius: var(--radius);
  box-shadow: var(--shadow); border: 1px solid var(--border);
}
.gate-icon {
  width: 42px; height: 42px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem; flex-shrink: 0;
}
.gate-pass .gate-icon { background: var(--success-bg); color: var(--success); }
.gate-fail .gate-icon { background: var(--danger-bg); color: var(--danger); }
.gate-warn .gate-icon { background: var(--warning-bg); color: var(--warning); }
.gate-info .gate-icon { background: var(--info-bg); color: var(--info); }
.gate-label { font-weight: 600; font-size: 0.85rem; }
.gate-status { font-size: 0.75rem; color: var(--text-muted); }

/* ── Tables ────────────────────── */
.data-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.data-table th {
  text-align: left; padding: 10px 12px; background: #f8fafc;
  border-bottom: 2px solid var(--border); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.72rem;
  color: var(--text-muted);
}
.data-table td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
.data-table tr:hover { background: #f8fafc; }

/* ── Section headings ──────────── */
.section-title {
  font-size: 1.15rem; font-weight: 700; color: var(--text);
  margin-bottom: 0; padding-bottom: 0;
}

/* ── Key-value ─────────────────── */
.kv-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
.kv-row:last-child { border-bottom: none; }
.kv-key { color: var(--text-muted); }
.kv-val { font-weight: 600; }

/* ── Footer ────────────────────── */
.footer { text-align: center; padding: 32px 0 16px; color: var(--text-muted); font-size: 0.78rem; }

/* ── Plotly overrides ──────────── */
.js-plotly-plot .plotly .main-svg { border-radius: 8px; }
"""


# ── JavaScript ────────────────────────────────────────────────────────────────


def _javascript() -> str:
    return r"""
(function() {
  const raw = document.getElementById('dashboard-data').textContent;
  const D = JSON.parse(raw);

  // ── Helpers ──────────────────────────────────────────────────────────
  function $(sel) { return document.querySelector(sel); }
  function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function fmtNum(n, dec) {
    if (n == null || isNaN(n)) return '—';
    if (dec === undefined) dec = 3;
    return Number(n).toFixed(dec);
  }
  function tierBadge(tier) {
    const t = String(tier || '').toLowerCase();
    if (t === 'research_grade') return '<span class="badge badge-success">Research Grade</span>';
    if (t === 'publication_grade') return '<span class="badge badge-info">Publication Grade</span>';
    if (t === 'diagnostic') return '<span class="badge badge-warning">Diagnostic</span>';
    if (t === 'exploratory') return '<span class="badge badge-neutral">Exploratory</span>';
    return '<span class="badge badge-neutral">Exploratory</span>';
  }
  function statusBadge(status) {
    const s = String(status || '').toUpperCase();
    if (s === 'SUCCESS') return '<span class="badge badge-success">Success</span>';
    if (s === 'BLOCKED' || s === 'FAILED') return '<span class="badge badge-danger">Blocked</span>';
    return '<span class="badge badge-warning">' + esc(status || 'Unknown') + '</span>';
  }
  function metricColor(nse, kge, pbias) {
    if (kge != null && kge >= 0.5 && pbias != null && Math.abs(pbias) <= 25) return 'good';
    if (kge != null && kge < -0.5) return 'bad';
    if (nse != null && nse < -1) return 'bad';
    return 'warn';
  }
  function hasAlignment() {
    return D.alignment && D.alignment.dates && D.alignment.dates.length > 0
      && D.alignment.obs && D.alignment.obs.length > 0
      && D.alignment.sim && D.alignment.sim.length > 0;
  }

  // ── Build DOM ────────────────────────────────────────────────────────
  const root = $('#dashboard-root');

  const basin = esc(D.usgs_id || 'Unknown Basin');
  const startDate = D.start_date || '';
  const endDate = D.end_date || '';
  const modelFamily = D.model_family || '';
  const status = D.status || 'UNKNOWN';
  const tier = D.effective_claim_tier || D.claim_tier || 'exploratory';
  const physStatus = D.physical_gates_status || 'unknown';
  const routStatus = D.routing_gates_status || 'unknown';

  const m = D.metrics || {};
  const nse = m.nse != null ? m.nse : (D.run_config && D.run_config.baseline_nse);
  const kge = m.kge != null ? m.kge : (D.run_config && D.run_config.baseline_kge);
  const pbias = m.pbias != null ? m.pbias : (m.pbias_pct != null ? m.pbias_pct : null);
  const bfiSim = m.bfi_sim != null ? m.bfi_sim : (m.bfi != null ? m.bfi : null);
  const bfiObs = m.bfi_obs != null ? m.bfi_obs : null;
  const mc = metricColor(nse, kge, pbias);

  const gatesPassed = D.gates_passed || [];
  const gatesFailed = D.gates_failed || [];

  let html = '';

  // ── Hero ─────────────────────────────────────────────────────────────
  html += '<div class="hero">';
  html += '<div class="hero-top">';
  html += '<div>';
  html += '<div class="hero-basin">USGS ' + basin + '</div>';
  html += '<div class="hero-usgs">Model Family: ' + esc(modelFamily.toUpperCase()) + (D.warmup_years ? ' • Warmup: ' + D.warmup_years + ' yr' : '') + (D.hru_mode ? ' • HRU: ' + esc(D.hru_mode) : '') + '</div>';
  html += '<div class="hero-date">' + esc(startDate) + ' → ' + esc(endDate) + '</div>';
  html += '</div>';
  html += '<div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;">';
  html += statusBadge(status);
  html += tierBadge(tier);
  html += '</div>';
  html += '</div>';

  html += '<div class="hero-metrics">';
  html += '<div class="hero-metric"><div class="val ' + mc + '">' + fmtNum(nse) + '</div><div class="lbl">NSE</div></div>';
  html += '<div class="hero-metric"><div class="val ' + mc + '">' + fmtNum(kge) + '</div><div class="lbl">KGE</div></div>';
  html += '<div class="hero-metric"><div class="val ' + mc + '">' + fmtNum(pbias, 1) + '%</div><div class="lbl">PBIAS</div></div>';
  html += '<div class="hero-metric"><div class="val">' + fmtNum(bfiSim) + '</div><div class="lbl">BFI (sim)</div></div>';
  if (bfiObs != null) {
    html += '<div class="hero-metric"><div class="val">' + fmtNum(bfiObs) + '</div><div class="lbl">BFI (obs)</div></div>';
  }
  html += '</div>';
  html += '</div>';

  // ── Gate Status Grid ─────────────────────────────────────────────────
  const gateDefs = [
    { key: 'contract_policy', label: 'Contract Policy', icon: '\uD83D\uDCCB' },
    { key: 'fresh_engine_output', label: 'Fresh Engine Output', icon: '\u26A1' },
    { key: 'benchmark_lock', label: 'Benchmark Lock', icon: '\uD83D\uDD12' },
    { key: 'outlet_provenance', label: 'Outlet Provenance', icon: '\uD83D\uDCCD' },
    { key: 'physical_gates', label: 'Physical Gates', icon: '\u2696', extra: physStatus },
    { key: 'routing_flow', label: 'Routing Flow', icon: '\uD83C\uDF0A', extra: routStatus },
    { key: 'sensitivity_screen', label: 'Sensitivity Screen', icon: '\uD83D\uDCCA' },
    { key: 'soil_fidelity', label: 'Soil Fidelity', icon: '\uD83C\uDF31' },
    { key: 'landuse_fidelity', label: 'Land Use Fidelity', icon: '\uD83C\uDF3E' },
    { key: 'calibration_verification', label: 'Calibration Verified', icon: '\u2705' },
  ];

  html += '<div class="grid-4" style="margin-bottom:24px;">';
  for (const g of gateDefs) {
    let cls = 'gate-info';
    let statusText = 'Not run';
    if (gatesPassed.includes(g.key)) { cls = 'gate-pass'; statusText = 'Passed'; }
    else if (gatesFailed.includes(g.key)) { cls = 'gate-fail'; statusText = 'Failed'; }
    else if (g.extra && g.extra === 'passed') { cls = 'gate-pass'; statusText = 'Passed'; }
    else if (g.extra && g.extra === 'failed') { cls = 'gate-fail'; statusText = 'Failed'; }
    else if (g.extra && g.extra === 'warning') { cls = 'gate-warn'; statusText = 'Warning'; }
    html += '<div class="gate-card ' + cls + '">';
    html += '<div class="gate-icon">' + g.icon + '</div>';
    html += '<div><div class="gate-label">' + g.label + '</div>';
    html += '<div class="gate-status">' + statusText + '</div></div>';
    html += '</div>';
  }
  html += '</div>';

  // ── Charts Section ────────────────────────────────────────────────────
  html += '<div class="grid-2">';

  // Hydrograph
  html += '<div class="card card-full">';
  html += '<div class="section-title">\uD83D\uDCC8 Hydrograph</div>';
  html += hasAlignment()
    ? '<div id="chart-hydrograph" class="chart-container"></div>'
    : '<div class="no-data">No alignment data available — SWAT+ engine run required</div>';
  html += '</div>';

  // FDC
  html += '<div class="card">';
  html += '<div class="section-title">\uD83D\uDCCA Flow Duration Curve</div>';
  html += hasAlignment()
    ? '<div id="chart-fdc" class="chart-container"></div>'
    : '<div class="no-data">No alignment data available</div>';
  html += '</div>';

  // Scatter
  html += '<div class="card">';
  html += '<div class="section-title">\uD83C\uDFAF Observed vs Simulated</div>';
  html += hasAlignment()
    ? '<div id="chart-scatter" class="chart-container"></div>'
    : '<div class="no-data">No alignment data available</div>';
  html += '</div>';

  html += '</div>';

  // ── BFI Comparison + Seasonal ────────────────────────────────────────
  html += '<div class="grid-2">';

  // BFI comparison
  html += '<div class="card">';
  html += '<div class="section-title">\uD83C\uDF0A Baseflow Index</div>';
  html += (bfiObs != null || bfiSim != null)
    ? '<div id="chart-bfi" class="chart-container" style="min-height:300px;"></div>'
    : '<div class="no-data">BFI not computed</div>';
  html += '</div>';

  // Seasonal
  html += '<div class="card">';
  html += '<div class="section-title">\uD83D\uDCC5 Seasonal Flow</div>';
  html += (D.seasonal && D.seasonal.months && D.seasonal.months.length > 0)
    ? '<div id="chart-seasonal" class="chart-container"></div>'
    : '<div class="no-data">Insufficient data for seasonal aggregation</div>';
  html += '</div>';

  html += '</div>';

  // ── Water Balance + Spatial ──────────────────────────────────────────
  html += '<div class="grid-2">';

  // Water Balance
  html += '<div class="card">';
  html += '<div class="section-title">\uD83D\uDCA7 Water Balance</div>';
  html += (D.water_balance && D.water_balance.precip)
    ? '<div id="chart-waterbalance" class="chart-container"></div>'
    : '<div class="no-data">Water balance data not available</div>';
  html += '</div>';

  // Spatial overview or Run Metadata
  if (D.spatial_overview_base64) {
    html += '<div class="card">';
    html += '<div class="section-title">\uD83D\uDDFA\uFE0F Basin Spatial Overview</div>';
    html += '<div style="text-align:center;overflow:hidden;border-radius:8px;">';
    html += '<img src="data:image/png;base64,' + D.spatial_overview_base64 + '" style="max-width:100%;height:auto;" alt="Basin spatial overview">';
    html += '</div></div>';
  } else {
    html += '<div class="card">';
    html += '<div class="section-title">\uD83D\uDCCA Run Metadata</div>';
    html += _renderMetadataCard(D);
    html += '</div>';
  }
  html += '</div>';

  // ── Calibration Section ──────────────────────────────────────────────
  if (D.calibration && D.calibration.status !== 'not_attempted') {
    html += '<div class="grid-2" style="margin-top:20px;">';

    if (D.best_solution && D.best_solution.parameters) {
      html += '<div class="card">';
      html += '<div class="section-title">\uD83D\uDD27 Calibration Parameters</div>';
      html += '<div id="chart-params" class="chart-container"></div>';
      html += '</div>';
    }

    if (D.calibration_history && D.calibration_history.length > 0) {
      html += '<div class="card">';
      html += '<div class="section-title">\uD83D\uDCC9 Calibration Convergence</div>';
      html += '<div id="chart-convergence" class="chart-container"></div>';
      html += '</div>';
    } else {
      html += '<div class="card">';
      html += '<div class="section-title">\uD83D\uDD27 Calibration Summary</div>';
      html += '<div style="padding:12px 0;">';
      html += _renderCalibrationSummary(D);
      html += '</div></div>';
    }
    html += '</div>';
  }

  // ── Land Use + Soil ──────────────────────────────────────────────────
  if (D.landuse_fidelity || D.soil_report) {
    html += '<div class="grid-2">';
    if (D.landuse_fidelity) {
      html += '<div class="card">';
      html += '<div class="section-title">\uD83C\uDF33 Land Use Composition</div>';
      html += '<div id="chart-landuse" class="chart-container"></div>';
      html += '</div>';
    }
    if (D.soil_report) {
      html += '<div class="card">';
      html += '<div class="section-title">\uD83C\uDF31 Soil Sources</div>';
      html += '<div id="chart-soil" class="chart-container"></div>';
      html += '</div>';
    }
    html += '</div>';
  }

  // ── Claims Tables ────────────────────────────────────────────────────
  if ((D.allowed_claims && D.allowed_claims.length > 0) || (D.blocked_claims && D.blocked_claims.length > 0)) {
    html += '<div class="grid-2">';

    if (D.allowed_claims && D.allowed_claims.length > 0) {
      html += '<div class="card">';
      html += '<div class="section-title" style="color:var(--success);">\u2705 Allowed Claims</div>';
      html += '<table class="data-table"><thead><tr><th>Claim</th><th>Tier</th><th>Basis</th></tr></thead><tbody>';
      for (const c of D.allowed_claims) {
        html += '<tr><td>' + esc(c.claim || '') + '</td><td>' + esc(c.tier || '') + '</td><td style="font-size:0.78rem;color:var(--text-muted);">' + esc(c.basis || '') + '</td></tr>';
      }
      html += '</tbody></table></div>';
    }

    if (D.blocked_claims && D.blocked_claims.length > 0) {
      html += '<div class="card">';
      html += '<div class="section-title" style="color:var(--danger);">\u274C Blocked Claims</div>';
      html += '<table class="data-table"><thead><tr><th>Claim</th><th>Tier</th><th>Reason</th></tr></thead><tbody>';
      for (const c of D.blocked_claims) {
        html += '<tr><td>' + esc(c.claim || '') + '</td><td>' + esc(c.tier || '') + '</td><td style="font-size:0.78rem;color:var(--danger);">' + esc(c.reason || '') + '</td></tr>';
      }
      html += '</tbody></table></div>';
    }

    html += '</div>';
  }

  // ── Run Details ──────────────────────────────────────────────────────
  html += '<div class="card" style="margin-top:20px;">';
  html += '<div class="section-title">\uD83D\uDCCB Run Details</div>';
  html += _renderRunDetails(D);
  html += '</div>';

  // ── Footer ───────────────────────────────────────────────────────────
  html += '<div class="footer">SWAT+ Builder Dashboard • Generated ' + esc(D.generated_at || '') + ' • Run directory: ' + esc(D.run_dir || '') + '</div>';

  root.innerHTML = html;

  // ── Plotly Charts ────────────────────────────────────────────────────

  if (hasAlignment()) {
    // Hydrograph
    Plotly.newPlot('chart-hydrograph', [
      { x: D.alignment.dates, y: D.alignment.obs, type: 'scatter', mode: 'lines',
        name: 'Observed', line: { color: '#1e40af', width: 1.8 } },
      { x: D.alignment.dates, y: D.alignment.sim, type: 'scatter', mode: 'lines',
        name: 'Simulated', line: { color: '#dc2626', width: 1.4 } }
    ], {
      margin: { t: 10, r: 20, b: 40, l: 50 },
      xaxis: { title: '', rangeslider: { visible: true }, type: 'date' },
      yaxis: { title: 'Discharge (m\u00B3/s)', type: 'log' },
      legend: { orientation: 'h', y: 1.15 },
      hovermode: 'x unified',
      paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
    }, { responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] });

    // FDC
    const obsSorted = [...D.alignment.obs].sort((a,b) => b-a);
    const simSorted = [...D.alignment.sim].sort((a,b) => b-a);
    const exceedObs = obsSorted.map((_,i) => (i/(obsSorted.length-1))*100);
    const exceedSim = simSorted.map((_,i) => (i/(simSorted.length-1))*100);
    Plotly.newPlot('chart-fdc', [
      { x: exceedObs, y: obsSorted, type: 'scatter', mode: 'lines', name: 'Observed',
        line: { color: '#1e40af', width: 1.8 } },
      { x: exceedSim, y: simSorted, type: 'scatter', mode: 'lines', name: 'Simulated',
        line: { color: '#dc2626', width: 1.4 } }
    ], {
      margin: { t: 10, r: 20, b: 40, l: 50 },
      xaxis: { title: 'Exceedance Probability (%)' },
      yaxis: { title: 'Discharge (m\u00B3/s)', type: 'log' },
      legend: { orientation: 'h', y: 1.15 },
      paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
    }, { responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] });

    // Scatter
    const maxVal = Math.max(...D.alignment.obs, ...D.alignment.sim) * 1.05;
    Plotly.newPlot('chart-scatter', [
      { x: D.alignment.obs, y: D.alignment.sim, type: 'scatter', mode: 'markers',
        marker: { color: '#2563eb', opacity: 0.35, size: 5 }, name: 'Daily flow' },
      { x: [0, maxVal], y: [0, maxVal], type: 'scatter', mode: 'lines',
        line: { dash: 'dash', color: '#1a2332', width: 1.5 }, name: '1:1 line' }
    ], {
      margin: { t: 10, r: 20, b: 40, l: 50 },
      xaxis: { title: 'Observed (m\u00B3/s)', range: [0, maxVal] },
      yaxis: { title: 'Simulated (m\u00B3/s)', range: [0, maxVal], scaleanchor: 'x', scaleratio: 1 },
      legend: { orientation: 'h', y: 1.15 },
      paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
    }, { responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] });

    // BFI comparison
    if (bfiObs != null || bfiSim != null) {
      const bfiBars = [];
      const bfiLabels = [];
      if (bfiObs != null) { bfiBars.push(bfiObs); bfiLabels.push('Observed'); }
      if (bfiSim != null) { bfiBars.push(bfiSim); bfiLabels.push('Simulated'); }
      Plotly.newPlot('chart-bfi', [
        { x: bfiLabels, y: bfiBars, type: 'bar',
          marker: { color: bfiLabels.map(l => l === 'Observed' ? '#1e40af' : '#dc2626') },
          text: bfiBars.map(v => v.toFixed(3)), textposition: 'outside' }
      ], {
        margin: { t: 10, r: 20, b: 40, l: 50 },
        yaxis: { title: 'Baseflow Index', range: [0, Math.max(bfiObs||0, bfiSim||0, 0.1) * 1.3] },
        paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
      }, { responsive: true, displayModeBar: false });
    }

    // Seasonal
    if (D.seasonal && D.seasonal.months && D.seasonal.months.length > 0) {
      Plotly.newPlot('chart-seasonal', [
        { x: D.seasonal.months, y: D.seasonal.sim_total, type: 'bar',
          name: 'Simulated', marker: { color: '#dc2626', opacity: 0.7 } },
        { x: D.seasonal.months, y: D.seasonal.obs_total, type: 'bar',
          name: 'Observed', marker: { color: '#1e40af', opacity: 0.7 } }
      ], {
        margin: { t: 10, r: 20, b: 40, l: 50 },
        barmode: 'group',
        xaxis: { title: '' }, yaxis: { title: 'Total Monthly Flow (m\u00B3/s)' },
        legend: { orientation: 'h', y: 1.15 },
        paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
      }, { responsive: true, displayModeBar: true });
    }
  }

  // Water Balance
  if (D.water_balance && D.water_balance.precip) {
    const wb = D.water_balance;
    const total = wb.precip || 1;
    const etPct = (wb.et || 0) / total * 100;
    const wyPct = (wb.wateryld || 0) / total * 100;
    const residual = wb.residual != null ? wb.residual : (wb.precip - (wb.et||0) - (wb.wateryld||0));
    const resPct = residual / total * 100;
    // Build slices, omitting zero-value components
    const labels = [], values = [], colors = [];
    if (etPct > 0.5) {
      labels.push('ET (' + (wb.et||0).toFixed(0) + ' mm)');
      values.push(etPct);
      colors.push('#3A7D44');
    }
    if (wyPct > 0.5) {
      labels.push('Water Yield (' + (wb.wateryld||0).toFixed(0) + ' mm)');
      values.push(wyPct);
      colors.push('#2F6FA5');
    }
    if (resPct > 0.5) {
      labels.push('Residual (' + residual.toFixed(0) + ' mm)');
      values.push(resPct);
      colors.push('#C78A2C');
    }
    if (values.length === 0) {
      labels.push('No significant partitions');
      values.push(100);
      colors.push('#cbd5e1');
    }
    Plotly.newPlot('chart-waterbalance', [
      { labels: labels, values: values, type: 'pie', hole: 0.45,
        marker: { colors: colors },
        textinfo: 'label+percent', textposition: 'outside',
        hoverinfo: 'label+value' }
    ], {
      margin: { t: 10, r: 10, b: 10, l: 10 },
      annotations: [{ text: 'P=' + total.toFixed(0) + ' mm', showarrow: false, font: { size: 16 } }],
      paper_bgcolor: '#fff'
    }, { responsive: true, displayModeBar: false });
  }

  // ── Calibration convergence ──────────────────────────────────────────
  if (D.calibration_history && D.calibration_history.length > 0) {
    const hist = D.calibration_history;
    const iterNse = hist.filter(h => (h.nse || h.metric_nse) != null);
    if (iterNse.length > 0) {
      Plotly.newPlot('chart-convergence', [
        { x: iterNse.map(h => h.iteration), y: iterNse.map(h => h.nse || h.metric_nse),
          type: 'scatter', mode: 'lines+markers',
          marker: { size: 5 }, line: { width: 1.5 }, name: 'NSE' }
      ], {
        margin: { t: 10, r: 20, b: 40, l: 50 },
        xaxis: { title: 'Iteration' }, yaxis: { title: 'NSE' },
        paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
      }, { responsive: true, displayModeBar: true });
    }
  }

  // ── Parameter comparison ─────────────────────────────────────────────
  if (D.best_solution && D.best_solution.parameters) {
    const params = D.best_solution.parameters;
    const names = Object.keys(params).sort();
    Plotly.newPlot('chart-params', [
      { x: names, y: names.map(n => params[n]), type: 'bar',
        marker: { color: '#2563eb' }, name: 'Calibrated' }
    ], {
      margin: { t: 10, r: 20, b: 60, l: 50 },
      xaxis: { title: '', tickangle: -45 }, yaxis: { title: 'Value' },
      paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
    }, { responsive: true, displayModeBar: true });
  }

  // ── Land Use ─────────────────────────────────────────────────────────
  if (D.landuse_fidelity) {
    const lu = D.landuse_fidelity;
    const classes = lu.landuse_classes_present || lu.landuse_distribution || [];
    if (classes && classes.length > 0) {
      const names = classes.map(c => (typeof c === 'string' ? c : (c.name || c.label || c.landuse || '')));
      const areas = classes.map(c => (typeof c === 'object' ? (c.area_km2 || c.area_pct || c.fraction) : 1));
      Plotly.newPlot('chart-landuse', [
        { labels: names, values: areas, type: 'pie', hole: 0.4,
          textinfo: 'label+percent', textposition: 'outside' }
      ], {
        margin: { t: 10, r: 10, b: 10, l: 10 }, paper_bgcolor: '#fff'
      }, { responsive: true, displayModeBar: false });
    }
  }

  // ── Soil sources ─────────────────────────────────────────────────────
  if (D.soil_report) {
    const sr = D.soil_report;
    const sources = sr.components || sr.sources || [];
    if (sources && sources.length > 0) {
      const names = sources.map(s => s.name || s.source || s.mukey || '');
      const areas = sources.map(s => s.area_km2 || s.area_pct || s.fraction || 1);
      Plotly.newPlot('chart-soil', [
        { labels: names, values: areas, type: 'pie', hole: 0.4,
          textinfo: 'label+percent', textposition: 'outside' }
      ], {
        margin: { t: 10, r: 10, b: 10, l: 10 }, paper_bgcolor: '#fff'
      }, { responsive: true, displayModeBar: false });
    }
  }

  // ── Helper render functions ──────────────────────────────────────────
  function _renderCalibrationSummary(D) {
    const p = D.calibration.provenance || {};
    let h = '';
    h += '<div class="kv-row"><span class="kv-key">Status</span><span class="kv-val">' + esc(D.calibration_status || 'unknown') + '</span></div>';
    if (p.final_nse != null) h += '<div class="kv-row"><span class="kv-key">Final NSE</span><span class="kv-val">' + fmtNum(p.final_nse) + '</span></div>';
    if (p.final_kge != null) h += '<div class="kv-row"><span class="kv-key">Final KGE</span><span class="kv-val">' + fmtNum(p.final_kge) + '</span></div>';
    if (p.delta_nse != null) h += '<div class="kv-row"><span class="kv-key">\u0394NSE</span><span class="kv-val">' + fmtNum(p.delta_nse) + '</span></div>';
    if (p.delta_kge != null) h += '<div class="kv-row"><span class="kv-key">\u0394KGE</span><span class="kv-val">' + fmtNum(p.delta_kge) + '</span></div>';
    return h;
  }

  function _renderMetadataCard(D) {
    let h = '';
    const keys = [
      ['USGS ID', D.usgs_id],
      ['Model Family', D.model_family],
      ['HRU Mode', D.hru_mode],
      ['Start', D.start_date],
      ['End', D.end_date],
      ['Warmup Years', D.warmup_years],
      ['Run Status', D.status],
      ['Claim Tier', D.effective_claim_tier || D.claim_tier],
      ['Blocker', D.blocker_class || 'none'],
      ['Physical Gates', D.physical_gates_status],
      ['Routing Gates', D.routing_gates_status],
      ['Calibration', D.calibration_status],
    ];
    for (const [k, v] of keys) {
      if (v != null && v !== '') h += '<div class="kv-row"><span class="kv-key">' + k + '</span><span class="kv-val">' + esc(String(v)) + '</span></div>';
    }
    return h;
  }

  function _renderRunDetails(D) {
    let h = '';
    const details = [
      ['Run Directory', D.run_dir],
      ['Generated At', D.generated_at],
      ['Status', D.status],
      ['Claim Tier', D.effective_claim_tier || D.claim_tier],
      ['Gates Passed', (D.gates_passed || []).join(', ') || 'none'],
      ['Gates Failed', (D.gates_failed || []).join(', ') || 'none'],
    ];
    if (D.metrics) {
      details.push(['NSE', fmtNum(D.metrics.nse)]);
      details.push(['KGE', fmtNum(D.metrics.kge)]);
      details.push(['PBIAS', fmtNum(D.metrics.pbias, 1) + '%']);
      if (D.metrics.bfi_sim != null) details.push(['BFI (sim)', fmtNum(D.metrics.bfi_sim)]);
      if (D.metrics.bfi_obs != null) details.push(['BFI (obs)', fmtNum(D.metrics.bfi_obs)]);
    }
    if (D.calibration) {
      details.push(['Calibration Status', D.calibration_status]);
      details.push(['Calibration Success', String(D.calibration_success || false)]);
    }
    if (D.delineation && D.delineation.delineated_area_km2) {
      details.push(['Delineated Area', fmtNum(D.delineation.delineated_area_km2, 2) + ' km\u00B2']);
    }
    if (D.water_balance) {
      details.push(['Source File', D.water_balance.source_file || '']);
    }
    details.push(['Dashboard generated', D.generated_at]);
    for (const [k, v] of details) {
      if (v != null && v !== '') h += '<div class="kv-row"><span class="kv-key">' + k + '</span><span class="kv-val">' + esc(String(v)) + '</span></div>';
    }
    return h;
  }

})();
"""


# ── Data helpers ──────────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON, returning None on any failure."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.debug("Could not load %s: %s", path, exc)
        return None


def _coerce_metrics(metrics: dict) -> dict[str, Any]:
    """Ensure metric values are floats, not strings."""
    out: dict[str, Any] = {}
    for k, v in metrics.items():
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def _read_alignment(path: Path):
    """Read alignment.csv into date/obs/sim arrays for Plotly.

    Downsamples to ~5000 points max for browser performance.
    """
    import csv

    dates, obs_vals, sim_vals = [], [], []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dates.append(row[reader.fieldnames[0]])
                obs_vals.append(float(row.get("obs", 0)))
                sim_vals.append(float(row.get("sim", 0)))
            except (ValueError, KeyError, IndexError):
                continue
    n = len(dates)
    if n <= 5000:
        return {"dates": dates, "obs": obs_vals, "sim": sim_vals}
    # Downsample to ~5000 points: take every ceil(n/5000)-th point
    import math
    step = math.ceil(n / 5000)
    return {
        "dates": dates[::step],
        "obs": obs_vals[::step],
        "sim": sim_vals[::step],
    }


def _read_history_csv(path: Path) -> list[dict[str, Any]]:
    """Read calibration history CSV into list of rows.

    Normalises metric field names so JS always reads ``nse`` / ``kge``.
    """
    import csv

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out: dict[str, Any] = {}
            for k, v in row.items():
                try:
                    out[k] = float(v)
                except (ValueError, TypeError):
                    out[k] = v
            # Normalise: field may be "nse" or "metric_nse"
            if "nse" not in out and "metric_nse" in out:
                out["nse"] = out["metric_nse"]
            if "kge" not in out and "metric_kge" in out:
                out["kge"] = out["metric_kge"]
            rows.append(out)
    return rows


def _collect_water_balance_fallback(run_dir: Path) -> dict[str, Any] | None:
    """Fallback: read SWAT+ basin_wb_aa.txt directly when the plot module fails."""
    txt = None
    for candidate in [
        run_dir / "TxtInOut",
        run_dir / "project" / "Scenarios" / "Default" / "TxtInOut",
    ]:
        if candidate.is_dir():
            txt = candidate
            break
    if txt is None:
        return None

    for name in ("basin_wb_aa.txt", "basin_wb_yr.txt"):
        wb_path = txt / name
        if not wb_path.is_file():
            continue
        try:
            rows = _read_basin_wb(wb_path)
            if not rows:
                continue
            keys = ["precip", "et", "surq_gen", "latq", "perc", "wateryld"]
            means: dict[str, float] = {}
            for key in keys:
                vals = [r[key] for r in rows if key in r]
                if vals:
                    means[key] = sum(vals) / len(vals)
            if "precip" in means:
                residual = means.get("precip", 0) - means.get("et", 0) - means.get("wateryld", 0)
                return {
                    "precip": means.get("precip"),
                    "et": means.get("et"),
                    "surq_gen": means.get("surq_gen"),
                    "latq": means.get("latq"),
                    "perc": means.get("perc"),
                    "wateryld": means.get("wateryld"),
                    "residual": residual,
                    "source_file": name,
                    "n_years": len(rows),
                }
        except Exception as exc:
            log.debug("Could not parse %s: %s", wb_path, exc)
    return None


def _read_basin_wb(path: Path) -> list[dict[str, float]]:
    """Parse SWAT+ basin water balance file into list of annual rows."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        tokens = line.split()
        if "precip" in tokens and "et" in tokens:
            header_idx = i
            break
    if header_idx is None:
        return []
    columns = lines[header_idx].split()
    rows: list[dict[str, float]] = []
    for line in lines[header_idx + 1 :]:
        tokens = line.split()
        if len(tokens) < len(columns):
            continue
        try:
            float(tokens[columns.index("precip")])
        except (ValueError, IndexError):
            continue
        row: dict[str, float] = {}
        for idx, col in enumerate(columns):
            try:
                row[col] = float(tokens[idx])
            except (ValueError, IndexError):
                pass
        if row:
            rows.append(row)
    return rows


def _image_to_base64_resized(path: Path, max_width: int = 1200) -> str:
    """Read an image, optionally resize, and return base64-encoded string."""
    import base64

    try:
        from PIL import Image
        import io

        img = Image.open(path)
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except ImportError:
        log.debug("Pillow not installed; embedding full-resolution image")
        return base64.b64encode(path.read_bytes()).decode("ascii")
