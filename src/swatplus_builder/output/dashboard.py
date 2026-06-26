"""Self-contained interactive HTML dashboard for SWAT+ model evidence.

Generates a single ``dashboard.html`` that hydrologists can open directly in a
browser — no server or install. Run data and spatial previews are embedded;
Plotly, Leaflet, and the optional OpenStreetMap basemap are loaded from CDNs.

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
        data["execution_status"] = rc.get("status", "UNKNOWN")
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
        data["governance_evaluated"] = True
        data["workflow_success"] = bool(ev.get("success"))
        evidence_status = str(ev.get("status") or "").lower()
        if evidence_status in {"pipeline_blocked", "failed", "blocked"} or ev.get("success") is False:
            data["status"] = "BLOCKED"
        elif ev.get("success") is True:
            data["status"] = "SUCCESS"
        data["claim_tier"] = ev.get("claim_tier", "")
        data["effective_claim_tier"] = ev.get("effective_claim_tier", "")
        data["blocker_class"] = ev.get("blocker_class", "")
        data["gates_passed"] = ev.get("gates_passed", [])
        data["gates_failed"] = ev.get("gates_failed", [])
        data["allowed_claims"] = ev.get("allowed_claims", [])
        data["blocked_claims"] = ev.get("blocked_claims", [])
    else:
        data["governance_evaluated"] = False

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
    provenance: dict[str, Any] = {}
    if cal:
        data["calibration"] = cal
        data["calibration_status"] = cal.get("status", "not_attempted")
        provenance = cal.get("provenance", {}) if isinstance(cal.get("provenance"), dict) else {}
        data["calibration_success"] = cal.get("success", False)
        data["calibration_strategy"] = provenance.get("calibration_strategy")
        data["calibration_method"] = provenance.get("calibration_method")
        data["calibration_claim_status"] = provenance.get("calibration_claim_status")
        data["calibration_protocol"] = provenance.get("calibration_protocol", [])
        data["calibration_screening_window"] = provenance.get("screening_window")
        data["calibration_final_authority"] = provenance.get("final_metrics_authority")
        data["temporary_candidate_metrics_allowed_as_final"] = provenance.get(
            "temporary_candidate_metrics_allowed_as_final"
        )
        verification_metrics = provenance.get("verification_metrics")
        benchmark_metrics = provenance.get("benchmark_metrics")
        delta_metrics = provenance.get("verification_delta_metrics")
        if isinstance(verification_metrics, dict):
            data["calibration_verification_metrics"] = _coerce_metrics(verification_metrics)
            data["calibration_final_nse"] = verification_metrics.get("nse")
            data["calibration_final_kge"] = verification_metrics.get("kge")
            data["calibration_final_pbias"] = verification_metrics.get("pbias")
        else:
            data["calibration_final_nse"] = provenance.get("final_nse")
            data["calibration_final_kge"] = provenance.get("final_kge")
            data["calibration_final_pbias"] = provenance.get("final_pbias")
        if isinstance(benchmark_metrics, dict):
            data["calibration_benchmark_metrics"] = _coerce_metrics(benchmark_metrics)
        if isinstance(delta_metrics, dict):
            data["calibration_delta_metrics"] = _coerce_metrics(delta_metrics)
            data["calibration_delta_nse"] = delta_metrics.get("nse")
            data["calibration_delta_kge"] = delta_metrics.get("kge")
        else:
            data["calibration_delta_nse"] = provenance.get("delta_nse")
            data["calibration_delta_kge"] = provenance.get("delta_kge")

    # ── parameter_screen.json ────────────────────────────────────────────
    ps = _load_json(run_dir / "parameter_screen.json")
    if ps:
        data["parameter_screen"] = ps

    # ── Calibration history and best solution ────────────────────────────
    history_csv = _first_existing(
        [
            _path_from_value(provenance.get("history_csv")),
            run_dir / "calibration" / "calibration_reports_locked" / "history.csv",
            run_dir / "calibration" / "reports" / "history.csv",
        ]
    )
    if history_csv is not None:
        data["calibration_history"] = _read_history_csv(history_csv)
        data["calibration_history_csv"] = str(history_csv)
    best_solution_path = _first_existing(
        [
            _path_from_value(provenance.get("best_solution_json")),
            run_dir / "calibration" / "calibration_reports_locked" / "best_solution.json",
            run_dir / "calibration" / "reports" / "best_solution.json",
        ]
    )
    best_sol = _load_json(best_solution_path) if best_solution_path is not None else None
    if best_sol:
        data["best_solution"] = best_sol
        data["best_solution_path"] = str(best_solution_path)

    progress_path = _first_existing(
        [
            _path_from_value(provenance.get("calibration_progress_json")),
            run_dir / "calibration" / "calibration_reports_locked" / "calibration_progress.json",
            run_dir / "calibration" / "reports" / "calibration_progress.json",
        ]
    )
    progress = _load_json(progress_path) if progress_path is not None else None
    if progress:
        data["calibration_progress"] = progress
        data["calibration_progress_path"] = str(progress_path)

    locked_txt = _path_from_value(provenance.get("locked_calibrated_txtinout"))
    calibrated_alignment = _first_existing(
        [
            locked_txt / "alignment_calibration.csv" if locked_txt is not None else None,
            run_dir / "benchmark" / "alignment_calibration.csv",
        ]
    )
    if calibrated_alignment is not None:
        data["calibrated_alignment"] = _read_alignment(calibrated_alignment)
        data["calibrated_alignment_source"] = str(calibrated_alignment)

    hydrograph = provenance.get("hydrograph_comparison")
    if isinstance(hydrograph, dict):
        data["calibration_hydrograph"] = hydrograph
    skill = provenance.get("skill_diagnostics")
    if isinstance(skill, dict):
        data["calibration_skill_diagnostics"] = skill

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

    spatial = _collect_spatial_map(run_dir)
    if spatial:
        data["spatial_map"] = spatial

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
    # Prevent artifact text containing ``</script>`` from terminating the JSON
    # script element and becoming executable HTML.
    data_json = json.dumps(data, default=str, indent=None).replace("</", "<\\/")
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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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
.map-container { height: 620px; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.map-legend {
  background: rgba(255,255,255,.96); padding: 8px 10px; border-radius: 4px;
  box-shadow: var(--shadow); font-size: 0.75rem; line-height: 1.45;
}
.north-arrow {
  background: rgba(255,255,255,.92); padding: 5px 9px; border-radius: 4px;
  box-shadow: var(--shadow); font-weight: 800; font-size: 1rem; text-align: center;
}
.notice {
  padding: 14px 16px; margin-bottom: 20px; border-left: 4px solid var(--warning);
  background: var(--warning-bg); color: #6b4508; font-size: 0.88rem;
}
.notice-danger { border-left-color: var(--danger); background: var(--danger-bg); color: #7f1d1d; }

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
    if (s === 'SUCCESS' && D.governance_evaluated) return '<span class="badge badge-success">Governed run complete</span>';
    if (s === 'SUCCESS') return '<span class="badge badge-info">Engine completed</span>';
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
  function hasCalibratedAlignment() {
    return D.calibrated_alignment && D.calibrated_alignment.dates && D.calibrated_alignment.dates.length > 0
      && D.calibrated_alignment.sim && D.calibrated_alignment.sim.length > 0;
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

  if (!D.governance_evaluated) {
    html += '<div class="notice">Scientific claim governance was not evaluated for this lower-level run. Engine completion does not mean the model is scientifically accepted.</div>';
  }
  if (D.delineation) {
    const areaDiff = Number(D.delineation.area_diff_pct);
    const iou = Number(D.delineation.iou_pct);
    if ((Number.isFinite(areaDiff) && Math.abs(areaDiff) > 10) || (Number.isFinite(iou) && iou < 85)) {
      html += '<div class="notice notice-danger"><strong>Spatial fidelity warning.</strong> ';
      html += 'Delineated area difference: ' + fmtNum(areaDiff, 1) + '%; overlap (IoU): ' + fmtNum(iou, 1) + '%. ';
      html += 'Do not interpret performance metrics as gauge-representative until the delineation is repaired.</div>';
    }
  }

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

  // ── Spatial inspector ────────────────────────────────────────────────
  if (D.spatial_map && D.spatial_map.layers && D.spatial_map.layers.length > 0) {
    html += '<div class="card" style="margin-bottom:20px;">';
    html += '<div class="section-title">Basin and model spatial inspector</div>';
    html += '<div style="color:var(--text-muted);font-size:.8rem;margin:4px 0 12px;">Toggle watershed, subbasins, stream network, outlet, HRUs, and available raster layers.</div>';
    html += '<div id="model-map" class="map-container"></div>';
    html += '</div>';
  }

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

    html += '<div class="card">';
    html += '<div class="section-title">\uD83D\uDD27 Calibration Method and Evidence</div>';
    html += '<div style="padding:12px 0;">';
    html += _renderCalibrationSummary(D);
    html += '</div></div>';

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
      html += _renderSoilSummary(D.soil_report);
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

  if (D.spatial_map && D.spatial_map.layers && D.spatial_map.layers.length > 0 && window.L) {
    const modelMap = L.map('model-map', { preferCanvas: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(modelMap);
    const overlays = {};
    const styleByKind = {
      basin: { color: '#111827', weight: 3, fillColor: '#bfdbfe', fillOpacity: 0.12 },
      subbasins: { color: '#2563eb', weight: 1, fillColor: '#60a5fa', fillOpacity: 0.08 },
      channels: { color: '#0891b2', weight: 2.2, opacity: 0.9 },
      outlets: { radius: 7, color: '#7f1d1d', weight: 2, fillColor: '#ef4444', fillOpacity: 1 },
      hrus: { color: '#4d7c0f', weight: 0.45, fillColor: '#84cc16', fillOpacity: 0.09 }
    };
    let combinedBounds = null;
    for (const layerDef of D.spatial_map.layers) {
      let layer = null;
      if (layerDef.type === 'geojson' && layerDef.data) {
        const style = styleByKind[layerDef.kind] || styleByKind.subbasins;
        layer = L.geoJSON(layerDef.data, {
          style: () => style,
          pointToLayer: (_feature, latlng) => L.circleMarker(latlng, style),
          onEachFeature: (feature, item) => {
            const props = feature.properties || {};
            const rows = Object.keys(props).slice(0, 10).map(k => '<strong>' + esc(k) + ':</strong> ' + esc(props[k])).join('<br>');
            if (rows) item.bindPopup(rows);
          }
        });
      } else if (layerDef.type === 'raster' && layerDef.image && layerDef.bounds) {
        layer = L.imageOverlay('data:image/png;base64,' + layerDef.image, layerDef.bounds, {
          opacity: layerDef.opacity || 0.62,
          interactive: false
        });
      }
      if (!layer) continue;
      overlays[layerDef.label] = layer;
      if (layerDef.visible !== false) layer.addTo(modelMap);
      if (layer.getBounds) {
        const b = layer.getBounds();
        if (b.isValid()) combinedBounds = combinedBounds ? combinedBounds.extend(b) : b;
      }
    }
    L.control.layers(null, overlays, { collapsed: false }).addTo(modelMap);
    L.control.scale({ imperial: true, metric: true }).addTo(modelMap);
    const north = L.control({ position: 'topright' });
    north.onAdd = function() {
      const div = L.DomUtil.create('div', 'north-arrow');
      div.innerHTML = 'N<br><span style="font-size:1.25rem">↑</span>';
      return div;
    };
    north.addTo(modelMap);
    if (combinedBounds && combinedBounds.isValid()) modelMap.fitBounds(combinedBounds.pad(0.05));
    else modelMap.setView([39.5, -98.35], 4);
  }

  if (hasAlignment()) {
    // Hydrograph
    const hydroTraces = [
      { x: D.alignment.dates, y: D.alignment.obs, type: 'scatter', mode: 'lines',
        name: 'Observed', line: { color: '#1e40af', width: 1.8 } },
      { x: D.alignment.dates, y: D.alignment.sim, type: 'scatter', mode: 'lines',
        name: 'Simulated', line: { color: '#dc2626', width: 1.4 } }
    ];
    if (hasCalibratedAlignment()) {
      hydroTraces.push({ x: D.calibrated_alignment.dates, y: D.calibrated_alignment.sim, type: 'scatter', mode: 'lines',
        name: 'Calibrated locked rerun', line: { color: '#059669', width: 1.6 } });
    }
    Plotly.newPlot('chart-hydrograph', hydroTraces, {
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
    const fdcTraces = [
      { x: exceedObs, y: obsSorted, type: 'scatter', mode: 'lines', name: 'Observed',
        line: { color: '#1e40af', width: 1.8 } },
      { x: exceedSim, y: simSorted, type: 'scatter', mode: 'lines', name: 'Simulated',
        line: { color: '#dc2626', width: 1.4 } }
    ];
    if (hasCalibratedAlignment()) {
      const calSorted = [...D.calibrated_alignment.sim].sort((a,b) => b-a);
      const exceedCal = calSorted.map((_,i) => (i/(calSorted.length-1))*100);
      fdcTraces.push({ x: exceedCal, y: calSorted, type: 'scatter', mode: 'lines', name: 'Calibrated',
        line: { color: '#059669', width: 1.6 } });
    }
    Plotly.newPlot('chart-fdc', fdcTraces, {
      margin: { t: 10, r: 20, b: 40, l: 50 },
      xaxis: { title: 'Exceedance Probability (%)' },
      yaxis: { title: 'Discharge (m\u00B3/s)', type: 'log' },
      legend: { orientation: 'h', y: 1.15 },
      paper_bgcolor: '#fff', plot_bgcolor: '#fafbfc'
    }, { responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] });

    // Scatter
    const maxVal = Math.max(
      ...D.alignment.obs,
      ...D.alignment.sim,
      ...(hasCalibratedAlignment() ? D.calibrated_alignment.sim : [])
    ) * 1.05;
    const scatterTraces = [
      { x: D.alignment.obs, y: D.alignment.sim, type: 'scatter', mode: 'markers',
        marker: { color: '#2563eb', opacity: 0.35, size: 5 }, name: 'Daily flow' },
      { x: [0, maxVal], y: [0, maxVal], type: 'scatter', mode: 'lines',
        line: { dash: 'dash', color: '#1a2332', width: 1.5 }, name: '1:1 line' }
    ];
    if (hasCalibratedAlignment()) {
      scatterTraces.splice(1, 0, { x: D.calibrated_alignment.obs, y: D.calibrated_alignment.sim, type: 'scatter', mode: 'markers',
        marker: { color: '#059669', opacity: 0.28, size: 5 }, name: 'Calibrated daily flow' });
    }
    Plotly.newPlot('chart-scatter', scatterTraces, {
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
        { x: iterNse.map((h, i) => h.eval_idx != null ? h.eval_idx : (h.iteration != null ? h.iteration : i)),
          y: iterNse.map(h => h.nse || h.metric_nse),
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

  // ── Helper render functions ──────────────────────────────────────────
  function _renderCalibrationSummary(D) {
    const p = D.calibration.provenance || {};
    const bench = D.calibration_benchmark_metrics || {};
    const verify = D.calibration_verification_metrics || {};
    const delta = D.calibration_delta_metrics || {};
    const window = D.calibration_screening_window || (D.best_solution && D.best_solution.screening_window) || null;
    let h = '';
    h += '<div class="kv-row"><span class="kv-key">Status</span><span class="kv-val">' + esc(D.calibration_status || 'unknown') + '</span></div>';
    if (D.calibration_strategy || D.calibration_method) h += '<div class="kv-row"><span class="kv-key">Strategy</span><span class="kv-val">' + esc(D.calibration_strategy || D.calibration_method) + '</span></div>';
    if (D.calibration_claim_status) h += '<div class="kv-row"><span class="kv-key">Claim status</span><span class="kv-val">' + esc(D.calibration_claim_status) + '</span></div>';
    if (D.calibration_final_authority) h += '<div class="kv-row"><span class="kv-key">Final authority</span><span class="kv-val">' + esc(D.calibration_final_authority) + '</span></div>';
    if (D.calibration_progress) {
      const prog = D.calibration_progress;
      const done = prog.completed_evaluations != null ? prog.completed_evaluations : '';
      const budget = prog.total_budget != null ? prog.total_budget : '';
      h += '<div class="kv-row"><span class="kv-key">Calibration progress</span><span class="kv-val">' + esc((prog.status || 'unknown') + (prog.phase ? ' / ' + prog.phase : '') + (budget !== '' ? ' / ' + done + ' of ' + budget + ' evaluations' : '')) + '</span></div>';
      if (prog.updated_at_utc) h += '<div class="kv-row"><span class="kv-key">Progress updated</span><span class="kv-val">' + esc(prog.updated_at_utc) + '</span></div>';
      if (D.calibration_progress_path) h += '<div class="kv-row"><span class="kv-key">Progress JSON</span><span class="kv-val">' + esc(D.calibration_progress_path) + '</span></div>';
    }
    if (D.temporary_candidate_metrics_allowed_as_final === false) h += '<div class="notice" style="margin-top:12px;margin-bottom:12px;">Candidate/window metrics are provisional. Final claims require locked verification.</div>';
    if (window) {
      h += '<div class="kv-row"><span class="kv-key">Screening score window</span><span class="kv-val">' + esc((window.score_start || 'lock-start') + ' to ' + (window.score_end || 'lock-end')) + '</span></div>';
      h += '<div class="kv-row"><span class="kv-key">Screening simulation window</span><span class="kv-val">' + esc((window.simulation_start || 'lock-start') + ' to ' + (window.simulation_end || 'lock-end')) + '</span></div>';
    }
    if (bench.nse != null || verify.nse != null) h += '<div class="kv-row"><span class="kv-key">NSE benchmark → verified</span><span class="kv-val">' + fmtNum(bench.nse) + ' → ' + fmtNum(verify.nse) + ' (' + fmtNum(delta.nse) + ')</span></div>';
    if (bench.kge != null || verify.kge != null) h += '<div class="kv-row"><span class="kv-key">KGE benchmark → verified</span><span class="kv-val">' + fmtNum(bench.kge) + ' → ' + fmtNum(verify.kge) + ' (' + fmtNum(delta.kge) + ')</span></div>';
    if (bench.pbias != null || verify.pbias != null) h += '<div class="kv-row"><span class="kv-key">PBIAS benchmark → verified</span><span class="kv-val">' + fmtNum(bench.pbias, 1) + '% → ' + fmtNum(verify.pbias, 1) + '%</span></div>';
    if (D.best_solution && D.best_solution.selection_policy) h += '<div class="kv-row"><span class="kv-key">Selection policy</span><span class="kv-val">' + esc(D.best_solution.selection_policy) + '</span></div>';
    if (D.calibration_history_csv) h += '<div class="kv-row"><span class="kv-key">History CSV</span><span class="kv-val">' + esc(D.calibration_history_csv) + '</span></div>';
    if (D.best_solution_path) h += '<div class="kv-row"><span class="kv-key">Best solution</span><span class="kv-val">' + esc(D.best_solution_path) + '</span></div>';
    const protocol = D.calibration_protocol || (D.best_solution && D.best_solution.calibration_protocol) || [];
    if (protocol && protocol.length > 0) {
      h += '<div style="margin-top:14px;font-size:.8rem;color:var(--text-muted);font-weight:700;">Phases</div>';
      h += '<table class="data-table"><tbody>';
      for (const row of protocol) {
        h += '<tr><td>' + esc(row.phase || '') + '</td><td>' + esc((row.parameters || []).join(', ')) + '</td><td>' + esc(row.objective || '') + '</td></tr>';
      }
      h += '</tbody></table>';
    }
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

  function _renderSoilSummary(sr) {
    const pct = value => {
      if (value == null || isNaN(value)) return null;
      const numeric = Number(value);
      return fmtNum(Math.abs(numeric) <= 1 ? numeric * 100 : numeric, 1) + '%';
    };
    const rows = [
      ['Fidelity mode', sr.soil_mode || 'unknown'],
      ['Overlay source', sr.soil_overlay_source || sr.hru_soil_overlay_source || 'unknown'],
      ['Profiles written', sr.profiles_written],
      ['Requested map units', sr.requested_mukeys],
      ['Profile coverage', pct(sr.coverage_pct)],
      ['Fallback soil share', pct(sr.pct_fallback_soils)],
    ];
    let h = '';
    for (const [k, v] of rows) {
      if (v != null && v !== '') {
        h += '<div class="kv-row"><span class="kv-key">' + esc(k) + '</span><span class="kv-val">' + esc(String(v)) + '</span></div>';
      }
    }
    if (sr.authority_note) {
      h += '<div class="notice" style="margin-top:16px;margin-bottom:0;">' + esc(sr.authority_note) + '</div>';
    }
    return h || '<div class="no-data">No soil provenance summary available</div>';
  }

  function _renderRunDetails(D) {
    let h = '';
    const details = [
      ['Run Directory', D.run_dir],
      ['Generated At', D.generated_at],
      ['Execution Status', D.execution_status || 'unknown'],
      ['Scientific Status', D.governance_evaluated ? D.status : 'NOT EVALUATED'],
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


def _collect_spatial_map(run_dir: Path) -> dict[str, Any] | None:
    """Collect compact browser-ready vector and raster layers.

    Spatial artifacts remain authoritative on disk. The dashboard receives
    simplified EPSG:4326 previews for inspection, not replacement datasets.
    """
    layers: list[dict[str, Any]] = []
    vector_specs = [
        ("basin", "Reference basin", run_dir / "raw" / "basin_boundary.gpkg", True),
        ("subbasins", "Subbasins", run_dir / "delin" / "shapes" / "subbasins.gpkg", True),
        ("channels", "Stream network", run_dir / "delin" / "shapes" / "channels.gpkg", True),
        ("outlets", "Gauge / outlet", run_dir / "delin" / "shapes" / "outlets.gpkg", True),
        ("hrus", "HRUs", run_dir / "delin" / "hrus" / "hrus.gpkg", False),
    ]
    for kind, label, path, visible in vector_specs:
        layer = _vector_preview(path, kind=kind, label=label, visible=visible)
        if layer:
            layers.append(layer)

    raster_specs = [
        ("DEM", run_dir / "delin" / "rasters" / "dem_conditioned.tif", "continuous"),
        ("Land use", _first_existing(sorted((run_dir / "raw").glob("nlcd_*.tif"))), "categorical"),
        ("Soils", run_dir / "raw" / "mukey.tif", "categorical"),
        ("HRU raster", run_dir / "delin" / "hrus" / "hru_map.tif", "categorical"),
    ]
    for label, path, mode in raster_specs:
        if path is None:
            continue
        layer = _raster_preview(path, label=label, mode=mode)
        if layer:
            layers.append(layer)

    if not layers:
        return None
    return {
        "layers": layers,
        "note": (
            "Map layers are simplified previews. Use the GeoPackage and GeoTIFF "
            "artifacts in the run directory for quantitative GIS analysis."
        ),
    }


def _first_existing(paths: list[Path | None]) -> Path | None:
    return next((path for path in paths if path is not None and path.is_file()), None)


def _path_from_value(value: Any) -> Path | None:
    if not value:
        return None
    try:
        return Path(str(value)).expanduser()
    except Exception:
        return None


def _vector_preview(
    path: Path,
    *,
    kind: str,
    label: str,
    visible: bool,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        import geopandas as gpd

        frame = gpd.read_file(path)
        if frame.empty or frame.geometry.is_empty.all():
            return None
        if frame.crs is None:
            log.warning("Dashboard map skipped %s because its CRS is missing.", path)
            return None
        frame = frame.to_crs("EPSG:4326")
        # HRU layers can contain thousands of polygons. Geometry simplification
        # keeps the single HTML artifact responsive while retaining every HRU.
        tolerance = 0.00008 if kind == "hrus" else 0.00002
        frame = frame.copy()
        frame.geometry = frame.geometry.simplify(tolerance, preserve_topology=True)
        keep = [column for column in frame.columns if column != frame.geometry.name][:8]
        frame = frame[[*keep, frame.geometry.name]]
        payload = json.loads(frame.to_json(drop_id=True))
        return {
            "type": "geojson",
            "kind": kind,
            "label": f"{label} ({len(frame):,})",
            "visible": visible,
            "source": str(path),
            "feature_count": int(len(frame)),
            "data": payload,
        }
    except Exception as exc:
        log.debug("Dashboard vector preview failed for %s: %s", path, exc)
        return None


def _raster_preview(path: Path, *, label: str, mode: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        import base64
        import io

        import numpy as np
        import rasterio
        from PIL import Image
        from rasterio.warp import transform_bounds

        with rasterio.open(path) as src:
            scale = min(1.0, 900.0 / max(src.width, src.height))
            width = max(1, int(round(src.width * scale)))
            height = max(1, int(round(src.height * scale)))
            band = src.read(1, out_shape=(height, width), masked=True)
            west, south, east, north = transform_bounds(
                src.crs,
                "EPSG:4326",
                *src.bounds,
                densify_pts=21,
            )
        mask = np.ma.getmaskarray(band)
        values = np.asarray(band.filled(np.nan), dtype=float)
        valid = values[~mask & np.isfinite(values)]
        if valid.size == 0:
            return None
        if mode == "continuous":
            low, high = np.nanpercentile(valid, [2, 98])
            if high <= low:
                high = low + 1.0
            norm = np.nan_to_num(
                np.clip((values - low) / (high - low), 0, 1),
                nan=0.0,
            )
            red = (40 + 180 * norm).astype(np.uint8)
            green = (90 + 120 * norm).astype(np.uint8)
            blue = (120 - 80 * norm).astype(np.uint8)
        else:
            codes = np.nan_to_num(values, nan=0).astype(np.int64)
            red = ((codes * 53 + 47) % 205 + 25).astype(np.uint8)
            green = ((codes * 97 + 71) % 205 + 25).astype(np.uint8)
            blue = ((codes * 193 + 29) % 205 + 25).astype(np.uint8)
        alpha = np.where(mask | ~np.isfinite(values), 0, 190).astype(np.uint8)
        rgba = np.dstack([red, green, blue, alpha])
        image = Image.fromarray(rgba)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return {
            "type": "raster",
            "kind": "raster",
            "label": label,
            "visible": False,
            "source": str(path),
            "bounds": [[south, west], [north, east]],
            "opacity": 0.62,
            "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }
    except Exception as exc:
        log.debug("Dashboard raster preview failed for %s: %s", path, exc)
        return None


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
    import io

    try:
        from PIL import Image

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
