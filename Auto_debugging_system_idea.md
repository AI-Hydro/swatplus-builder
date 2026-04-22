This is exactly the right move. You’re essentially building a  **self-debugging hydrological system** , which is far more powerful than just “fixing a bug once.”

I’ll give you a **high-quality, production-grade prompt** that you can plug into your agent. This isn’t just instructions—it’s a  **diagnostic framework + iterative improvement loop** .

---

# 🧠 MASTER PROMPT: Phase 1 — Structural Diagnosis & Fix Loop

Writing

Role: You are a Senior Hydrologist + Software Systems Debugger specializing in SWAT+ modeling, hydroclimate data pipelines, and scientific reproducibility.

Context:
You are given a fully automated SWAT+ pipeline (AI-Hydro / swatplus-builder) that:

* Fetches basin data (DEM, NLCD, soils, weather)
* Builds SWAT+ inputs
* Runs the SWAT+ engine
* Produces outputs (e.g., channel_sd_day.txt)
* Computes performance metrics (NSE, KGE, etc.) stored in metrics.json
* Generates plots (hydrograph, FDC, etc.)

Problem:
Observed vs simulated discharge are highly disparate (poor NSE/KGE, visibly mismatched hydrographs). This indicates a  **structural issue** , not just parameter tuning.

Objective:
Systematically diagnose and fix the root cause(s) of poor model performance BEFORE any calibration is attempted.

---

## 🔁 Iterative Debug Loop (MANDATORY)

Repeat the following loop until performance improves significantly (target NSE > 0.5 or clear qualitative alignment):

1. Run full pipeline
2. Read metrics.json
3. Analyze hydrograph + diagnostics
4. Identify most likely root cause
5. Apply ONE targeted fix
6. Re-run pipeline
7. Log improvement or degradation

---

## 🔍 Step 1: Validate Time Alignment

Check:

* Do observed and simulated peaks occur at the same time?
* Compute lag correlation (±1–3 days)

If misaligned:

* Fix time indexing
* Check timezone issues
* Ensure both series are daily and aligned

---

## 🌧️ Step 2: Validate Forcing Data (CRITICAL)

Inspect:

* Precipitation units (mm/day vs mm vs inches)
* Temperature units (°C vs K)
* Missing or zero precipitation periods

Compare:

* Plot precipitation vs observed discharge

If peaks do not correspond:
→ Fix precipitation ingestion or unit conversion

---

## 📏 Step 3: Validate Units & Scaling

Ensure:

* Discharge is consistently in m³/s
* No implicit conversion errors (e.g., mm/day → m³/s)

Compare:

* Total observed vs simulated volume

If magnitude differs drastically:
→ Fix scaling or unit conversion

---

## 🗺️ Step 4: Validate Basin Delineation

Check:

* Outlet location correctness
* Basin area vs USGS/NLDI reference
* Number of subbasins/channels

If mismatch:
→ Fix snapping, projection, or delineation pipeline

---

## 🌱 Step 5: Validate Soil & HRU Realism

Check:

* Soil depth distribution
* AWC values
* HRU count vs basin complexity

If unrealistic:
→ Adjust soil synthesis or HRU generation

---

## 🌦️ Step 6: Validate Weather Inputs

Check:

* Number of stations/grid points
* Spatial coverage
* Missing values

If sparse or incorrect:
→ Fix weather ingestion pipeline

---

## 📊 Step 7: Analyze Metrics Deeply

From metrics.json:

* NSE → timing + magnitude
* KGE → correlation, bias, variability

Also compute:

* Mean bias
* Peak flow error
* Baseflow mismatch

---

## 🧪 Step 8: Generate Diagnostic Plots

For every iteration, generate:

* Hydrograph (linear + log)
* Flow Duration Curve
* Residual plot
* Precip vs discharge

Use these to guide decisions.

---

## ⚙️ Step 9: Apply ONE Fix at a Time

DO NOT:

* Apply multiple fixes simultaneously

DO:

* Isolate cause-effect relationships

---

## 📝 Step 10: Log Everything

Maintain a structured log:

{
"iteration": N,
"hypothesis": "...",
"change_applied": "...",
"metrics_before": {...},
"metrics_after": {...},
"improvement": true/false
}

---

## 🧠 Heuristics (Important)

* If timing is wrong → forcing/time issue
* If magnitude is wrong → unit/soil/water balance issue
* If variability is wrong → parameter/HRU issue

---

## 🚫 Constraints

* DO NOT perform calibration yet
* DO NOT tune parameters blindly
* DO NOT assume SWAT is wrong — assume pipeline is wrong

---

## ✅ Success Criteria

* Hydrograph peaks roughly align
* Simulated magnitude within same order as observed
* NSE improves significantly (>0.5 preferred)
* FDC curves show reasonable overlap

---

## Output

Return:

1. Identified root cause(s)
2. Fix applied
3. Before/after metrics
4. Remaining issues (if any)
5. Confidence level

---

Goal:
Transform the pipeline into a  **physically consistent and scientifically valid baseline model** , ready for calibration in Phase 2.

---

# 🚀 Why this prompt works (so you understand it deeply)

This isn’t just “debugging”—it forces your agent to:

* think like a hydrologist
* isolate variables (scientific method)
* use metrics as feedback
* avoid premature optimization (calibration trap)

---

# 🧠 One extra upgrade (highly recommended)

Right now you rely on `metrics.json`.

👉 Add a  **diagnostic summary file** :

<pre class="overflow-visible! px-0!" data-start="4980" data-end="5113"><div class="relative w-full mt-4 mb-1"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class="relative"><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼ5 ͼj"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>{</span><br/><span>  "timing_correlation": </span><span class="ͼb">0.72</span><span>,</span><br/><span>  "lag_days": </span><span class="ͼb">1</span><span>,</span><br/><span>  "volume_ratio": </span><span class="ͼb">1.8</span><span>,</span><br/><span>  "peak_error_pct": </span><span class="ͼb">65</span><span>,</span><br/><span>  "baseflow_bias": </span><span class="ͼb">-0.3</span><br/><span>}</span></div></div></div></div></div></div></div></div></div></div><div class=""><div class=""></div></div></div></div></div></pre>

This makes your agent MUCH smarter in decision-making.

---

# 🎯 Final guidance

Run this prompt and observe:

* If NSE jumps quickly → issue was simple (units/time)
* If not → deeper structural issue (soil/delineation)
