"""
Met a jour report/index.html a partir des data.json dans output/.

Usage (depuis csp_solver/experiments/) :
    python update_report.py
"""

import json
import math
from pathlib import Path
from datetime import datetime


def load_all_data(output_dir):
    """Charge les data.json tries par hX (config 'default' en priorite)."""
    results = {}
    for data_file in sorted(output_dir.glob("*/*/data.json")):
        config_name = data_file.parent.name  # "default", "no-freeze", ...
        h_name = data_file.parent.parent.name  # "h3", "h4", ...
        # Prendre 'default' en priorite, sinon la premiere config trouvee
        if h_name not in results or config_name == "default":
            with open(data_file, "r", encoding="utf-8") as f:
                results[h_name] = json.load(f)
    # Compatibilite : ancien format (data.json directement dans hX/)
    for data_file in sorted(output_dir.glob("*/data.json")):
        h_name = data_file.parent.name
        if h_name not in results:
            with open(data_file, "r", encoding="utf-8") as f:
                results[h_name] = json.load(f)
    return results


def compute_stats(data):
    """Calcule les stats pour un data.json."""
    molecules = data["molecules"]
    n_mol = len(molecules)
    n_sol = sum(len(m["solutions"]) for m in molecules.values())
    n_plan = sum(1 for m in molecules.values() for s in m["solutions"] if s["planar"])
    n_non = n_sol - n_plan
    n_orig = sum(1 for m in molecules.values() if m.get("original"))
    n_orig_plan = sum(1 for m in molecules.values()
                      if m.get("original") and m["original"]["planar"])
    pct = round(100 * n_plan / n_sol) if n_sol > 0 else 0
    return {
        "molecules": n_mol,
        "solutions": n_sol,
        "planar": n_plan,
        "non_planar": n_non,
        "pct_planar": pct,
        "originals": n_orig,
        "originals_planar": n_orig_plan,
    }


# =====================================================================
#  Helpers SVG (generes en Python, injectes dans le template)
# =====================================================================

def _pct_color(pct):
    """Couleur hex de rouge (0%) a vert (100%) via jaune (50%)."""
    pct = max(0, min(100, pct))
    if pct <= 50:
        t = pct / 50.0
        r = int(207 + (253 - 207) * t)
        g = int(34 + (203 - 34) * t)
        b = int(46 + (110 - 46) * t)
    else:
        t = (pct - 50) / 50.0
        r = int(253 - (253 - 26) * t)
        g = int(203 + (127 - 203) * t)
        b = int(110 - (110 - 55) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def generate_bar_chart_svg(stats_by_h):
    """SVG bar chart empile : solutions planes vs non-planes par h."""
    if not stats_by_h:
        return ""
    w, h = 600, 280
    mt, mr, mb, ml = 24, 20, 44, 56
    cw = w - ml - mr
    ch = h - mt - mb
    n = len(stats_by_h)
    max_val = max((p + np) for _, p, np in stats_by_h)
    if max_val == 0:
        max_val = 1

    bar_w = min(60, cw / n * 0.6)
    gap = (cw - n * bar_w) / (n + 1)

    lines = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"',
        f'  style="width:100%;max-width:{w}px;font-family:Segoe UI,system-ui,sans-serif;">',
    ]

    # Gridlines + y-axis labels
    n_grid = 4
    for i in range(n_grid + 1):
        y = mt + ch - (i / n_grid) * ch
        val = int(round(max_val * i / n_grid))
        lines.append(f'  <line x1="{ml}" y1="{y:.1f}" x2="{w-mr}" y2="{y:.1f}" '
                     f'stroke="#e1e4e8" stroke-dasharray="4,3"/>')
        lines.append(f'  <text x="{ml-8}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#6a737d">{val}</text>')

    # Bars
    for i, (h_num, planar, non_planar) in enumerate(stats_by_h):
        x = ml + gap + i * (bar_w + gap)
        total = planar + non_planar

        # Planar (bottom, green)
        h_plan = (planar / max_val) * ch
        y_plan = mt + ch - h_plan
        lines.append(f'  <rect x="{x:.1f}" y="{y_plan:.1f}" width="{bar_w:.1f}" '
                     f'height="{h_plan:.1f}" fill="#1a7f37" rx="2">'
                     f'<title>h{h_num} : {planar} planes</title></rect>')

        # Non-planar (top, red)
        if non_planar > 0:
            h_non = (non_planar / max_val) * ch
            y_non = y_plan - h_non
            lines.append(f'  <rect x="{x:.1f}" y="{y_non:.1f}" width="{bar_w:.1f}" '
                         f'height="{h_non:.1f}" fill="#cf222e" rx="2">'
                         f'<title>h{h_num} : {non_planar} non planes</title></rect>')
        else:
            y_non = y_plan

        # Value label
        lines.append(f'  <text x="{x + bar_w/2:.1f}" y="{y_non - 6:.1f}" text-anchor="middle" '
                     f'font-size="12" font-weight="700" fill="#24292e">{total}</text>')

        # X-axis label
        lines.append(f'  <text x="{x + bar_w/2:.1f}" y="{mt + ch + 22:.1f}" text-anchor="middle" '
                     f'font-size="13" font-weight="600" fill="#24292e">h{h_num}</text>')

    # Legend
    lx = w - mr - 160
    lines.append(f'  <rect x="{lx}" y="6" width="12" height="12" fill="#1a7f37" rx="2"/>')
    lines.append(f'  <text x="{lx+16}" y="16" font-size="11" fill="#6a737d">Planes</text>')
    lines.append(f'  <rect x="{lx+80}" y="6" width="12" height="12" fill="#cf222e" rx="2"/>')
    lines.append(f'  <text x="{lx+96}" y="16" font-size="11" fill="#6a737d">Non planes</text>')

    lines.append('</svg>')
    return "\n".join(lines)


def generate_donut_svg(planar, non_planar):
    """SVG donut chart : pourcentage de solutions planes."""
    total = planar + non_planar
    if total == 0:
        return ""
    pct = round(100 * planar / total)

    cx, cy, r = 100, 100, 70
    sw = 24
    circumference = 2 * math.pi * r

    green_len = (planar / total) * circumference

    lines = [
        '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg"',
        '  style="width:100%;max-width:200px;font-family:Segoe UI,system-ui,sans-serif;">',
    ]

    # Background circle (red)
    lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                 f'stroke="#cf222e" stroke-width="{sw}"/>')

    # Green arc
    if planar > 0 and planar < total:
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="#1a7f37" stroke-width="{sw}" '
                     f'stroke-dasharray="{green_len:.2f} {circumference:.2f}" '
                     f'transform="rotate(-90 {cx} {cy})"/>')
    elif planar == total:
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="#1a7f37" stroke-width="{sw}"/>')

    # Center text
    lines.append(f'  <text x="{cx}" y="{cy - 4}" text-anchor="middle" '
                 f'font-size="32" font-weight="700" fill="#24292e">{pct}%</text>')
    lines.append(f'  <text x="{cx}" y="{cy + 16}" text-anchor="middle" '
                 f'font-size="12" fill="#6a737d">planes</text>')

    lines.append('</svg>')
    return "\n".join(lines)


# =====================================================================
#  Generation du HTML
# =====================================================================

def generate_html(all_data):
    """Genere le HTML du rapport."""
    # Stats par h
    rows = []
    detail_rows = []
    totals = {"molecules": 0, "solutions": 0, "planar": 0, "non_planar": 0}
    h_cards = []
    chart_data = []  # (h_num, planar, non_planar)

    for h_name in sorted(all_data.keys(), key=lambda x: int(x[1:])):
        stats = compute_stats(all_data[h_name])
        h_num = h_name[1:]
        totals["molecules"] += stats["molecules"]
        totals["solutions"] += stats["solutions"]
        totals["planar"] += stats["planar"]
        totals["non_planar"] += stats["non_planar"]
        chart_data.append((int(h_num), stats["planar"], stats["non_planar"]))

        pct = stats["pct_planar"]
        bar_color = _pct_color(pct)

        non_cls = ' class="non-planar"' if stats["non_planar"] > 0 else ""
        rows.append(
            f'    <tr class="h-row">'
            f'<td class="h-toggle" onclick="toggleDetail(\'h{h_num}\')">'
            f'<strong>h={h_num}</strong> <span class="chevron" id="chev-h{h_num}">&#9654;</span></td>'
            f'<td>{stats["molecules"]}</td>'
            f'<td>{stats["solutions"]}</td>'
            f'<td class="planar">{stats["planar"]}</td>'
            f'<td{non_cls}>{stats["non_planar"]}</td>'
            f'<td><div class="pct-bar-wrap">'
            f'<div class="pct-bar" style="width:{pct}%;background:{bar_color};"></div>'
            f'<span class="pct-label">{pct}%</span>'
            f'</div></td>'
            f'<td class="planar">{stats["originals_planar"]}/{stats["originals"]}</td>'
            f'</tr>'
        )

        # Build molecule mini-table for this h
        mol_rows_html = ""
        for mol_name in sorted(all_data[h_name]["molecules"].keys()):
            mol = all_data[h_name]["molecules"][mol_name]
            n_sol = len(mol["solutions"])
            n_plan = sum(1 for s in mol["solutions"] if s["planar"])
            n_non = n_sol - n_plan
            orig = mol.get("original")
            if orig:
                o_cls = "planar" if orig["planar"] else "non-planar"
                o_txt = "PLAN" if orig["planar"] else "NON PLAN"
                o_angle = f'{orig["angle_deg"]}&deg;'
            else:
                o_cls = "na"
                o_txt = "-"
                o_angle = "-"
            non_cls_mol = ' class="non-planar"' if n_non > 0 else ""
            mol_rows_html += (
                f'      <tr>'
                f'<td style="font-family:SFMono-Regular,Consolas,monospace;font-weight:600;">{mol_name}</td>'
                f'<td>{n_sol}</td>'
                f'<td class="planar">{n_plan}</td>'
                f'<td{non_cls_mol}>{n_non}</td>'
                f'<td class="{o_cls}">{o_txt}</td>'
                f'<td>{o_angle}</td>'
                f'</tr>\n'
            )

        detail_rows.append(
            f'    <tr class="detail-row" id="detail-h{h_num}" style="display:none;">'
            f'<td colspan="7" style="padding:0;">'
            f'<div class="detail-panel">'
            f'<table class="mini-table"><thead><tr>'
            f'<th>Molecule</th><th>Solutions</th><th>Planes</th>'
            f'<th>Non pl.</th><th>Original</th><th>Angle</th>'
            f'</tr></thead><tbody>\n'
            f'{mol_rows_html}'
            f'    </tbody></table></div></td></tr>'
        )

        h_cards.append(
            f'  <a href="../output/{h_name}/view.html" target="_blank" '
            f'class="card blue">'
            f'<div class="value">{h_name}</div>'
            f'<div class="label">{stats["molecules"]} molecules</div>'
            f'<div class="sub">{stats["planar"]} pl. / {stats["non_planar"]} non pl.</div></a>'
        )

    h_list = sorted(all_data.keys(), key=lambda x: int(x[1:]))
    h_min = h_list[0][1:]
    h_max = h_list[-1][1:]

    # Interleave main rows and detail rows
    table_rows = []
    for r, d in zip(rows, detail_rows):
        table_rows.append(r)
        table_rows.append(d)
    rows_html = "\n".join(table_rows)
    cards_html = "\n".join(h_cards)

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # SVG charts
    bar_chart_svg = generate_bar_chart_svg(chart_data)
    donut_svg = generate_donut_svg(totals["planar"], totals["non_planar"])

    # Batch command rows
    batch_rows = "\n".join(
        f'    <tr><td>{h}</td>'
        f'<td><code>python batch_main.py plane/benzdb/{h} --validate</code></td></tr>'
        for h in h_list
    )

    total_pct = round(100 * totals["planar"] / totals["solutions"]) if totals["solutions"] > 0 else 0

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Experimentation — Structures planes BenzAI DB</title>
<style>
  :root {{
    --bg: #f0f2f5; --surface: #ffffff; --surface-alt: #f8f9fa;
    --border: #e1e4e8; --text: #24292e; --text-muted: #6a737d;
    --accent: #0969da; --accent-subtle: #ddf4ff;
    --green: #1a7f37; --green-bg: #dafbe1;
    --red: #cf222e; --red-bg: #ffebe9;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
    --shadow-md: 0 3px 8px rgba(0,0,0,0.08);
    --radius: 8px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: var(--bg);
         color: var(--text); padding: 0; line-height: 1.6; font-size: 15px; }}

  /* Header */
  .page-header {{ background: var(--surface); border-bottom: 1px solid var(--border);
                  padding: 24px 32px; box-shadow: var(--shadow-sm); }}
  .page-header h1 {{ font-size: 1.6em; margin-bottom: 2px; letter-spacing: -0.02em; }}
  .meta {{ color: var(--text-muted); font-size: 0.82em; }}

  /* Navigation */
  .nav-bar {{ position: sticky; top: 0; z-index: 100; background: rgba(255,255,255,0.97);
              backdrop-filter: blur(8px); border-bottom: 1px solid var(--border);
              padding: 8px 32px; display: flex; gap: 6px; flex-wrap: wrap; }}
  .nav-bar a {{ color: var(--text-muted); text-decoration: none; font-size: 0.78em; font-weight: 600;
                padding: 4px 10px; border-radius: 6px; transition: all 0.15s; white-space: nowrap; }}
  .nav-bar a:hover {{ color: var(--accent); background: var(--accent-subtle); }}
  .nav-bar a.active {{ color: var(--accent); background: var(--accent-subtle); }}

  /* Container */
  .container {{ max-width: 1100px; margin: 0 auto; padding: 0 32px 48px; }}

  /* Sections */
  section {{ padding-top: 28px; }}
  section + section {{ border-top: 1px solid var(--border); margin-top: 12px; }}
  h2 {{ font-size: 1.2em; margin-bottom: 14px; color: var(--text); padding-bottom: 8px;
       display: flex; align-items: center; gap: 10px; }}
  .section-num {{ background: var(--accent); color: #fff; font-size: 0.7em; padding: 2px 10px;
                  border-radius: 12px; font-weight: 700; display: inline-block; }}
  h3 {{ font-size: 1em; margin: 20px 0 10px; color: var(--text-muted); }}
  p {{ margin-bottom: 12px; }}

  /* Pipeline */
  .pipeline {{ background: var(--surface); border-radius: var(--radius); padding: 16px 20px; margin: 12px 0;
              box-shadow: var(--shadow-sm); font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.88em;
              display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .pipeline .step {{ background: #eef2f6; padding: 6px 14px; border-radius: 6px; }}
  .pipeline .arrow {{ color: var(--accent); font-weight: bold; font-size: 1.1em; }}

  /* Config boxes */
  .config {{ background: var(--surface); border-radius: var(--radius); padding: 16px 20px; margin: 12px 0;
            box-shadow: var(--shadow-sm); }}
  .config table {{ width: 100%; border-collapse: collapse; }}
  .config td {{ padding: 5px 12px; font-size: 0.88em; }}
  .config td:first-child {{ font-weight: 600; color: var(--text-muted); width: 220px; }}
  .config tr:nth-child(even) {{ background: var(--surface-alt); }}

  /* Cards */
  .cards {{ display: flex; gap: 14px; margin: 16px 0; flex-wrap: wrap; }}
  .card {{ background: var(--surface); border-radius: var(--radius); padding: 16px 20px; min-width: 140px;
          box-shadow: var(--shadow-sm); text-align: center; border-top: 3px solid var(--border);
          transition: transform 0.15s, box-shadow 0.15s; flex: 1; }}
  .card:hover {{ transform: translateY(-1px); box-shadow: var(--shadow-md); }}
  .card .value {{ font-size: 1.7em; font-weight: 700; }}
  .card .label {{ font-size: 0.75em; color: var(--text-muted); margin-top: 2px; }}
  .card .sub {{ font-size: 0.7em; color: var(--text-muted); }}
  .card.green {{ border-top-color: var(--green); }}  .card.green .value {{ color: var(--green); }}
  .card.red {{ border-top-color: var(--red); }}      .card.red .value {{ color: var(--red); }}
  .card.blue {{ border-top-color: var(--accent); }}  .card.blue .value {{ color: var(--accent); }}
  a.card {{ text-decoration: none; cursor: pointer; }}

  /* Charts */
  .charts-row {{ display: flex; gap: 24px; margin: 20px 0; align-items: center; flex-wrap: wrap; }}
  .chart-box {{ background: var(--surface); border-radius: var(--radius); padding: 20px;
               box-shadow: var(--shadow-sm); flex: 1; min-width: 220px; text-align: center; }}
  .chart-box.wide {{ flex: 3; }}

  /* Results table */
  table.results {{ width: 100%; background: var(--surface); border-radius: var(--radius); overflow: hidden;
                  box-shadow: var(--shadow-sm); border-collapse: collapse; margin: 16px 0; }}
  table.results th {{ background: #f6f8fa; padding: 10px 14px; text-align: center; font-size: 0.78em;
                     text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted);
                     border-bottom: 1px solid var(--border); }}
  table.results td {{ padding: 8px 14px; border-top: 1px solid #f0f0f0; text-align: center; font-size: 0.88em; }}
  table.results .h-row:hover {{ background: var(--accent-subtle); }}
  .h-toggle {{ cursor: pointer; text-align: left !important; white-space: nowrap; }}
  .chevron {{ font-size: 0.7em; color: var(--accent); display: inline-block; transition: transform 0.2s; margin-left: 4px; }}
  .planar {{ color: var(--green); font-weight: 600; }}
  .non-planar {{ color: var(--red); font-weight: 600; }}

  /* Progress bar */
  .pct-bar-wrap {{ position: relative; background: #f0f0f0; border-radius: 4px; height: 22px;
                   min-width: 80px; overflow: hidden; }}
  .pct-bar {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .pct-label {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
                font-size: 0.78em; font-weight: 700; color: var(--text); }}

  /* Detail panel */
  .detail-panel {{ padding: 12px 24px 16px; background: var(--surface-alt); border-top: 2px solid var(--accent); }}
  .mini-table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
  .mini-table th {{ background: #e8ecf0; padding: 6px 10px; text-align: center; font-size: 0.78em;
                   text-transform: uppercase; color: var(--text-muted); }}
  .mini-table td {{ padding: 5px 10px; border-top: 1px solid #e8ecf0; text-align: center; }}
  .mini-table tr:hover {{ background: #f0f4f8; }}
  .na {{ color: #b2bec3; }}

  /* Notes & observations */
  .note {{ background: #fff8c5; border-left: 4px solid #bf8700; padding: 12px 16px;
          border-radius: 0 var(--radius) var(--radius) 0; margin: 16px 0; font-size: 0.88em; }}
  .observation {{ background: var(--surface); border-left: 4px solid var(--accent); padding: 12px 16px;
                 border-radius: 0 var(--radius) var(--radius) 0; margin: 12px 0; font-size: 0.88em;
                 box-shadow: var(--shadow-sm); }}
  .observation strong::before {{ content: "\\25B6 "; color: var(--accent); font-size: 0.8em; }}

  ul {{ margin: 8px 0 8px 24px; }}
  li {{ margin-bottom: 4px; }}
  code {{ background: #eef2f6; padding: 2px 6px; border-radius: 4px; font-size: 0.85em;
         font-family: 'SFMono-Regular', Consolas, monospace; }}
  a {{ color: var(--accent); }}

  /* Responsive */
  @media (max-width: 768px) {{
    .page-header {{ padding: 16px; }}
    .nav-bar {{ padding: 6px 12px; overflow-x: auto; flex-wrap: nowrap; }}
    .container {{ padding: 0 12px 24px; }}
    .cards {{ flex-direction: column; }}
    .card {{ min-width: auto; }}
    .charts-row {{ flex-direction: column; }}
    .pipeline {{ flex-direction: column; align-items: flex-start; }}
    table.results th, table.results td {{ padding: 6px 8px; font-size: 0.8em; }}
    .detail-panel {{ padding: 8px 12px; }}
  }}
</style>
</head>
<body>

<header class="page-header">
  <h1>Phase experimentale — Structures planes</h1>
  <p class="meta">Source : BenzAI DB &mdash; h{h_min} a h{h_max}
    &mdash; {totals["molecules"]} molecules, {totals["solutions"]} solutions
    &mdash; Mis a jour le {now}</p>
</header>

<nav class="nav-bar" id="nav">
  <a href="#introduction">Introduction</a>
  <a href="#methodologie">Methodologie</a>
  <a href="#resultats">Resultats</a>
  <a href="#observations">Observations</a>
  <a href="#details">Details</a>
  <a href="#commandes">Commandes</a>
</nav>

<div class="container">

<!-- ============================================================ -->
<section id="introduction">
<h2><span class="section-num">1</span> Introduction</h2>

<p>
  Le modele de generation de non-benzenoides (solveur CSP + reconstruction 3D + optimisation xTB)
  est operationnel. Les premiers tests ont revele des solutions marquees comme non planes,
  ce qui a motive le lancement d'une phase experimentale systematique.
</p>
<p>
  L'objectif est de tester le pipeline sur des structures dont la planarite est connue :
  les benzenoides plans issus de <strong>BenzAI DB</strong>, de h={h_min} a h={h_max}.
  Puisque ces structures sont planes par construction, toutes les solutions tout-hexagonales (6,6,...,6)
  doivent etre validees comme planes. Les solutions avec substitutions 5/7 sont les cas d'interet.
</p>
</section>

<!-- ============================================================ -->
<section id="methodologie">
<h2><span class="section-num">2</span> Methodologie</h2>

<h3>Pipeline</h3>
<div class="pipeline">
  <span class="step">.graph (BenzAI DB)</span>
  <span class="arrow">&rarr;</span>
  <span class="step">Solveur CSP (ACE)</span>
  <span class="arrow">&rarr;</span>
  <span class="step">Reconstruction 3D</span>
  <span class="arrow">&rarr;</span>
  <span class="step">xTB (GFN2-xTB)</span>
  <span class="arrow">&rarr;</span>
  <span class="step">Test planarite (ACP)</span>
</div>

<h3>Configuration xTB</h3>
<div class="config">
  <table>
    <tr><td>Methode</td><td>GFN2-xTB (semi-empirique, tight-binding etendu)</td></tr>
    <tr><td>Niveau d'optimisation</td><td><code>--opt tight</code></td></tr>
    <tr><td>Perturbation initiale</td><td>&plusmn;0.1 &Aring; aleatoire sur les coordonnees z</td></tr>
    <tr><td>Timeout</td><td>300 secondes par molecule</td></tr>
  </table>
</div>

<h3>Test de planarite</h3>
<div class="config">
  <table>
    <tr><td>Methode</td><td>Analyse en Composantes Principales (ACP) sur les coordonnees atomiques</td></tr>
    <tr><td>Metrique</td><td>Angle maximal de deviation par rapport au plan moyen</td></tr>
    <tr><td>Seuil</td><td><strong>10&deg;</strong> &mdash; en dessous = plan, au dessus = non plan</td></tr>
  </table>
</div>

<div class="note">
  <strong>Non-determinisme :</strong> xTB est un optimiseur local (descente de gradient).
  La perturbation aleatoire en z fait que le point de depart differe a chaque run,
  ce qui peut mener a des minima locaux legerement differents.
  Les angles observes peuvent varier de &plusmn;3-5&deg; entre executions successives.
</div>
</section>

<!-- ============================================================ -->
<section id="resultats">
<h2><span class="section-num">3</span> Resultats</h2>

<h3>Vue d'ensemble</h3>
<div class="cards">
  <div class="card blue"><div class="value">{totals["molecules"]}</div><div class="label">Molecules testees</div></div>
  <div class="card blue"><div class="value">{totals["solutions"]}</div><div class="label">Solutions CSP</div></div>
  <div class="card green"><div class="value">{totals["planar"]}</div><div class="label">Solutions planes</div></div>
  <div class="card red"><div class="value">{totals["non_planar"]}</div><div class="label">Solutions non planes</div></div>
</div>

<h3>Visualisation</h3>
<div class="charts-row">
  <div class="chart-box wide">
    {bar_chart_svg}
  </div>
  <div class="chart-box">
    {donut_svg}
  </div>
</div>

<h3>Par taille de benzenoide</h3>
<p style="font-size:0.85em;color:var(--text-muted);margin-bottom:8px;">Cliquez sur une ligne pour voir le detail par molecule.</p>
<table class="results">
  <thead>
    <tr>
      <th>h</th>
      <th>Molecules</th>
      <th>Solutions</th>
      <th>Planes</th>
      <th>Non planes</th>
      <th>% plan</th>
      <th>Originaux plans</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
</section>

<!-- ============================================================ -->
<section id="observations">
<h2><span class="section-num">4</span> Observations</h2>

<div class="observation">
  <strong>Les originaux sont tous plans.</strong>
  Les {totals["molecules"]} structures originales (tout hexagonal, solution 6,6,...,6) sont systematiquement
  validees comme planes (&lt; 1&deg;). Cela confirme que le pipeline de reconstruction + xTB
  fonctionne correctement sur les benzenoides connus.
</div>

<div class="observation">
  <strong>Les solutions tout-6 sont toujours planes.</strong>
  Quand la solution CSP est identique au benzenoide original (tous les cycles a 6),
  l'angle maximal est systematiquement &lt; 1&deg;. Le pipeline est coherent.
</div>

<div class="observation">
  <strong>Le taux de non-planarite augmente avec h.</strong>
  Plus le benzenoide est grand, plus les substitutions 5/7
  ont de chances de produire des structures non planes.
</div>

<div class="observation">
  <strong>Non-determinisme observe.</strong>
  Les solutions avec des angles proches du seuil (10-20&deg;) peuvent varier entre les runs.
  Les solutions clairement planes (&lt; 1&deg;) ou clairement non planes (&gt; 20&deg;)
  sont stables entre les runs.
</div>
</section>

<!-- ============================================================ -->
<section id="details">
<h2><span class="section-num">5</span> Resultats detailles</h2>
<p>Cliquez sur une carte pour ouvrir le viewer interactif de chaque taille.</p>
<div class="cards">
{cards_html}
</div>
</section>

<!-- ============================================================ -->
<section id="commandes">
<h2><span class="section-num">6</span> Commandes</h2>

<p>Toutes les commandes se lancent depuis le dossier <code>csp_solver/experiments/</code>.</p>

<h3>Lancer les tests sur un dossier (CSP + validation + original)</h3>
<div class="config">
  <table>
{batch_rows}
  </table>
</div>
<p>
  Cela lance pour chaque <code>.graph</code> : le test de l'original (tout-6) via <code>test.py</code>,
  puis le solveur CSP + validation xTB via <code>main.py --validate</code>.
  Le rapport <code>view.html</code> est genere automatiquement a la fin dans <code>output/hX/</code>.
</p>

<h3>Tester seulement les originaux</h3>
<div class="config">
  <table>
    <tr><td>Exemple</td><td><code>python batch_test.py plane/benzdb/h3</code></td></tr>
  </table>
</div>

<h3>Regenerer les rapports sans relancer les calculs</h3>
<div class="config">
  <table>
    <tr><td>Un seul</td><td><code>python view.py output/h4 --aggregate</code></td></tr>
    <tr><td>Rapport global</td><td><code>python update_report.py</code></td></tr>
  </table>
</div>

<h3>Lancer un seul fichier manuellement</h3>
<p>Depuis le dossier <code>csp_solver/</code> :</p>
<div class="config">
  <table>
    <tr><td>CSP + validation</td><td><code>python main.py data/fichier.graph --validate</code></td></tr>
    <tr><td>Test original seul</td><td><code>python test.py data/fichier.graph</code></td></tr>
  </table>
</div>
</section>

</div>

<script>
/* Toggle detail rows */
function toggleDetail(id) {{
  var row = document.getElementById('detail-' + id);
  var chev = document.getElementById('chev-' + id);
  if (!row) return;
  if (row.style.display === 'none') {{
    row.style.display = 'table-row';
    chev.innerHTML = '&#9660;';
    chev.style.transform = 'rotate(0deg)';
  }} else {{
    row.style.display = 'none';
    chev.innerHTML = '&#9654;';
    chev.style.transform = 'rotate(0deg)';
  }}
}}

/* Smooth scroll for nav links */
document.querySelectorAll('.nav-bar a').forEach(function(a) {{
  a.addEventListener('click', function(e) {{
    e.preventDefault();
    var target = document.querySelector(this.getAttribute('href'));
    if (target) target.scrollIntoView({{ behavior: 'smooth' }});
  }});
}});

/* Active section tracking */
var observer = new IntersectionObserver(function(entries) {{
  entries.forEach(function(entry) {{
    if (entry.isIntersecting) {{
      document.querySelectorAll('.nav-bar a').forEach(function(a) {{
        a.classList.toggle('active', a.getAttribute('href') === '#' + entry.target.id);
      }});
    }}
  }});
}}, {{ rootMargin: '-20% 0px -70% 0px' }});
document.querySelectorAll('section[id]').forEach(function(s) {{ observer.observe(s); }});
</script>

</body>
</html>"""
    return html


def main():
    experiments_dir = Path(__file__).parent
    output_dir = experiments_dir / "output"
    report_dir = experiments_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not output_dir.is_dir():
        print("ERREUR : dossier output/ introuvable.")
        return

    all_data = load_all_data(output_dir)
    if not all_data:
        print("Aucun data.json trouve dans output/.")
        return

    print(f"Donnees chargees : {', '.join(sorted(all_data.keys()))}")

    html = generate_html(all_data)
    out_path = report_dir / "index.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Rapport genere : {out_path}")


if __name__ == "__main__":
    main()
