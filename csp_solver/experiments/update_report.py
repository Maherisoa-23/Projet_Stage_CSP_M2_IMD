"""
Met a jour report/index.html a partir des data.json dans output/.

Usage (depuis csp_solver/experiments/) :
    python update_report.py

Les templates HTML/CSS/JS sont dans ./templates/ (edites avec coloration
syntaxique). Les helpers SVG (bar chart, donut) generent leurs strings en
Python pur puis sont injectes dans le template.
"""

import json
import math
from pathlib import Path
from datetime import datetime
from string import Template

TEMPLATES_DIR = Path(__file__).parent / "templates"


# =====================================================================
#  Chargement + stats
# =====================================================================

def load_all_data(output_dir):
    """Charge les data.json tries par hX (config 'default' en priorite)."""
    results = {}
    # Pass 1 : config-level (output/hX/configName/data.json)
    for data_file in sorted(output_dir.glob("*/*/data.json")):
        config_name = data_file.parent.name
        h_name = data_file.parent.parent.name
        if h_name not in results or config_name == "default":
            with open(data_file, "r", encoding="utf-8") as f:
                results[h_name] = json.load(f)
    # Pass 2 : ancien format (output/hX/data.json direct)
    for data_file in sorted(output_dir.glob("*/data.json")):
        h_name = data_file.parent.name
        if h_name not in results:
            with open(data_file, "r", encoding="utf-8") as f:
                results[h_name] = json.load(f)
    return results


def compute_stats(data):
    """Stats agregees pour un data.json."""
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
#  Helpers SVG (pure Python)
# =====================================================================

def _pct_color(pct):
    """Hex color : rouge (0%) -> jaune (50%) -> vert (100%)."""
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
    """SVG bar chart empile : solutions planes (vert) + non-planes (rouge) par h."""
    if not stats_by_h:
        return ""
    w, h = 600, 280
    mt, mr, mb, ml = 24, 20, 44, 56
    cw = w - ml - mr
    ch = h - mt - mb
    n = len(stats_by_h)
    max_val = max((p + np) for _, p, np in stats_by_h) or 1

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

        h_plan = (planar / max_val) * ch
        y_plan = mt + ch - h_plan
        lines.append(f'  <rect x="{x:.1f}" y="{y_plan:.1f}" width="{bar_w:.1f}" '
                     f'height="{h_plan:.1f}" fill="#1a7f37" rx="2">'
                     f'<title>h{h_num} : {planar} planes</title></rect>')

        if non_planar > 0:
            h_non = (non_planar / max_val) * ch
            y_non = y_plan - h_non
            lines.append(f'  <rect x="{x:.1f}" y="{y_non:.1f}" width="{bar_w:.1f}" '
                         f'height="{h_non:.1f}" fill="#cf222e" rx="2">'
                         f'<title>h{h_num} : {non_planar} non planes</title></rect>')
        else:
            y_non = y_plan

        lines.append(f'  <text x="{x + bar_w/2:.1f}" y="{y_non - 6:.1f}" text-anchor="middle" '
                     f'font-size="12" font-weight="700" fill="#24292e">{total}</text>')
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
        f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#cf222e" stroke-width="{sw}"/>',
    ]

    # Cas 100% plan : tracer un full circle (evite un bug visuel avec stroke-dasharray a circonf complete).
    if planar > 0 and planar < total:
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="#1a7f37" stroke-width="{sw}" '
                     f'stroke-dasharray="{green_len:.2f} {circumference:.2f}" '
                     f'transform="rotate(-90 {cx} {cy})"/>')
    elif planar == total:
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="#1a7f37" stroke-width="{sw}"/>')

    lines.append(f'  <text x="{cx}" y="{cy - 4}" text-anchor="middle" '
                 f'font-size="32" font-weight="700" fill="#24292e">{pct}%</text>')
    lines.append(f'  <text x="{cx}" y="{cy + 16}" text-anchor="middle" '
                 f'font-size="12" fill="#6a737d">planes</text>')
    lines.append('</svg>')
    return "\n".join(lines)


# =====================================================================
#  Rendu HTML (helpers dedies + assemblage final)
# =====================================================================

def _load_template(name):
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _compute_per_h(all_data):
    """Agrege les donnees par h : stats + totals + donnees pour le chart.
    Retourne un dict avec tout ce dont les helpers de rendu ont besoin."""
    h_list = sorted(all_data.keys(), key=lambda x: int(x[1:]))
    totals = {"molecules": 0, "solutions": 0, "planar": 0, "non_planar": 0}
    per_h = []  # [{h_name, h_num, stats}]
    chart_data = []  # [(h_num_int, planar, non_planar)] pour le bar chart

    for h_name in h_list:
        stats = compute_stats(all_data[h_name])
        h_num = h_name[1:]
        per_h.append({"h_name": h_name, "h_num": h_num, "stats": stats})
        chart_data.append((int(h_num), stats["planar"], stats["non_planar"]))
        for k in totals:
            totals[k] += stats[k]

    return {
        "h_list": h_list,
        "per_h": per_h,
        "totals": totals,
        "chart_data": chart_data,
    }


def _render_results_row(h_num, stats):
    """Ligne principale du tableau resultats (avec barre de progression %)."""
    pct = stats["pct_planar"]
    bar_color = _pct_color(pct)
    non_cls = ' class="non-planar"' if stats["non_planar"] > 0 else ""
    return (
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


def _render_mol_mini_row(mol_name, mol):
    """Une ligne de la mini-table (detail par molecule)."""
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
    return (
        f'      <tr>'
        f'<td style="font-family:SFMono-Regular,Consolas,monospace;font-weight:600;">{mol_name}</td>'
        f'<td>{n_sol}</td>'
        f'<td class="planar">{n_plan}</td>'
        f'<td{non_cls_mol}>{n_non}</td>'
        f'<td class="{o_cls}">{o_txt}</td>'
        f'<td>{o_angle}</td>'
        f'</tr>'
    )


def _render_detail_row(h_num, mols_dict):
    """Ligne depliable (mini-table des molecules) pour un h donne."""
    mol_rows = "\n".join(
        _render_mol_mini_row(name, mols_dict[name]) for name in sorted(mols_dict.keys())
    )
    return (
        f'    <tr class="detail-row" id="detail-h{h_num}" style="display:none;">'
        f'<td colspan="7" style="padding:0;">'
        f'<div class="detail-panel">'
        f'<table class="mini-table"><thead><tr>'
        f'<th>Molecule</th><th>Solutions</th><th>Planes</th>'
        f'<th>Non pl.</th><th>Original</th><th>Angle</th>'
        f'</tr></thead><tbody>\n'
        f'{mol_rows}\n'
        f'    </tbody></table></div></td></tr>'
    )


def _render_rows_html(per_h, all_data):
    """Tableau resultats : ligne h + ligne detail, pour chaque h."""
    blocks = []
    for entry in per_h:
        h_num = entry["h_num"]
        blocks.append(_render_results_row(h_num, entry["stats"]))
        blocks.append(_render_detail_row(h_num, all_data[entry["h_name"]]["molecules"]))
    return "\n".join(blocks)


def _render_h_cards(per_h):
    """Cards cliquables (une par h) qui menent vers le viewer."""
    return "\n".join(
        f'  <a href="../output/{e["h_name"]}/view.html" target="_blank" class="card blue">'
        f'<div class="value">{e["h_name"]}</div>'
        f'<div class="label">{e["stats"]["molecules"]} molecules</div>'
        f'<div class="sub">{e["stats"]["planar"]} pl. / {e["stats"]["non_planar"]} non pl.</div></a>'
        for e in per_h
    )


def _render_batch_rows(h_list):
    """Commandes batch par h (section Commandes)."""
    return "\n".join(
        f'    <tr><td>{h}</td>'
        f'<td><code>python batch_main.py plane/benzdb/{h} --validate</code></td></tr>'
        for h in h_list
    )


def generate_html(all_data):
    """Assemble le rapport : charge le template, substitue les placeholders."""
    data = _compute_per_h(all_data)
    per_h = data["per_h"]
    totals = data["totals"]
    h_list = data["h_list"]

    template = Template(_load_template("report.html"))
    return template.safe_substitute(
        now=datetime.now().strftime("%d/%m/%Y %H:%M"),
        h_min=h_list[0][1:],
        h_max=h_list[-1][1:],
        total_molecules=totals["molecules"],
        total_solutions=totals["solutions"],
        total_planar=totals["planar"],
        total_non_planar=totals["non_planar"],
        bar_chart_svg=generate_bar_chart_svg(data["chart_data"]),
        donut_svg=generate_donut_svg(totals["planar"], totals["non_planar"]),
        rows_html=_render_rows_html(per_h, all_data),
        cards_html=_render_h_cards(per_h),
        batch_rows=_render_batch_rows(h_list),
        common_css=_load_template("common.css"),
        report_css=_load_template("report.css"),
        report_js=_load_template("report.js"),
    )


# =====================================================================
#  Main
# =====================================================================

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
    out_path.write_text(html, encoding="utf-8")

    print(f"Rapport genere : {out_path}")


if __name__ == "__main__":
    main()
