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

    plots_html = ""
    for p in diag_files:
        src = embed_image(p)
        label = Path(p).name
        if src:
            plots_html += f'<figure><img src="{src}" alt="{label}" loading="lazy"><figcaption>{label}</figcaption></figure>'
    if plots_html:
        plots_html = f'<div class="plots">{plots_html}</div>'

    return f"""
  <details class='run-card' id='{run_id}' data-status='{overall}'>
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
            f"<tr data-status='{row['status']}'>"
            f"<td>{row['country']}</td>"
            f"<td><code>{row['variable']}</code></td>"
            f"<td>{row['scenario']}</td>"
            f"<td>{row['period']}</td>"
            f"<td>{_badge(row['status'])}</td>"
            f"<td><a href='#{row['run_id']}'>{row['run_id']}</a></td>"
            f"<td>{row['timestamp']}</td>"
            f"<td data-val='{row['duration']:.0f}'>{row['duration']:.0f}s</td>"
            f"</tr>"
        )
    headers = ["Country", "Variable", "Scenario", "Period", "Status", "Run ID", "Date", "Duration"]
    th_html = "".join(
        f"<th data-col='{i}'>{h} <span class='sort-icon'>⇅</span></th>"
        for i, h in enumerate(headers)
    )
    return f"""
  <div class='table-toolbar'>
    <div class='filter-group'>
      <input type='search' id='inv-search' placeholder='Search…' oninput='filterInventory()'>
      <div class='status-filters'>
        <button class='filter-btn active' onclick='setStatusFilter(this,"")'>All</button>
        <button class='filter-btn' onclick='setStatusFilter(this,"SUCCESS")'>✓ Success</button>
        <button class='filter-btn' onclick='setStatusFilter(this,"FAILED")'>✗ Failed</button>
        <button class='filter-btn' onclick='setStatusFilter(this,"WARNING")'>⚠ Warning</button>
      </div>
    </div>
    <button class='export-btn' onclick='exportCSV()'>⬇ Export CSV</button>
  </div>
  <div class='table-wrap'>
    <table class='inv-table' id='inv-table'>
      <thead><tr>{th_html}</tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
  <div id='inv-count' class='table-count'></div>"""


# ── JavaScript ────────────────────────────────────────────────────────────────

_JS = """
// ── Sortable tables ──────────────────────────────────────────────────────────
(function() {
  var _sortCol = -1, _sortAsc = true;

  function sortTable(table, col) {
    var asc = (_sortCol === col) ? !_sortAsc : true;
    _sortCol = col; _sortAsc = asc;

    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a, b) {
      var ac = a.cells[col], bc = b.cells[col];
      var av = (ac.dataset.val !== undefined ? ac.dataset.val : ac.innerText).trim();
      var bv = (bc.dataset.val !== undefined ? bc.dataset.val : bc.innerText).trim();
      var an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    rows.forEach(function(r) { tbody.appendChild(r); });

    table.querySelectorAll('th').forEach(function(th, i) {
      var icon = th.querySelector('.sort-icon');
      if (!icon) return;
      icon.textContent = (i === col) ? (asc ? '▲' : '▼') : '⇅';
      th.classList.toggle('th-sorted', i === col);
    });
  }

  function initSortable(table) {
    table.querySelectorAll('th[data-col]').forEach(function(th) {
      th.style.cursor = 'pointer';
      th.title = 'Click to sort';
      th.addEventListener('click', function() {
        sortTable(table, parseInt(th.dataset.col));
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.inv-table').forEach(initSortable);
  });
})();

// ── Inventory filter ─────────────────────────────────────────────────────────
var _statusFilter = '';

function filterInventory() {
  var q = (document.getElementById('inv-search').value || '').toLowerCase();
  var rows = document.querySelectorAll('#inv-table tbody tr');
  var visible = 0;
  rows.forEach(function(row) {
    var textMatch = !q || row.innerText.toLowerCase().includes(q);
    var statusMatch = !_statusFilter || (row.dataset.status || '') === _statusFilter;
    var show = textMatch && statusMatch;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  var cnt = document.getElementById('inv-count');
  if (cnt) cnt.textContent = visible + ' of ' + rows.length + ' rows';
}

function setStatusFilter(btn, status) {
  _statusFilter = status;
  document.querySelectorAll('.filter-btn').forEach(function(b) {
    b.classList.toggle('active', b === btn);
  });
  filterInventory();
}

// ── CSV export ───────────────────────────────────────────────────────────────
function exportCSV() {
  var table = document.getElementById('inv-table');
  if (!table) return;
  var rows = Array.from(table.querySelectorAll('tr'));
  var csv = rows
    .filter(function(r) { return r.style.display !== 'none'; })
    .map(function(r) {
      return Array.from(r.querySelectorAll('th,td'))
        .map(function(c) { return '"' + c.innerText.replace(/"/g,'""').trim() + '"'; })
        .join(',');
    }).join('\\n');
  var a = document.createElement('a');
  a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
  a.download = 'climate_inventory.csv';
  a.click();
}

// ── Expand / Collapse All ────────────────────────────────────────────────────
function expandAll(open) {
  document.querySelectorAll('#run-history .run-card').forEach(function(d) {
    d.open = open;
  });
}

function filterRuns() {
  var status = document.getElementById('run-status-filter').value;
  document.querySelectorAll('#run-history .run-card').forEach(function(d) {
    d.style.display = (!status || d.dataset.status === status) ? '' : 'none';
  });
}

// ── Dark mode ────────────────────────────────────────────────────────────────
function toggleDark() {
  var html = document.documentElement;
  var dark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', dark ? 'light' : 'dark');
  document.querySelector('.dark-toggle').textContent = dark ? '🌙' : '☀️';
  try { localStorage.setItem('theme', dark ? 'light' : 'dark'); } catch(e) {}
}
(function() {
  try {
    var t = localStorage.getItem('theme');
    if (t === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      document.addEventListener('DOMContentLoaded', function() {
        var btn = document.querySelector('.dark-toggle');
        if (btn) btn.textContent = '☀️';
      });
    }
  } catch(e) {}
})();

// ── Keyboard shortcut: / focuses search ──────────────────────────────────────
document.addEventListener('keydown', function(e) {
  if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
    e.preventDefault();
    var s = document.getElementById('inv-search');
    if (s) { s.focus(); s.select(); }
  }
  if (e.key === 'Escape') {
    var s = document.getElementById('inv-search');
    if (s && document.activeElement === s) { s.value = ''; filterInventory(); s.blur(); }
  }
});

// ── Init count ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  filterInventory();
});
"""

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
.stat-card .num.green { color: #16a34a; }
.stat-card .num.red   { color: #dc2626; }
.stat-card .lbl { font-size: 11px; color: #6b7280; margin-top: 2px;
                  text-transform: uppercase; letter-spacing: .5px; }

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

/* Table toolbar */
.table-toolbar { display: flex; justify-content: space-between; align-items: center;
                 flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
.filter-group { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
#inv-search { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px;
              font-size: 13px; width: 200px; outline: none; }
#inv-search:focus { border-color: #2563eb; box-shadow: 0 0 0 2px #dbeafe; }
.status-filters { display: flex; gap: 4px; }
.filter-btn { padding: 5px 10px; border: 1px solid #d1d5db; border-radius: 6px;
              font-size: 11px; font-weight: 500; cursor: pointer; background: #fff;
              color: #374151; transition: all .15s; }
.filter-btn:hover { background: #f3f4f6; }
.filter-btn.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.export-btn { padding: 6px 12px; border: 1px solid #d1d5db; border-radius: 6px;
              font-size: 12px; cursor: pointer; background: #fff; color: #374151;
              font-weight: 500; transition: all .15s; }
.export-btn:hover { background: #f3f4f6; }
.table-count { font-size: 11px; color: #9ca3af; margin-top: 6px; }

/* Inventory table */
.table-wrap { overflow-x: auto; border-radius: 10px;
              box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.inv-table { width: 100%; border-collapse: collapse; background: #fff; }
.inv-table thead { position: sticky; top: 0; z-index: 1; }
.inv-table th { background: #f8fafc; font-size: 11px; text-transform: uppercase;
                letter-spacing: .5px; color: #6b7280; padding: 10px 14px;
                text-align: left; border-bottom: 2px solid #e5e7eb;
                white-space: nowrap; user-select: none; }
.inv-table th:hover { background: #f1f5f9; color: #374151; }
.inv-table th.th-sorted { color: #2563eb; }
.sort-icon { font-size: 10px; opacity: 0.5; margin-left: 3px; }
.inv-table th.th-sorted .sort-icon { opacity: 1; }
.inv-table td { padding: 9px 14px; border-bottom: 1px solid #f1f5f9; }
.inv-table tr:last-child td { border-bottom: none; }
.inv-table tbody tr:hover td { background: #f8fafc; }

/* Run history toolbar */
.run-toolbar { display: flex; justify-content: space-between; align-items: center;
               flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.run-toolbar-left { display: flex; gap: 6px; align-items: center; }
.run-toolbar select { padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 6px;
                      font-size: 12px; background: #fff; cursor: pointer; }
.run-toolbar-right { display: flex; gap: 6px; }
.ctrl-btn { padding: 5px 10px; border: 1px solid #d1d5db; border-radius: 6px;
            font-size: 11px; font-weight: 500; cursor: pointer; background: #fff;
            color: #374151; transition: all .15s; }
.ctrl-btn:hover { background: #f3f4f6; }

/* Run cards */
.run-card { background: #fff; border-radius: 10px; margin-bottom: 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }
.run-card > summary { padding: 14px 18px; cursor: pointer; list-style: none;
                      display: flex; align-items: center; }
.run-card > summary:hover { background: #f8fafc; }
.run-card > summary::-webkit-details-marker { display: none; }
.run-summary-row { display: flex; align-items: center;
                   justify-content: space-between; width: 100%; gap: 12px;
                   flex-wrap: wrap; }
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
                          list-style: none; display: flex; align-items: center;
                          gap: 8px; }
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
.qc-grid { display: grid;
           grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
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

/* Navigation */
.top-nav { background: #fff; border-bottom: 1px solid #e5e7eb;
           padding: 0 24px; display: flex; gap: 0; position: sticky;
           top: 0; z-index: 100; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.top-nav a { display: inline-block; padding: 12px 16px; font-size: 13px;
             font-weight: 500; color: #6b7280; border-bottom: 2px solid transparent;
             transition: all .15s; text-decoration: none; }
.top-nav a:hover { color: #2563eb; border-bottom-color: #2563eb; }

/* Header layout */
.header-inner { display: flex; align-items: center; gap: 24px; }
.header-logo { flex-shrink: 0; }
.header-text h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }
.header-text .subtitle { font-size: 13px; opacity: 0.8; margin-top: 4px; }
.header-text .generated { font-size: 11px; opacity: 0.6; margin-top: 8px; }

/* About section */
.about-grid { display: grid;
              grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
              gap: 14px; }
.about-card { background: #fff; border-radius: 10px; padding: 18px 20px;
              box-shadow: 0 1px 4px rgba(0,0,0,.08);
              border-top: 3px solid #2563eb; }
.about-icon { font-size: 22px; margin-bottom: 8px; }
.about-title { font-size: 13px; font-weight: 600; color: #111; margin-bottom: 6px; }
.about-body { font-size: 12px; color: #6b7280; line-height: 1.6; }

/* Dark mode toggle */
.dark-toggle { position: fixed; bottom: 24px; right: 24px; z-index: 200;
               width: 42px; height: 42px; border-radius: 50%;
               border: 1px solid #e5e7eb; background: #fff;
               font-size: 18px; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.12);
               display: flex; align-items: center; justify-content: center;
               transition: all .2s; }
.dark-toggle:hover { transform: scale(1.1); }

/* Footer */
.page-footer { background: #1e3a5f; color: #fff; margin-top: 48px;
               padding: 40px 24px 28px; }
.footer-inner { max-width: 1200px; margin: 0 auto;
                display: grid;
                grid-template-columns: auto 1fr auto;
                gap: 40px; align-items: start; }
.footer-brand { display: flex; flex-direction: column; gap: 12px; }
.footer-tagline { font-size: 11px; opacity: 0.6; line-height: 1.6;
                  max-width: 160px; margin-top: 4px; }
.footer-section-label { font-size: 10px; text-transform: uppercase;
                        letter-spacing: .8px; opacity: 0.5; margin-bottom: 12px; }
.contact-row { display: flex; flex-direction: column; gap: 12px; }
.contact-card { display: flex; align-items: center; gap: 12px; }
.contact-avatar { width: 36px; height: 36px; border-radius: 50%;
                  background: rgba(255,255,255,.15); display: flex;
                  align-items: center; justify-content: center;
                  font-size: 14px; font-weight: 700; flex-shrink: 0; }
.contact-name { font-size: 13px; font-weight: 600; }
.contact-title { font-size: 11px; opacity: 0.65; margin: 1px 0; }
.contact-email { font-size: 11px; color: #93c5fd; text-decoration: none; }
.contact-email:hover { text-decoration: underline; }
.footer-meta { font-size: 12px; opacity: 0.75; }
.footer-meta-item { margin-bottom: 6px; }
.footer-meta a { color: #93c5fd; }

/* Dark mode */
[data-theme="dark"] { background: #0f172a; color: #e2e8f0; }
[data-theme="dark"] .top-nav { background: #1e293b; border-color: #334155; }
[data-theme="dark"] .top-nav a { color: #94a3b8; }
[data-theme="dark"] .top-nav a:hover { color: #60a5fa; border-color: #60a5fa; }
[data-theme="dark"] .stat-card,
[data-theme="dark"] .run-card,
[data-theme="dark"] .inv-table,
[data-theme="dark"] .about-card { background: #1e293b; box-shadow: none;
                                   border-color: #334155; }
[data-theme="dark"] .inv-table th { background: #0f172a; color: #64748b;
                                     border-color: #334155; }
[data-theme="dark"] .inv-table td { border-color: #1e293b; }
[data-theme="dark"] .inv-table tbody tr:hover td { background: #0f172a; }
[data-theme="dark"] .run-card > summary:hover,
[data-theme="dark"] .stage-detail > summary { background: #0f172a; }
[data-theme="dark"] .stage-detail { border-color: #334155; }
[data-theme="dark"] .run-body { border-color: #334155; }
[data-theme="dark"] h2 { color: #e2e8f0; border-color: #334155; }
[data-theme="dark"] .qc-card { background: #0f172a; border-color: #334155; }
[data-theme="dark"] .filter-btn,
[data-theme="dark"] .export-btn,
[data-theme="dark"] .ctrl-btn { background: #1e293b; border-color: #334155;
                                  color: #94a3b8; }
[data-theme="dark"] .filter-btn.active { background: #2563eb; color: #fff; }
[data-theme="dark"] #inv-search { background: #1e293b; border-color: #334155;
                                   color: #e2e8f0; }
[data-theme="dark"] .dark-toggle { background: #1e293b; border-color: #334155; }
[data-theme="dark"] .run-toolbar select { background: #1e293b; border-color: #334155;
                                          color: #94a3b8; }
[data-theme="dark"] .about-body { color: #94a3b8; }
[data-theme="dark"] a { color: #60a5fa; }

/* Print */
@media print {
  .dark-toggle, .top-nav, .table-toolbar, .run-toolbar,
  .filter-btn, .export-btn, .ctrl-btn { display: none !important; }
  body { background: #fff; font-size: 12px; }
  .page-header { background: #005899 !important; -webkit-print-color-adjust: exact; }
  .run-card, .stage-detail { box-shadow: none; border: 1px solid #e5e7eb; }
  .content { max-width: 100%; padding: 16px; }
  details { display: block !important; }
  details > summary { display: none; }
  .plots img { max-width: 100%; page-break-inside: avoid; }
  .page-footer { background: #1e3a5f !important; -webkit-print-color-adjust: exact; }
}

/* Responsive */
@media (max-width: 768px) {
  .page-header { padding: 20px; }
  .header-inner { flex-direction: column; gap: 16px; }
  .footer-inner { grid-template-columns: 1fr; gap: 28px; }
  .content { padding: 16px; }
  .top-nav { overflow-x: auto; }
  .stat-row { gap: 10px; }
  .stat-card { min-width: 100px; padding: 12px 16px; }
}
"""


# ── ILRI Logo (inline SVG — no external dependency) ──────────────────────────

_ILRI_LOGO_SVG = """<img src="data:image/png;base64,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" height="48" alt="ILRI logo" role="img" style="display:block;">"""

# ── Contacts ──────────────────────────────────────────────────────────────────

_CONTACTS = [
    {"name": "Yonas Mersha",       "title": "Climate Data Scientist", "email": "Y.Mersha@cgiar.org"},
    {"name": "Dr Teferi Demissie", "title": "Senior Scientist",       "email": "t.demissie@cgiar.org"},
]


def _render_contacts() -> str:
    cards = []
    for c in _CONTACTS:
        cards.append(f"""
        <div class='contact-card'>
          <div class='contact-avatar'>{c['name'][0]}</div>
          <div class='contact-info'>
            <div class='contact-name'>{c['name']}</div>
            <div class='contact-title'>{c['title']}</div>
            <a class='contact-email' href='mailto:{c['email']}'>{c['email']}</a>
          </div>
        </div>""")
    return "".join(cards)


# ── Full page assembly ────────────────────────────────────────────────────────

def generate_html(manifests: list[dict], generated_at: str) -> str:
    inventory = build_inventory(manifests)

    total_runs = len(manifests)
    total_failed = sum(1 for m in manifests if m.get("summary", {}).get("failed", 0) > 0)
    total_ok = total_runs - total_failed
    total_outputs = len(inventory)
    last_run = manifests[0].get("timestamp", "")[:10] if manifests else "—"
    success_rate = f"{total_ok / total_runs * 100:.0f}%" if total_runs else "—"

    stat_cards = f"""
    <div class='stat-row'>
      <div class='stat-card'><div class='num'>{total_runs}</div><div class='lbl'>Total runs</div></div>
      <div class='stat-card'><div class='num green'>{total_ok}</div><div class='lbl'>Successful</div></div>
      <div class='stat-card'><div class='num{"  red" if total_failed else ""}'>{total_failed}</div><div class='lbl'>Failed</div></div>
      <div class='stat-card'><div class='num'>{success_rate}</div><div class='lbl'>Success rate</div></div>
      <div class='stat-card'><div class='num'>{total_outputs}</div><div class='lbl'>Known outputs</div></div>
      <div class='stat-card'><div class='num'>{last_run}</div><div class='lbl'>Last run</div></div>
    </div>"""

    run_toolbar = """
    <div class='run-toolbar'>
      <div class='run-toolbar-left'>
        <label style='font-size:12px;color:#6b7280'>Filter:</label>
        <select id='run-status-filter' onchange='filterRuns()'>
          <option value=''>All statuses</option>
          <option value='SUCCESS'>✓ Success</option>
          <option value='FAILED'>✗ Failed</option>
          <option value='WARNING'>⚠ Warning</option>
        </select>
      </div>
      <div class='run-toolbar-right'>
        <button class='ctrl-btn' onclick='expandAll(true)'>Expand all</button>
        <button class='ctrl-btn' onclick='expandAll(false)'>Collapse all</button>
      </div>
    </div>"""

    runs_html = "\n".join(_render_run(m) for m in manifests)

    nav = """
    <nav class='top-nav' aria-label='Page sections'>
      <a href='#sec-about'>About</a>
      <a href='#sec-inventory'>Inventory</a>
      <a href='#sec-runs'>Run History</a>
      <a href='#sec-contacts'>Contacts</a>
    </nav>"""

    about_section = """
    <section id='sec-about'>
      <h2>About This System</h2>
      <div class='about-grid'>
        <div class='about-card'>
          <div class='about-icon'>🌍</div>
          <div class='about-title'>Coverage</div>
          <div class='about-body'>Ethiopia, Kenya and Somalia — East Africa's most climate-vulnerable pastoralist zones.</div>
        </div>
        <div class='about-card'>
          <div class='about-icon'>📊</div>
          <div class='about-title'>Variables</div>
          <div class='about-body'>Daily temperature (tas), relative humidity (rh), vapour pressure deficit (vpd) and precipitation (pr) at 0.25° resolution.</div>
        </div>
        <div class='about-card'>
          <div class='about-icon'>🔄</div>
          <div class='about-title'>Sources</div>
          <div class='about-body'>AgERA5 reanalysis (historical), CHIRPS v2 (precipitation), ISIMIP3b projections (SSP2-4.5 · SSP5-8.5).</div>
        </div>
        <div class='about-card'>
          <div class='about-icon'>✅</div>
          <div class='about-title'>Quality</div>
          <div class='about-body'>Every output validated for time coverage, grid consistency, unit correctness and spatial bounds before delivery.</div>
        </div>
      </div>
    </section>"""

    footer = f"""
  <footer class='page-footer' id='sec-contacts'>
    <div class='footer-inner'>
      <div class='footer-brand'>
        {_ILRI_LOGO_SVG}
        <div class='footer-tagline'>ILRI Livestock, Climate and Environment Services</div>
      </div>
      <div class='footer-contacts'>
        <div class='footer-section-label'>Project Contacts</div>
        <div class='contact-row'>{_render_contacts()}</div>
      </div>
      <div class='footer-meta'>
        <div class='footer-section-label'>Report</div>
        <div class='footer-meta-item'>Generated {generated_at}</div>
        <div class='footer-meta-item'>
          <a href='https://www.ilri.org' target='_blank' rel='noopener'>www.ilri.org</a>
        </div>
        <div class='footer-meta-item muted' style='margin-top:8px;font-size:10px;'>
          © ILRI / CGIAR. Data for research use only.
        </div>
      </div>
    </div>
  </footer>"""

    dark_toggle = """<button class='dark-toggle' onclick='toggleDark()' title='Toggle dark mode' aria-label='Toggle dark mode'>🌙</button>"""

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Climate Agent — Run Report · ILRI</title>
  <style>{_CSS}</style>
</head>
<body>
  {dark_toggle}

  <header class='page-header'>
    <div class='header-inner'>
      <div class='header-logo'>{_ILRI_LOGO_SVG}</div>
      <div class='header-text'>
        <h1>AI Climate Data Harmonization Agent</h1>
        <div class='subtitle'>ILRI Livestock, Climate and Environment Services · East Africa</div>
        <div class='generated'>Generated {generated_at}</div>
      </div>
    </div>
  </header>

  {nav}

  <div class='content'>
    {stat_cards}

    {about_section}

    <section id='sec-inventory'>
      <h2>Data Inventory</h2>
      {_render_inventory(inventory)}
    </section>

    <section id='sec-runs'>
      <h2>Run History</h2>
      {run_toolbar}
      <div id='run-history'>
        {runs_html if runs_html.strip() else "<p class='muted'>No runs found.</p>"}
      </div>
    </section>
  </div>

  {footer}
  <script>{_JS}</script>
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
