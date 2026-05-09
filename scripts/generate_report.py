#!/usr/bin/env python3
"""
generate_report.py — Static HTML run report for the Climate Data Harmonization Agent.

Reads all run manifests from runs/manifests/ and produces a single self-contained
HTML file with an embedded summary, data inventory, run history, validation tables,
QC statistics, and base64-encoded diagnostic plots.

Usage
-----
    python scripts/generate_report.py                        # → report.html
    python scripts/generate_report.py --output report.html
    python scripts/generate_report.py --manifests-dir runs/manifests --output out.html
"""

from __future__ import annotations
import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# ── Status styling ────────────────────────────────────────────────────────────

_STATUS_CLASS = {
    "SUCCESS":  "badge-success",
    "FAILED":   "badge-failed",
    "WARNING":  "badge-warning",
    "SKIPPED":  "badge-skipped",
    "OK":       "badge-ok",
    "FAIL":     "badge-failed",
    "WARN":     "badge-warning",
    "SKIP":     "badge-skipped",
}

_CHECK_ICON = {"OK": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "–"}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_manifests(manifests_dir: Path) -> list[dict]:
    manifests = []
    for p in sorted(manifests_dir.glob("run_*.json"), reverse=True):
        try:
            manifests.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return manifests


def embed_image(path_str: str) -> str | None:
    p = Path(path_str)
    if not p.exists():
        # Absolute path failed (e.g., Windows path stored in manifest, run on Linux CI).
        # Re-anchor to project root using the data/diagnostics/... suffix.
        norm = path_str.replace("\\", "/")
        marker = "data/diagnostics/"
        idx = norm.find(marker)
        if idx == -1:
            return None
        p = _ROOT / norm[idx:]
        if not p.exists():
            return None
    try:
        data = base64.b64encode(p.read_bytes()).decode()
        return f"data:image/png;base64,{data}"
    except Exception:
        return None


# ── Data inventory (deduplicated view of all known outputs) ───────────────────

def build_inventory(manifests: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for m in reversed(manifests):  # oldest first; newer run overwrites
        req = m.get("request", {})
        summary = m.get("summary", {})
        countries = req.get("countries", [])
        variables = req.get("variables", [])
        scenario = req.get("scenario", "")
        period = req.get("period", [])
        period_str = f"{period[0]}–{period[1]}" if len(period) == 2 else "?"
        status = "SUCCESS" if summary.get("failed", 0) == 0 else "FAILED"
        if summary.get("warnings", 0) > 0 and status == "SUCCESS":
            status = "WARNING"

        for country in countries:
            for variable in variables:
                key = f"{country}|{variable}|{scenario}|{period_str}"
                seen[key] = {
                    "country": country.upper(),
                    "variable": variable,
                    "scenario": scenario,
                    "period": period_str,
                    "status": status,
                    "run_id": m.get("run_id", ""),
                    "timestamp": m.get("timestamp", "")[:10],
                    "duration": summary.get("duration_seconds", 0),
                }
    return sorted(seen.values(),
                  key=lambda r: (r["country"], r["variable"], r["scenario"]))


# ── HTML fragments ────────────────────────────────────────────────────────────

def _badge(text: str) -> str:
    cls = _STATUS_CLASS.get(text.upper(), "badge-skipped")
    return f'<span class="badge {cls}">{text}</span>'


def _render_validation_table(validation: dict) -> str:
    if not validation:
        return "<p class='muted'>No validation recorded.</p>"
    rows = []
    for filename, checks in validation.items():
        rows.append(f"<tr><td colspan='2' class='file-label'>{filename}</td></tr>")
        for check, result in checks.items():
            icon = _CHECK_ICON.get(result, result)
            cls = _STATUS_CLASS.get(result, "badge-skipped")
            rows.append(
                f"<tr><td class='check-name'>{check}</td>"
                f"<td><span class='badge {cls}'>{icon} {result}</span></td></tr>"
            )
    return f"<table class='check-table'>{''.join(rows)}</table>"


def _render_qc_stats(qc_stats: dict) -> str:
    if not qc_stats:
        return ""
    parts = []
    for filename, s in qc_stats.items():
        dims = s.get("dims", {})
        grid = s.get("grid", {})
        time = s.get("time", {})
        vals = s.get("value_stats", {})
        cov = s.get("coverage", {})
        parts.append(f"""
        <div class='qc-card'>
          <div class='qc-title'>{filename}</div>
          <div class='qc-grid'>
            <div class='qc-item'><span class='qc-label'>Variable</span>
              {s.get('file_variable','?')} ({s.get('units','?')})</div>
            <div class='qc-item'><span class='qc-label'>Dimensions</span>
              {dims.get('time','?')} time × {dims.get('lat','?')} lat × {dims.get('lon','?')} lon</div>
            <div class='qc-item'><span class='qc-label'>Resolution</span>
              {grid.get('lat_step_deg','?')}° × {grid.get('lon_step_deg','?')}°</div>
            <div class='qc-item'><span class='qc-label'>Bbox</span>
              lat {grid.get('lat_min','?')}–{grid.get('lat_max','?')},
              lon {grid.get('lon_min','?')}–{grid.get('lon_max','?')}</div>
            <div class='qc-item'><span class='qc-label'>Timesteps</span>
              {time.get('n_timesteps','?')} ({time.get('duplicate_count',0)} duplicates,
              {time.get('n_missing_years',0)} missing years)</div>
            <div class='qc-item'><span class='qc-label'>Land coverage</span>
              {cov.get('finite_ratio', 0)*100:.1f}% non-NaN pixels</div>
            <div class='qc-item'><span class='qc-label'>Value range</span>
              {vals.get('min','?')} – {vals.get('max','?')}</div>
            <div class='qc-item'><span class='qc-label'>Mean ± std</span>
              {vals.get('mean','?')} ± {vals.get('std','?')}</div>
            <div class='qc-item'><span class='qc-label'>Percentiles</span>
              p05={vals.get('p05','?')} p25={vals.get('p25','?')}
              p50={vals.get('median','?')} p75={vals.get('p75','?')}
              p95={vals.get('p95','?')}</div>
          </div>
        </div>""")
    return "".join(parts)


def _render_stage(stage: dict) -> str:
    status = stage.get("status", "?")
    validation = stage.get("validation", {})
    cmd = stage.get("command", "")
    stderr = stage.get("stderr_tail", "").strip()
    stdout = stage.get("stdout_tail", "").strip()
    error = stage.get("error_message", "").strip()
    attempt = stage.get("attempt", 1)
    exit_code = stage.get("exit_code", "?")

    detail_id = f"stage-{stage.get('stage','s')}-{stage.get('country','')}-{stage.get('variable','')}"
    return f"""
    <details class='stage-detail'>
      <summary>
        {_badge(status)}
        <strong>{stage.get('stage','?')}</strong>
        — {stage.get('country','?')} / {stage.get('variable','?')}
        <span class='muted'>(exit {exit_code}, attempt {attempt})</span>
      </summary>
      <div class='stage-body'>
        <div class='cmd-block'>{cmd}</div>
        {_render_validation_table(validation)}
        {f'<details><summary class="muted">stdout</summary><pre>{stdout}</pre></details>' if stdout else ''}
        {f'<div class="error-block">{error}</div>' if error else ''}
        {f'<details><summary class="muted">stderr</summary><pre>{stderr}</pre></details>' if stderr else ''}
      </div>
    </details>"""


def _render_run(m: dict) -> str:
    run_id = m.get("run_id", "?")
    ts = m.get("timestamp", "")[:19].replace("T", " ")
    req = m.get("request", {})
    summary = m.get("summary", {})
    env = m.get("environment", {})
    stages = m.get("stages", [])
    qc_stats = summary.get("qc_stats", {})
    diag_files = summary.get("diagnostic_files", [])

    ok = summary.get("succeeded", 0)
    fail = summary.get("failed", 0)
    warn = summary.get("warnings", 0)
    skip = summary.get("skipped", 0)
    dur = summary.get("duration_seconds", 0)
    overall = "FAILED" if fail > 0 else ("WARNING" if warn > 0 else "SUCCESS")

    countries = ", ".join(req.get("countries", []))
    variables = ", ".join(req.get("variables", []))
    period = req.get("period", [])
    period_str = f"{period[0]}–{period[1]}" if len(period) == 2 else "?"

    stages_html = "".join(_render_stage(s) for s in stages)

    # Embed diagnostic PNGs
    plots_html = ""
    for p in diag_files:
        src = embed_image(p)
        label = Path(p).name
        if src:
            plots_html += f'<figure><img src="{src}" alt="{label}"><figcaption>{label}</figcaption></figure>'
    if plots_html:
        plots_html = f'<div class="plots">{plots_html}</div>'

    return f"""
  <details class='run-card' id='{run_id}'>
    <summary>
      <div class='run-summary-row'>
        <div>{_badge(overall)} <span class='run-id'>{run_id}</span></div>
        <div class='run-meta'>
          <span>{ts}</span>
          <span>{countries} · {variables} · {req.get('scenario','?')} · {period_str}</span>
          <span class='muted'>{dur:.0f}s</span>
          <span class='pill-group'>
            <span class='pill pill-ok'>{ok} ok</span>
            <span class='pill pill-fail'>{fail} fail</span>
            <span class='pill pill-warn'>{warn} warn</span>
            <span class='pill pill-skip'>{skip} skip</span>
          </span>
        </div>
      </div>
    </summary>
    <div class='run-body'>
      <div class='env-row'>
        <span class='qc-label'>Python</span> {env.get('python_version','?')} &nbsp;
        <span class='qc-label'>xarray</span> {env.get('xarray_version','?')} &nbsp;
        <span class='qc-label'>commit</span> {env.get('script_commit','?')} &nbsp;
        <span class='qc-label'>mode</span> {req.get('quality_level','?')}
      </div>
      {stages_html}
      {_render_qc_stats(qc_stats)}
      {plots_html}
    </div>
  </details>"""


def _render_inventory(inventory: list[dict]) -> str:
    if not inventory:
        return "<p class='muted'>No outputs recorded yet.</p>"
    rows = []
    for row in inventory:
        rows.append(
            f"<tr>"
            f"<td>{row['country']}</td>"
            f"<td><code>{row['variable']}</code></td>"
            f"<td>{row['scenario']}</td>"
            f"<td>{row['period']}</td>"
            f"<td>{_badge(row['status'])}</td>"
            f"<td><a href='#{row['run_id']}'>{row['run_id']}</a></td>"
            f"<td>{row['timestamp']}</td>"
            f"<td>{row['duration']:.0f}s</td>"
            f"</tr>"
        )
    return f"""
  <table class='inv-table'>
    <thead><tr>
      <th>Country</th><th>Variable</th><th>Scenario</th><th>Period</th>
      <th>Status</th><th>Run ID</th><th>Date</th><th>Duration</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       font-size: 14px; background: #f4f6f8; color: #1a1a1a; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
code { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px; }
pre { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 11px;
      white-space: pre-wrap; word-break: break-all; background: #1e1e2e;
      color: #cdd6f4; padding: 10px 14px; border-radius: 6px;
      max-height: 220px; overflow-y: auto; margin-top: 8px; }

/* Header */
.page-header { background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
               color: #fff; padding: 32px 40px 24px; }
.page-header h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }
.page-header .subtitle { font-size: 13px; opacity: 0.8; margin-top: 4px; }
.page-header .generated { font-size: 11px; opacity: 0.6; margin-top: 8px; }

/* Layout */
.content { max-width: 1200px; margin: 0 auto; padding: 28px 24px; }
section { margin-bottom: 32px; }
h2 { font-size: 16px; font-weight: 600; margin-bottom: 14px;
     padding-bottom: 6px; border-bottom: 2px solid #e5e7eb; color: #111; }

/* Summary cards */
.stat-row { display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
.stat-card { background: #fff; border-radius: 10px; padding: 16px 22px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); min-width: 130px; }
.stat-card .num { font-size: 28px; font-weight: 700; color: #2563eb; }
.stat-card .lbl { font-size: 11px; color: #6b7280; margin-top: 2px; text-transform: uppercase; letter-spacing: .5px; }

/* Badges */
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
         font-size: 11px; font-weight: 600; letter-spacing: .3px; }
.badge-success { background: #dcfce7; color: #166534; }
.badge-failed  { background: #fee2e2; color: #991b1b; }
.badge-warning { background: #fef9c3; color: #854d0e; }
.badge-skipped { background: #f1f5f9; color: #64748b; }
.badge-ok      { background: #dcfce7; color: #166534; }

/* Pills */
.pill-group { display: inline-flex; gap: 4px; }
.pill { padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.pill-ok   { background: #dcfce7; color: #166534; }
.pill-fail { background: #fee2e2; color: #991b1b; }
.pill-warn { background: #fef9c3; color: #854d0e; }
.pill-skip { background: #f1f5f9; color: #64748b; }

/* Inventory table */
.inv-table { width: 100%; border-collapse: collapse; background: #fff;
             border-radius: 10px; overflow: hidden;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.inv-table th { background: #f8fafc; font-size: 11px; text-transform: uppercase;
                letter-spacing: .5px; color: #6b7280; padding: 10px 14px;
                text-align: left; border-bottom: 1px solid #e5e7eb; }
.inv-table td { padding: 9px 14px; border-bottom: 1px solid #f1f5f9; }
.inv-table tr:last-child td { border-bottom: none; }
.inv-table tr:hover td { background: #f8fafc; }

/* Run cards */
.run-card { background: #fff; border-radius: 10px; margin-bottom: 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }
.run-card > summary { padding: 14px 18px; cursor: pointer; list-style: none;
                      display: flex; align-items: center; }
.run-card > summary:hover { background: #f8fafc; }
.run-card > summary::-webkit-details-marker { display: none; }
.run-summary-row { display: flex; align-items: center;
                   justify-content: space-between; width: 100%; gap: 12px; flex-wrap: wrap; }
.run-id { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
          color: #374151; margin-left: 8px; }
.run-meta { display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
            font-size: 12px; color: #6b7280; }
.run-body { padding: 14px 18px 18px; border-top: 1px solid #f1f5f9; }
.env-row { font-size: 11px; color: #9ca3af; margin-bottom: 12px; }

/* Stage details */
.stage-detail { margin-bottom: 8px; border: 1px solid #e5e7eb;
                border-radius: 8px; overflow: hidden; }
.stage-detail > summary { padding: 8px 14px; cursor: pointer; background: #f8fafc;
                          list-style: none; display: flex; align-items: center; gap: 8px; }
.stage-detail > summary:hover { background: #f1f5f9; }
.stage-detail > summary::-webkit-details-marker { display: none; }
.stage-body { padding: 12px 14px; }
.cmd-block { font-family: monospace; font-size: 11px; background: #1e1e2e;
             color: #cdd6f4; padding: 8px 12px; border-radius: 6px;
             margin-bottom: 10px; overflow-x: auto; white-space: nowrap; }

/* Check table */
.check-table { border-collapse: collapse; margin: 8px 0 10px; font-size: 12px; }
.check-table td { padding: 3px 12px 3px 0; }
.check-name { color: #6b7280; min-width: 160px; }
.file-label { font-size: 11px; color: #9ca3af; padding-top: 8px;
              font-family: monospace; }

/* QC stats */
.qc-card { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px;
           padding: 12px 16px; margin: 10px 0; }
.qc-title { font-family: monospace; font-size: 11px; color: #6b7280;
            margin-bottom: 10px; }
.qc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
           gap: 6px 20px; }
.qc-item { font-size: 12px; color: #374151; }
.qc-label { font-size: 10px; text-transform: uppercase; letter-spacing: .5px;
            color: #9ca3af; display: block; }

/* Plots */
.plots { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 14px; }
.plots figure { text-align: center; }
.plots img { max-width: 600px; width: 100%; border-radius: 8px;
             border: 1px solid #e5e7eb; }
.plots figcaption { font-size: 10px; color: #9ca3af; margin-top: 4px; }

/* Misc */
.muted { color: #9ca3af; font-size: 11px; }
.error-block { background: #fff1f2; border-left: 3px solid #ef4444;
               padding: 8px 12px; font-size: 12px; color: #7f1d1d;
               border-radius: 0 6px 6px 0; margin: 8px 0; }
"""


# ── Full page assembly ────────────────────────────────────────────────────────

def generate_html(manifests: list[dict], generated_at: str) -> str:
    inventory = build_inventory(manifests)

    total_runs = len(manifests)
    total_failed = sum(1 for m in manifests if m.get("summary", {}).get("failed", 0) > 0)
    total_outputs = len(inventory)
    last_run = manifests[0].get("timestamp", "")[:10] if manifests else "—"

    stat_cards = f"""
    <div class='stat-row'>
      <div class='stat-card'><div class='num'>{total_runs}</div><div class='lbl'>Total runs</div></div>
      <div class='stat-card'><div class='num'>{total_failed}</div><div class='lbl'>Failed runs</div></div>
      <div class='stat-card'><div class='num'>{total_runs - total_failed}</div><div class='lbl'>Successful runs</div></div>
      <div class='stat-card'><div class='num'>{total_outputs}</div><div class='lbl'>Known outputs</div></div>
      <div class='stat-card'><div class='num'>{last_run}</div><div class='lbl'>Last run</div></div>
    </div>"""

    runs_html = "\n".join(_render_run(m) for m in manifests)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Climate Agent — Run Report</title>
  <style>{_CSS}</style>
</head>
<body>
  <header class='page-header'>
    <h1>AI Climate Data Harmonization Agent</h1>
    <div class='subtitle'>ILRI Livestock, Climate and Environment Services &nbsp;</div>
    <div class='generated'>Generated {generated_at}</div>
  </header>

  <div class='content'>
    {stat_cards}

    <section>
      <h2>Data Inventory</h2>
      {_render_inventory(inventory)}
    </section>

    <section>
      <h2>Run History</h2>
      {runs_html if runs_html.strip() else "<p class='muted'>No runs found.</p>"}
    </section>
  </div>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a static HTML run report from climate agent manifests."
    )
    parser.add_argument(
        "--manifests-dir",
        default=str(_ROOT / "runs" / "manifests"),
        help="Directory containing run_*.json manifest files (default: runs/manifests/)",
    )
    parser.add_argument(
        "--output", "-o",
        default="report.html",
        help="Output HTML file path (default: report.html)",
    )
    args = parser.parse_args()

    manifests_dir = Path(args.manifests_dir)
    if not manifests_dir.exists():
        print(f"ERROR: manifests directory not found: {manifests_dir}", file=sys.stderr)
        return 1

    print(f"Loading manifests from {manifests_dir} …")
    manifests = load_manifests(manifests_dir)
    if not manifests:
        print("WARNING: no run manifests found — report will be empty.")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(manifests, generated_at)

    output = Path(args.output)
    output.write_text(html, encoding="utf-8")
    print(f"Report written: {output.resolve()}  ({output.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
