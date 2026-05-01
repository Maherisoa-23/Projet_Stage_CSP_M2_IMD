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


# === 3-bucket categorization (invariant partage avec view.js) ============
# PLANE     = always_planar + mostly_planar
# NON_PLANE = always_non_planar + mostly_non_planar
# AUTRES    = unstable + ambiguous (multi-runs) ou desaccord MR vs MD
BUCKET_COLORS = {
    "PLANE":     "#1a7f37",
    "AUTRES":    "#bf8700",
    "NON_PLANE": "#cf222e",
}
BUCKET_LABELS = {
    "PLANE":     "🟢 Plans",
    "AUTRES":    "🟡 Autres",
    "NON_PLANE": "⚫ Non plans",
}


def _class_to_bucket(cls):
    if cls in ("always_planar", "mostly_planar"):
        return "PLANE"
    if cls in ("always_non_planar", "mostly_non_planar"):
        return "NON_PLANE"
    return "AUTRES"


def _solution_bucket_3bucket(sol):
    """Bucket 3-categorie (multi-runs + MD avec AUTRES). Conserve pour
    usage futur potentiel, NON utilise par le dashboard MD-only courant."""
    runs = sol.get("runs")
    mv = sol.get("md_validation")
    mr = _class_to_bucket(runs["classification"]) if runs and runs.get("classification") else None
    md = ("PLANE" if mv.get("planar") else "NON_PLANE") if mv else None
    if mr and md:
        if mr == md:
            return mr
        if mr == "AUTRES" or md == "AUTRES":
            return "AUTRES"
        return "AUTRES"
    if mr:
        return mr
    if md:
        return md
    return "PLANE" if sol.get("planar") else "NON_PLANE"


def _solution_bucket(sol):
    """Verdict MD-only (binaire) : PLANE / NON_PLANE.
    Choix arrete : le dashboard ne parle que de MD. Si pas de bloc
    md_validation, on retombe sur le booleen sol.planar (single-run)."""
    mv = sol.get("md_validation")
    if mv is not None:
        return "PLANE" if mv.get("planar") else "NON_PLANE"
    return "PLANE" if sol.get("planar") else "NON_PLANE"


def compute_stats(data):
    """Stats agregees pour un data.json."""
    molecules = data["molecules"]
    n_mol = len(molecules)
    n_sol = 0
    buckets = {"PLANE": 0, "AUTRES": 0, "NON_PLANE": 0}
    n_plan = 0
    n_md_validated = 0
    for m in molecules.values():
        for s in m["solutions"]:
            n_sol += 1
            if s.get("planar"):
                n_plan += 1
            if s.get("md_validation") is not None:
                n_md_validated += 1
            buckets[_solution_bucket(s)] += 1
    n_non = n_sol - n_plan
    n_orig = sum(1 for m in molecules.values() if m.get("original"))
    n_orig_plan = sum(1 for m in molecules.values()
                      if m.get("original") and m["original"]["planar"])
    pct = round(100 * buckets["PLANE"] / n_sol) if n_sol > 0 else 0
    return {
        "molecules": n_mol,
        "solutions": n_sol,
        "planar": n_plan,
        "non_planar": n_non,
        "buckets": buckets,
        "md_validated": n_md_validated,
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
    """SVG bar chart empile 3 buckets : Plans (vert) / Autres (jaune) / Non plans (rouge).
    stats_by_h : [(h_num, {PLANE,AUTRES,NON_PLANE}), ...]"""
    if not stats_by_h:
        return ""
    w, h = 620, 300
    mt, mr, mb, ml = 28, 20, 48, 60
    cw = w - ml - mr
    ch = h - mt - mb
    n = len(stats_by_h)
    max_val = max(sum(b.values()) for _, b in stats_by_h) or 1

    bar_w = min(64, cw / n * 0.6)
    gap = (cw - n * bar_w) / (n + 1)

    lines = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"',
        f'  style="width:100%;max-width:{w}px;font-family:Segoe UI,system-ui,sans-serif;">',
    ]
    n_grid = 4
    for i in range(n_grid + 1):
        y = mt + ch - (i / n_grid) * ch
        val = int(round(max_val * i / n_grid))
        lines.append(f'  <line x1="{ml}" y1="{y:.1f}" x2="{w-mr}" y2="{y:.1f}" '
                     f'stroke="#e1e4e8" stroke-dasharray="4,3"/>')
        lines.append(f'  <text x="{ml-8}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#6a737d">{val}</text>')

    order = ["NON_PLANE", "AUTRES", "PLANE"]  # ordre d'empilement: bas=plan, haut=non plan
    for i, (h_num, buckets) in enumerate(stats_by_h):
        x = ml + gap + i * (bar_w + gap)
        total = sum(buckets.values())
        # Bottom-up : on commence par PLANE en bas
        y_top = mt + ch
        for key in ["PLANE", "AUTRES", "NON_PLANE"]:
            v = buckets.get(key, 0)
            if v == 0:
                continue
            seg_h = (v / max_val) * ch
            y_top -= seg_h
            lines.append(f'  <rect x="{x:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" '
                         f'height="{seg_h:.1f}" fill="{BUCKET_COLORS[key]}" rx="1">'
                         f'<title>h{h_num} : {v} {BUCKET_LABELS[key]}</title></rect>')
        lines.append(f'  <text x="{x + bar_w/2:.1f}" y="{y_top - 6:.1f}" text-anchor="middle" '
                     f'font-size="12" font-weight="700" fill="#24292e">{total}</text>')
        lines.append(f'  <text x="{x + bar_w/2:.1f}" y="{mt + ch + 22:.1f}" text-anchor="middle" '
                     f'font-size="13" font-weight="600" fill="#24292e">h{h_num}</text>')

    # Legende : 2 buckets MD-only (Plans / Non plans). AUTRES, s'il existe
    # encore dans les donnees, est rendu silencieusement empile mais absent
    # de la legende -- visuellement il sera jaune si jamais present.
    lx = w - mr - 200; ly = 6
    for i, key in enumerate(["PLANE", "NON_PLANE"]):
        cx = lx + i * 96
        lines.append(f'  <rect x="{cx}" y="{ly}" width="12" height="12" fill="{BUCKET_COLORS[key]}" rx="2"/>')
        lines.append(f'  <text x="{cx+16}" y="{ly+10}" font-size="11" fill="#6a737d">{BUCKET_LABELS[key]}</text>')

    lines.append('</svg>')
    return "\n".join(lines)


def generate_3bucket_donut_svg(buckets):
    """SVG donut 3-bucket : proportions PLANE/AUTRES/NON_PLANE."""
    total = sum(buckets.values())
    if total == 0:
        return ""
    cx, cy, r = 100, 100, 70
    sw = 24
    circumference = 2 * math.pi * r

    lines = [
        '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg"',
        '  style="width:100%;max-width:200px;font-family:Segoe UI,system-ui,sans-serif;">',
        f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e1e4e8" stroke-width="{sw}"/>',
    ]
    offset = 0.0
    for key in ["PLANE", "AUTRES", "NON_PLANE"]:
        v = buckets.get(key, 0)
        if v == 0:
            continue
        seg_len = (v / total) * circumference
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="{BUCKET_COLORS[key]}" stroke-width="{sw}" '
                     f'stroke-dasharray="{seg_len:.2f} {circumference - seg_len:.2f}" '
                     f'stroke-dashoffset="{-offset:.2f}" '
                     f'transform="rotate(-90 {cx} {cy})"/>')
        offset += seg_len

    pct_pl = round(100 * buckets.get("PLANE", 0) / total)
    lines.append(f'  <text x="{cx}" y="{cy - 4}" text-anchor="middle" '
                 f'font-size="32" font-weight="700" fill="#24292e">{pct_pl}%</text>')
    lines.append(f'  <text x="{cx}" y="{cy + 16}" text-anchor="middle" '
                 f'font-size="11" fill="#6a737d">plans</text>')
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
#  Multi-runs : stabilite (agregats + SVG pie + scatter)
# =====================================================================

# Invariant partage avec templates/view.js (CLASSIFICATIONS).
# Ordre = ordre d'affichage dans le camembert et la legende.
CLASSIFICATIONS = [
    ("always_planar",     "Toujours plan",     "\U0001F7E2", "#1a7f37"),
    ("mostly_planar",     "Majorit. plan",     "\U0001F7E1", "#6fb347"),
    ("unstable",          "Instable",          "\U0001F7E0", "#e66f00"),
    ("mostly_non_planar", "Majorit. non-plan", "\U0001F534", "#c72d0f"),
    ("always_non_planar", "Toujours non-plan", "\u26AB",     "#cf222e"),
    ("ambiguous",         "Ambigu",            "\u26AA",     "#6a737d"),
]
CLASS_INFO = {key: (label, emoji, color) for key, label, emoji, color in CLASSIFICATIONS}


def _walk_all_solutions(all_data):
    """Generator : yield (h_name, cfg_name, mol_name, sol) pour TOUTES les
    solutions de tous les data.json multi-config. Ne filtre pas sur la
    presence d'un bloc particulier -- au consommateur de filtrer."""
    experiments_dir = Path(__file__).parent
    output_dir = experiments_dir / "output"
    for data_file in sorted(output_dir.glob("*/*/data.json")):
        cfg_name = data_file.parent.name
        h_name = data_file.parent.parent.name
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for mol_name, mol in d.get("molecules", {}).items():
            for sol in mol.get("solutions", []):
                yield h_name, cfg_name, mol_name, sol


def _walk_solutions_with_runs(all_data):
    """Comme _walk_all_solutions mais filtre uniquement les solutions avec
    un bloc 'runs' (multi-runs). Conserve pour retrocompat."""
    for h_name, cfg_name, mol_name, sol in _walk_all_solutions(all_data):
        if sol.get("runs"):
            yield h_name, cfg_name, mol_name, sol


def _compute_stability(all_data):
    """Agrege les donnees multi-runs : counts globaux/h, points pour scatter.
    Retourne None si aucune solution n'a de bloc runs."""
    counts_global = {key: 0 for key, *_ in CLASSIFICATIONS}
    counts_per_h = {}   # {h_name: {class_key: count}}
    points = []         # [(angle_mean, angle_std, classification, h, cfg, mol)]
    has_any = False

    for h_name, cfg_name, mol_name, sol in _walk_solutions_with_runs(all_data):
        has_any = True
        runs = sol["runs"]
        c = runs.get("classification", "ambiguous")
        if c not in counts_global:
            c = "ambiguous"
        counts_global[c] += 1
        counts_per_h.setdefault(h_name, {key: 0 for key, *_ in CLASSIFICATIONS})
        counts_per_h[h_name][c] += 1
        points.append({
            "mean": runs.get("angle_mean", 0.0),
            "std":  runs.get("angle_std", 0.0),
            "class": c,
            "h": h_name, "cfg": cfg_name, "mol": mol_name,
            "sizes": sol.get("sizes", ""),
        })

    if not has_any:
        return None
    return {
        "counts_global": counts_global,
        "counts_per_h": counts_per_h,
        "points": points,
        "total": sum(counts_global.values()),
    }


def generate_pie_svg(counts_by_class):
    """SVG camembert : proportions des classes de stabilite.
    Les parts sont tracees comme des arcs <path> pour controler l'ordre et
    les couleurs (contrairement a stroke-dasharray du donut a 2 couleurs)."""
    total = sum(counts_by_class.values())
    if total == 0:
        return ""

    w, h_ = 240, 240
    cx, cy, r = w / 2, h_ / 2, 95
    lines = [
        f'<svg viewBox="0 0 {w} {h_}" xmlns="http://www.w3.org/2000/svg"',
        f'  style="width:100%;max-width:{w}px;font-family:Segoe UI,system-ui,sans-serif;">',
    ]

    # Cas special : une seule classe avec 100% -> full circle (sinon arc se boucle mal)
    non_zero = [(key, counts_by_class[key]) for key, *_ in CLASSIFICATIONS if counts_by_class.get(key, 0) > 0]
    if len(non_zero) == 1:
        only_key, only_count = non_zero[0]
        color = CLASS_INFO[only_key][2]
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}">')
        lines.append(f'    <title>{CLASS_INFO[only_key][0]} : {only_count} ({100}%)</title></circle>')
    else:
        angle = -math.pi / 2  # demarre en haut
        for key, count in non_zero:
            frac = count / total
            sweep = frac * 2 * math.pi
            end = angle + sweep
            x1 = cx + r * math.cos(angle)
            y1 = cy + r * math.sin(angle)
            x2 = cx + r * math.cos(end)
            y2 = cy + r * math.sin(end)
            large = 1 if sweep > math.pi else 0
            color = CLASS_INFO[key][2]
            label = CLASS_INFO[key][0]
            pct = round(100 * frac)
            path = (f'M {cx} {cy} L {x1:.2f} {y1:.2f} '
                    f'A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} Z')
            lines.append(f'  <path d="{path}" fill="{color}" stroke="#fff" stroke-width="2">')
            lines.append(f'    <title>{label} : {count} ({pct}%)</title></path>')
            angle = end

    lines.append(f'  <text x="{cx}" y="{cy - 4}" text-anchor="middle" '
                 f'font-size="22" font-weight="700" fill="#fff" '
                 f'style="paint-order:stroke;stroke:#24292e;stroke-width:4px">{total}</text>')
    lines.append(f'  <text x="{cx}" y="{cy + 14}" text-anchor="middle" '
                 f'font-size="11" fill="#fff" '
                 f'style="paint-order:stroke;stroke:#24292e;stroke-width:3px">solutions</text>')
    lines.append('</svg>')
    return "\n".join(lines)


def _compute_md_stats(all_data):
    """Compte global et per-h des verdicts MD. Retourne None si aucune
    solution n'a de bloc md_validation."""
    counts_global = {"planar": 0, "non_planar": 0}
    counts_per_h = {}
    has_any = False
    for h_name, cfg_name, mol_name, sol in _walk_all_solutions(all_data):
        mv = sol.get("md_validation")
        if not mv:
            continue
        has_any = True
        key = "planar" if mv.get("planar") else "non_planar"
        counts_global[key] += 1
        counts_per_h.setdefault(h_name, {"planar": 0, "non_planar": 0})
        counts_per_h[h_name][key] += 1
    if not has_any:
        return None
    return {
        "counts_global": counts_global,
        "counts_per_h": counts_per_h,
        "total": sum(counts_global.values()),
    }


def _collect_method_compare_points(all_data):
    """Pour chaque solution ayant LES DEUX blocs (runs ET md_validation),
    retourne un point (x=runs.angle_mean, y=md_validation.angle_deg) pour
    le scatter de comparaison des methodes."""
    points = []
    for h_name, cfg_name, mol_name, sol in _walk_all_solutions(all_data):
        runs = sol.get("runs")
        mv = sol.get("md_validation")
        if not runs or not mv:
            continue
        x = runs.get("angle_mean")
        y = mv.get("angle_deg")
        if x is None or y is None:
            continue
        # Categorie d'accord pour le code couleur :
        #   - both_planar : multi-runs (always_/mostly_planar) ET md.planar=True
        #   - both_non    : multi-runs non plan ET md.planar=False
        #   - disagree    : les 2 methodes divergent
        c = runs.get("classification", "ambiguous")
        is_mr_planar = (c == "always_planar" or c == "mostly_planar")
        is_md_planar = bool(mv.get("planar"))
        if is_mr_planar and is_md_planar:
            agree = "both_planar"
        elif (not is_mr_planar) and (not is_md_planar):
            agree = "both_non_planar"
        else:
            agree = "disagree"
        points.append({
            "x": x, "y": y, "agree": agree,
            "h": h_name, "cfg": cfg_name, "mol": mol_name,
            "sizes": sol.get("sizes", ""),
            "mr_class": c, "md_planar": is_md_planar,
        })
    return points


def generate_method_compare_svg(points):
    """SVG scatter X=multi-runs angle_mean, Y=MD angle_deg.
    1 point = 1 solution validee par les 2 methodes. Couleur = accord :
    vert (les 2 plates), rouge fonce (les 2 non plates), orange (divergent).
    Diagonale y=x : les 2 methodes donnent le meme angle. Lignes seuil 10 deg
    sur les 2 axes."""
    if not points:
        return ""

    w, h_ = 680, 480
    mt, mr, mb, ml = 24, 24, 56, 64
    cw = w - ml - mr
    ch = h_ - mt - mb

    # Echelle commune sur les 2 axes pour faciliter la lecture diagonale.
    max_v = max(max(p["x"] for p in points), max(p["y"] for p in points))
    xmax = max(12, min(40, max_v * 1.1))
    ymax = xmax  # axes carrees

    def to_x(v): return ml + min(1.0, v / xmax) * cw
    def to_y(v): return mt + ch - min(1.0, v / ymax) * ch

    AGREE_COLORS = {
        "both_planar":     "#1a7f37",   # vert
        "both_non_planar": "#cf222e",   # rouge
        "disagree":        "#e66f00",   # orange (alerte)
    }

    lines = [
        f'<svg viewBox="0 0 {w} {h_}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{w}px;font-family:Segoe UI,system-ui,sans-serif;">',
    ]

    # Grille
    n_grid = 5
    for i in range(n_grid + 1):
        v = xmax * i / n_grid
        x = ml + (i / n_grid) * cw
        y = mt + ch - (i / n_grid) * ch
        lines.append(f'  <line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt+ch}" '
                     f'stroke="#e1e4e8" stroke-dasharray="3,3"/>')
        lines.append(f'  <line x1="{ml}" y1="{y:.1f}" x2="{ml+cw}" y2="{y:.1f}" '
                     f'stroke="#e1e4e8" stroke-dasharray="3,3"/>')
        lines.append(f'  <text x="{x:.1f}" y="{mt+ch+16}" text-anchor="middle" '
                     f'font-size="11" fill="#6a737d">{v:.0f}</text>')
        lines.append(f'  <text x="{ml-6}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#6a737d">{v:.0f}</text>')

    # Diagonale y=x : si les 2 methodes donnent le meme angle, le point y est
    diag_x1 = ml; diag_y1 = mt + ch
    diag_x2 = ml + cw; diag_y2 = mt
    lines.append(f'  <line x1="{diag_x1}" y1="{diag_y1:.1f}" x2="{diag_x2}" y2="{diag_y2:.1f}" '
                 f'stroke="#0969da" stroke-width="1" stroke-dasharray="6,4" opacity="0.5"/>')
    lines.append(f'  <text x="{diag_x2 - 4:.1f}" y="{diag_y2 + 12:.1f}" text-anchor="end" '
                 f'font-size="10" fill="#0969da" font-style="italic">y = x (accord parfait)</text>')

    # Lignes seuil 10 deg sur les 2 axes
    if 10 <= xmax:
        tx = to_x(10); ty = to_y(10)
        lines.append(f'  <line x1="{tx:.1f}" y1="{mt}" x2="{tx:.1f}" y2="{mt+ch}" '
                     f'stroke="#bf8700" stroke-width="1.2" stroke-dasharray="4,3"/>')
        lines.append(f'  <line x1="{ml}" y1="{ty:.1f}" x2="{ml+cw}" y2="{ty:.1f}" '
                     f'stroke="#bf8700" stroke-width="1.2" stroke-dasharray="4,3"/>')
        lines.append(f'  <text x="{tx + 4:.1f}" y="{mt+12}" text-anchor="start" '
                     f'font-size="10" fill="#bf8700" font-weight="600">seuil 10&#176;</text>')

    # Axis labels
    lines.append(f'  <text x="{ml+cw/2:.1f}" y="{h_-8}" text-anchor="middle" '
                 f'font-size="12" font-weight="600" fill="#24292e">Multi-runs &mdash; angle moyen &#956; (&#176;)</text>')
    lines.append(f'  <text x="14" y="{mt+ch/2:.1f}" text-anchor="middle" '
                 f'font-size="12" font-weight="600" fill="#24292e" '
                 f'transform="rotate(-90 14 {mt+ch/2:.1f})">MD &mdash; angle final (&#176;)</text>')

    # Points : ordre = both_planar puis both_non puis disagree (au-dessus pour visibilite)
    order = ["both_planar", "both_non_planar", "disagree"]
    sorted_pts = sorted(points, key=lambda p: order.index(p["agree"]))
    for p in sorted_pts:
        color = AGREE_COLORS[p["agree"]]
        x = to_x(p["x"]); y = to_y(p["y"])
        verdict_label = {"both_planar": "Accord (planes)",
                          "both_non_planar": "Accord (non planes)",
                          "disagree": "DIVERGENCE"}[p["agree"]]
        tooltip = (f'{p["h"]}/{p["cfg"]} - {p["mol"]} [{p["sizes"]}] | '
                   f'multi-runs: μ={p["x"]}° ({p["mr_class"]}), MD: {p["y"]}° '
                   f'({"plan" if p["md_planar"] else "non plan"}) | {verdict_label}')
        lines.append(f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" '
                     f'stroke="#fff" stroke-width="1" opacity="0.9">')
        lines.append(f'    <title>{tooltip}</title></circle>')

    lines.append('</svg>')
    return "\n".join(lines)


def generate_scatter_svg(points):
    """SVG scatter plot : X = angle_mean, Y = angle_std, couleur = classe.
    Ligne verticale pointillee au seuil x=10 deg. Tooltip <title> par point."""
    if not points:
        return ""

    w, h_ = 680, 420
    mt, mr, mb, ml = 24, 24, 52, 54
    cw = w - ml - mr
    ch = h_ - mt - mb

    # Limites : X cappe a 40 deg, Y cappe a 10 deg (pertinent pour xTB planarite).
    max_mean = max(p["mean"] for p in points)
    max_std = max(p["std"] for p in points)
    xmax = max(12, min(40, max_mean * 1.1))
    ymax = max(2, min(10, max_std * 1.15))
    if ymax < 0.5:
        ymax = 0.5

    def to_x(v): return ml + min(1.0, v / xmax) * cw
    def to_y(v): return mt + ch - min(1.0, v / ymax) * ch

    lines = [
        f'<svg viewBox="0 0 {w} {h_}" xmlns="http://www.w3.org/2000/svg"',
        f'  style="width:100%;max-width:{w}px;font-family:Segoe UI,system-ui,sans-serif;">',
    ]

    # Grille + labels
    n_grid_x = 5
    for i in range(n_grid_x + 1):
        xv = xmax * i / n_grid_x
        x = ml + (i / n_grid_x) * cw
        lines.append(f'  <line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt+ch}" '
                     f'stroke="#e1e4e8" stroke-dasharray="3,3"/>')
        lines.append(f'  <text x="{x:.1f}" y="{mt+ch+16}" text-anchor="middle" '
                     f'font-size="11" fill="#6a737d">{xv:.0f}</text>')
    n_grid_y = 4
    for i in range(n_grid_y + 1):
        yv = ymax * i / n_grid_y
        y = mt + ch - (i / n_grid_y) * ch
        lines.append(f'  <line x1="{ml}" y1="{y:.1f}" x2="{ml+cw}" y2="{y:.1f}" '
                     f'stroke="#e1e4e8" stroke-dasharray="3,3"/>')
        lines.append(f'  <text x="{ml-6}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#6a737d">{yv:.1f}</text>')

    # Ligne du seuil 10 deg (x)
    if 10 <= xmax:
        tx = to_x(10)
        lines.append(f'  <line x1="{tx:.1f}" y1="{mt}" x2="{tx:.1f}" y2="{mt+ch}" '
                     f'stroke="#bf8700" stroke-width="1.2" stroke-dasharray="4,3"/>')
        lines.append(f'  <text x="{tx:.1f}" y="{mt-6}" text-anchor="middle" '
                     f'font-size="10" fill="#bf8700" font-weight="600">seuil 10&#176;</text>')

    # Axis labels
    lines.append(f'  <text x="{ml+cw/2:.1f}" y="{h_-8}" text-anchor="middle" '
                 f'font-size="12" font-weight="600" fill="#24292e">Angle moyen &#956; (&#176;)</text>')
    lines.append(f'  <text x="14" y="{mt+ch/2:.1f}" text-anchor="middle" '
                 f'font-size="12" font-weight="600" fill="#24292e" '
                 f'transform="rotate(-90 14 {mt+ch/2:.1f})">Ecart-type &#963; (&#176;)</text>')

    # Points (ordre : classes stables d'abord, puis instables par-dessus pour visibilite)
    order = ["always_planar", "mostly_planar", "always_non_planar", "mostly_non_planar", "ambiguous", "unstable"]
    sorted_pts = sorted(points, key=lambda p: order.index(p["class"]) if p["class"] in order else 99)
    for p in sorted_pts:
        color = CLASS_INFO.get(p["class"], CLASS_INFO["ambiguous"])[2]
        x = to_x(p["mean"])
        y = to_y(p["std"])
        # Tooltip via <title>. sizes peut contenir '<' ? Non (format v0=5 v1=7...), safe.
        label_class = CLASS_INFO.get(p["class"], CLASS_INFO["ambiguous"])[0]
        tooltip = f'{p["h"]}/{p["cfg"]} - {p["mol"]} [{p["sizes"]}] | {label_class} | μ={p["mean"]}° σ={p["std"]}°'
        lines.append(f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" '
                     f'stroke="#fff" stroke-width="1" opacity="0.85">')
        lines.append(f'    <title>{tooltip}</title></circle>')

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
    totals = {"molecules": 0, "solutions": 0, "planar": 0, "non_planar": 0,
              "buckets": {"PLANE": 0, "AUTRES": 0, "NON_PLANE": 0}}
    per_h = []  # [{h_name, h_num, stats}]
    chart_data = []  # [(h_num_int, {PLANE,AUTRES,NON_PLANE}), ...]

    for h_name in h_list:
        stats = compute_stats(all_data[h_name])
        h_num = h_name[1:]
        per_h.append({"h_name": h_name, "h_num": h_num, "stats": stats})
        chart_data.append((int(h_num), stats["buckets"]))
        for k in ("molecules", "solutions", "planar", "non_planar"):
            totals[k] += stats[k]
        for bk in totals["buckets"]:
            totals["buckets"][bk] += stats["buckets"][bk]

    return {
        "h_list": h_list,
        "per_h": per_h,
        "totals": totals,
        "chart_data": chart_data,
    }


def _bucket_pill(key, count):
    return (f'<span class="bucket-pill" style="background:{BUCKET_COLORS[key]}1a;'
            f'color:{BUCKET_COLORS[key]};border:1px solid {BUCKET_COLORS[key]}">'
            f'{count} {BUCKET_LABELS[key]}</span>')


def _render_bucket_bar_inline(buckets, width=180):
    """Mini barre 3-bucket inline (proportions). Width en px."""
    total = sum(buckets.values()) or 1
    parts = ['<div class="inline-bucket-bar" style="width:{}px;">'.format(width)]
    for key in ["PLANE", "AUTRES", "NON_PLANE"]:
        v = buckets.get(key, 0)
        if v == 0:
            continue
        pct = 100 * v / total
        parts.append(f'<span style="background:{BUCKET_COLORS[key]};width:{pct:.1f}%;" '
                     f'title="{v} {BUCKET_LABELS[key]}"></span>')
    parts.append('</div>')
    return "".join(parts)


def _render_results_row(h_num, stats):
    """Ligne tableau dashboard MD-only : h | mol | sol | bar | plans | non plans | originaux.
    Les counts PLANE/NON_PLANE sont MD-based (via _solution_bucket)."""
    bk = stats["buckets"]
    pct = stats["pct_planar"]
    pills = (_bucket_pill("PLANE", bk["PLANE"]) +
             _bucket_pill("NON_PLANE", bk["NON_PLANE"]))
    return (
        f'    <tr class="h-row">'
        f'<td class="h-toggle" onclick="toggleDetail(\'h{h_num}\')">'
        f'<strong>h={h_num}</strong> <span class="chevron" id="chev-h{h_num}">&#9654;</span></td>'
        f'<td>{stats["molecules"]}</td>'
        f'<td>{stats["solutions"]}</td>'
        f'<td>{_render_bucket_bar_inline(bk)}</td>'
        f'<td class="bucket-pills-cell">{pills}</td>'
        f'<td><b>{pct}%</b></td>'
        f'<td class="planar">{stats["originals_planar"]}/{stats["originals"]}</td>'
        f'</tr>'
    )


def _render_mol_mini_row(mol_name, mol):
    """Une ligne de la mini-table : nom mol + counts par bucket + original."""
    bk = {"PLANE": 0, "AUTRES": 0, "NON_PLANE": 0}
    for s in mol["solutions"]:
        bk[_solution_bucket(s)] += 1
    n_sol = len(mol["solutions"])
    orig = mol.get("original")
    if orig:
        o_cls = "planar" if orig["planar"] else "non-planar"
        o_txt = "PLAN" if orig["planar"] else "NON PLAN"
        o_angle = f'{orig["angle_deg"]}&deg;'
    else:
        o_cls = "na"
        o_txt = "-"
        o_angle = "-"
    return (
        f'      <tr>'
        f'<td style="font-family:SFMono-Regular,Consolas,monospace;font-weight:600;">{mol_name}</td>'
        f'<td>{n_sol}</td>'
        f'<td style="color:{BUCKET_COLORS["PLANE"]};font-weight:700">{bk["PLANE"]}</td>'
        f'<td style="color:{BUCKET_COLORS["NON_PLANE"]};font-weight:700">{bk["NON_PLANE"]}</td>'
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
        f'<th>Molecule</th><th>Sol.</th>'
        f'<th>🟢 Plans</th><th>⚫ Non pl.</th>'
        f'<th>Original</th><th>Angle</th>'
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
    """Cards cliquables (une par h) qui menent vers le viewer.
    Affiche les 3 buckets en sub-text."""
    out = []
    for e in per_h:
        bk = e["stats"]["buckets"]
        sub = (f'<span style="color:{BUCKET_COLORS["PLANE"]}">{bk["PLANE"]} pl.</span> · '
               f'<span style="color:{BUCKET_COLORS["NON_PLANE"]}">{bk["NON_PLANE"]} non pl.</span>')
        out.append(
            f'  <a href="../output/{e["h_name"]}/view.html" target="_blank" class="card blue">'
            f'<div class="value">{e["h_name"]}</div>'
            f'<div class="label">{e["stats"]["molecules"]} molecules &middot; {e["stats"]["solutions"]} sol.</div>'
            f'<div class="sub">{sub}</div></a>'
        )
    return "\n".join(out)


def _render_batch_rows(h_list):
    """Commandes batch par h (section Commandes -- legacy mono-run)."""
    return "\n".join(
        f'    <tr><td>{h}</td>'
        f'<td><code>python batch_main.py plane/benzdb/{h} --validate</code></td></tr>'
        for h in h_list
    )


def _render_batch_rows_md(h_list):
    """Lignes 'Batch MD pour hX' par h (section Commandes, sous-section MD)."""
    return "\n".join(
        f'    <tr><td>Batch MD pour {h}</td>'
        f'<td><code>python batch_all.py plane/benzdb/{h} --method md</code></td></tr>'
        for h in h_list
    )


def _render_batch_rows_mr(h_list):
    """Lignes 'Batch multi-runs pour hX' par h."""
    return "\n".join(
        f'    <tr><td>Batch multi-runs pour {h}</td>'
        f'<td><code>python batch_all.py plane/benzdb/{h} --n-runs 10</code></td></tr>'
        for h in h_list
    )


def _render_stability_cards(stab):
    """Cards de stabilite (une par classe)."""
    cards = []
    for key, label, emoji, color in CLASSIFICATIONS:
        n = stab["counts_global"].get(key, 0)
        cards.append(
            f'  <div class="card" style="border-top-color:{color}">'
            f'<div class="value" style="color:{color}">{n}</div>'
            f'<div class="label">{emoji} {label}</div></div>'
        )
    return "\n".join(cards)


def _render_stability_per_h_rows(stab, h_list):
    """Lignes du tableau par h dans la section stabilite."""
    rows = []
    for h_name in h_list:
        counts = stab["counts_per_h"].get(h_name, {})
        total = sum(counts.values())
        if total == 0:
            rows.append(
                f'    <tr><td><strong>{h_name}</strong></td>'
                f'<td colspan="6" class="na">(pas de runs)</td></tr>'
            )
            continue
        cells = []
        for key, label, emoji, color in CLASSIFICATIONS:
            n = counts.get(key, 0)
            if n == 0:
                cells.append(f'<td class="na">0</td>')
            else:
                cells.append(f'<td style="color:{color};font-weight:600" '
                             f'title="{label}">{emoji} {n}</td>')
        rows.append(
            f'    <tr><td><strong>{h_name}</strong></td>'
            f'<td>{total}</td>'
            + "".join(cells)
            + '</tr>'
        )
    return "\n".join(rows)


def _render_stability_section(stab, h_list):
    """Assemble le HTML de la section stabilite complete (cards + pie +
    scatter + tableau per-h). Retourne chaine vide si stab est None."""
    if stab is None:
        return ""
    return f"""
<section id="stabilite">
<h2><span class="section-num">4</span> Stabilite inter-runs</h2>

<p>
  xTB est un optimiseur local avec perturbation aleatoire initiale : un meme calcul
  peut donner des angles differents entre runs. Pour caracteriser la <b>stabilite</b>
  d'une solution, on la lance N fois et on classe selon la distribution des angles.
</p>

<div class="cards">
{_render_stability_cards(stab)}
</div>

<div class="charts-row">
  <div class="chart-box">
    <h3 style="margin-top:0">Distribution des classes</h3>
    {generate_pie_svg(stab['counts_global'])}
  </div>
  <div class="chart-box wide">
    <h3 style="margin-top:0">Angle moyen &times; ecart-type par solution</h3>
    {generate_scatter_svg(stab['points'])}
    <p style="font-size:0.82em;color:var(--text-muted);margin:8px 0 0;">
      Chaque point = 1 solution. Couleur = classification. La ligne verticale jaune
      marque le seuil de planarite 10&deg;. Survolez un point pour voir les details.
    </p>
  </div>
</div>

<h3>Par taille de benzenoide</h3>
<table class="results stability-table">
  <thead>
    <tr>
      <th>h</th><th>Total</th>
      <th>&#x1F7E2; Toujours pl.</th>
      <th>&#x1F7E1; Majorit. pl.</th>
      <th>&#x1F7E0; Instable</th>
      <th>&#x1F534; Majorit. non-pl.</th>
      <th>&#x26AB; Toujours non-pl.</th>
      <th>&#x26AA; Ambigu</th>
    </tr>
  </thead>
  <tbody>
{_render_stability_per_h_rows(stab, h_list)}
  </tbody>
</table>
</section>
"""


def _render_md_section(md_stats, compare_points, h_list):
    """HTML de la section 'Validation MD' (apres section Stabilite).

    Affiche :
      - cards : counts plans/non-plans MD (global)
      - donut : % plans MD
      - scatter de comparaison μ_multi-runs vs angle_MD (si on a des
        solutions avec les 2 blocs)
      - tableau par h : counts MD par taille

    Si md_stats est None, retourne chaine vide (section masquee)."""
    if md_stats is None:
        return ""

    n_pl = md_stats["counts_global"]["planar"]
    n_non = md_stats["counts_global"]["non_planar"]
    total = md_stats["total"]
    pct = round(100 * n_pl / total) if total else 0

    # Cards globales
    cards = (
        f'  <div class="card blue"><div class="value">{total}</div>'
        f'<div class="label">Solutions validees MD</div></div>\n'
        f'  <div class="card green"><div class="value">{n_pl}</div>'
        f'<div class="label">🧬 Plans (MD)</div></div>\n'
        f'  <div class="card red"><div class="value">{n_non}</div>'
        f'<div class="label">🧬 Non plans (MD)</div></div>\n'
        f'  <div class="card" style="border-top-color:#8b5cf6">'
        f'<div class="value" style="color:#6d28d9">{pct}%</div>'
        f'<div class="label">% plans MD</div></div>'
    )

    # Tableau per-h
    rows = []
    for h_name in h_list:
        c = md_stats["counts_per_h"].get(h_name, {"planar": 0, "non_planar": 0})
        ph = c["planar"]; np_ = c["non_planar"]; tot = ph + np_
        if tot == 0:
            rows.append(f'    <tr><td><strong>{h_name}</strong></td>'
                        f'<td colspan="3" class="na">(pas de donnees MD)</td></tr>')
        else:
            ppct = round(100 * ph / tot)
            rows.append(
                f'    <tr><td><strong>{h_name}</strong></td>'
                f'<td>{tot}</td>'
                f'<td class="planar">{ph}</td>'
                f'<td class="non-planar">{np_}</td>'
                f'<td><b>{ppct}%</b></td></tr>'
            )
    per_h_rows = "\n".join(rows)

    # Section scatter de comparaison (visible seulement si donnees suffisantes)
    if compare_points:
        # Stats agreement
        n_agree_pl = sum(1 for p in compare_points if p["agree"] == "both_planar")
        n_agree_non = sum(1 for p in compare_points if p["agree"] == "both_non_planar")
        n_disagree = sum(1 for p in compare_points if p["agree"] == "disagree")
        total_pairs = len(compare_points)
        pct_agree = round(100 * (n_agree_pl + n_agree_non) / total_pairs) if total_pairs else 0

        compare_block = f"""
<h3>Comparaison multi-runs vs MD</h3>
<p>
  Pour les <b>{total_pairs}</b> solutions validees par les <b>2 methodes</b>,
  on compare l'angle moyen des multi-runs (μ) avec l'angle final apres MD+opt.
  Accord global : <b>{pct_agree}%</b> ({n_agree_pl} plans + {n_agree_non} non plans).
  <span class="non-planar">{n_disagree} divergences</span> a investiguer.
</p>
<div class="charts-row">
  <div class="chart-box wide">
    {generate_method_compare_svg(compare_points)}
    <p class="caption" style="font-size:0.82em;color:var(--text-muted);margin:8px 0 0;">
      Chaque point = 1 solution. Vert = les 2 methodes plates, rouge = les 2 non plates,
      orange = divergence. Les lignes pointillees jaunes marquent le seuil 10°.
      La diagonale bleue (y=x) materialise un accord parfait sur l'angle.
    </p>
  </div>
</div>
"""
    else:
        compare_block = ""

    return f"""
<section id="validation-md">
<h2><span class="section-num">5</span> Validation MD (xtb --md + opt)</h2>

<p>
  Validation par dynamique moleculaire courte (1 ps a 298 K) suivie d'une
  optimisation finale, selon le protocole recommande par les chimistes.
  Compare aux multi-runs : 1 seul run par solution (vs N=10), exploration
  thermique reelle pour casser les symetries plates parasites avant l'opt.
</p>

<div class="cards">
{cards}
</div>

<h3>Par taille de benzenoide</h3>
<table class="results">
  <thead>
    <tr><th>h</th><th>Total</th><th>🧬 Plans</th><th>🧬 Non plans</th><th>% plans</th></tr>
  </thead>
  <tbody>
{per_h_rows}
  </tbody>
</table>
{compare_block}
</section>
"""


def _compute_dashboard_kpis(all_data, totals):
    """KPIs hero du dashboard : counts + % accord MR/MD."""
    n_pairs = 0
    n_agree = 0
    n_disagree_pl_non = 0  # MR plan, MD non plan ou inverse (cas critiques)
    divergences = []       # liste detaillee pour la section "alertes"
    for h_name, cfg, mol, sol in _walk_all_solutions(all_data):
        runs = sol.get("runs")
        mv = sol.get("md_validation")
        if not (runs and mv):
            continue
        n_pairs += 1
        mr_b = _class_to_bucket(runs.get("classification", "ambiguous"))
        md_b = "PLANE" if mv.get("planar") else "NON_PLANE"
        if mr_b == md_b:
            n_agree += 1
        else:
            if (mr_b == "PLANE" and md_b == "NON_PLANE") or (mr_b == "NON_PLANE" and md_b == "PLANE"):
                n_disagree_pl_non += 1
                divergences.append({
                    "h": h_name, "cfg": cfg, "mol": mol,
                    "sizes": sol.get("sizes", ""),
                    "mr": runs.get("classification"), "md": "plan" if mv.get("planar") else "non plan",
                    "mu": runs.get("angle_mean"), "md_angle": mv.get("angle_deg"),
                })
    pct_agree = round(100 * n_agree / n_pairs) if n_pairs > 0 else None
    pct_plane_global = (round(100 * totals["buckets"]["PLANE"] / totals["solutions"])
                        if totals["solutions"] > 0 else 0)
    return {
        "n_pairs": n_pairs,
        "n_agree": n_agree,
        "pct_agree": pct_agree,
        "n_disagree_pl_non": n_disagree_pl_non,
        "divergences": divergences,
        "pct_plane_global": pct_plane_global,
    }


def _render_hero(totals, kpis, h_min, h_max, now):
    """Hero MD-only : 4 KPIs uniformes (BIG = compte absolu, sub = % ou contexte).
    Plans / Non plans sont basees uniquement sur le verdict MD (md_validation.planar)."""
    bk = totals["buckets"]
    n_sol = totals["solutions"]
    pct_pl  = round(100 * bk["PLANE"] / n_sol)     if n_sol else 0
    pct_non = round(100 * bk["NON_PLANE"] / n_sol) if n_sol else 0
    return f"""
<section class="hero">
  <div class="hero-meta">BenzAI DB &middot; h{h_min} a h{h_max} &middot; mis a jour le {now}</div>
  <div class="kpi-grid">
    <div class="kpi-tile primary">
      <div class="kpi-value">{totals["molecules"]}</div>
      <div class="kpi-label">Molecules</div>
      <div class="kpi-sub">h{h_min} a h{h_max}</div>
    </div>
    <div class="kpi-tile primary">
      <div class="kpi-value">{n_sol}</div>
      <div class="kpi-label">Solutions CSP</div>
      <div class="kpi-sub">toutes configurations</div>
    </div>
    <div class="kpi-tile plane">
      <div class="kpi-value">{bk["PLANE"]}</div>
      <div class="kpi-label">🟢 Plans (MD)</div>
      <div class="kpi-sub">{pct_pl}% des solutions</div>
    </div>
    <div class="kpi-tile nonplane">
      <div class="kpi-value">{bk["NON_PLANE"]}</div>
      <div class="kpi-label">⚫ Non plans (MD)</div>
      <div class="kpi-sub">{pct_non}% des solutions</div>
    </div>
  </div>
</section>
"""


def _render_alerts(kpis):
    """Strip d'alertes : s'affiche uniquement si quelque chose de notable."""
    items = []
    n_div = kpis["n_disagree_pl_non"]
    if n_div > 0:
        items.append(
            f'<li><b>{n_div} divergence(s) franche(s) MR vs MD</b> '
            f'(une methode dit plan, l\'autre non plan). Voir section MD ci-dessous.</li>'
        )
    if not items:
        return ""
    return f"""
<section class="alerts">
  <div class="alerts-header">⚠ Points d'attention</div>
  <ul>{''.join(items)}</ul>
</section>
"""


def _render_divergences_block(divergences):
    """Tableau des divergences franches MR plan vs MD non plan (ou inverse)."""
    if not divergences:
        return ""
    rows = []
    for d in divergences:
        rows.append(
            f'<tr><td>{d["h"]}/{d["cfg"]}</td>'
            f'<td><code>{d["mol"]}</code></td>'
            f'<td><code>{d["sizes"]}</code></td>'
            f'<td>{d["mr"]} (&mu;={d["mu"]}&deg;)</td>'
            f'<td>{d["md"]} ({d["md_angle"]}&deg;)</td></tr>'
        )
    return f"""
<details class="divergences" open>
  <summary>Divergences MR vs MD ({len(divergences)} cas)</summary>
  <table class="mini-table">
    <thead><tr><th>h / config</th><th>Molecule</th><th>Tailles</th><th>Multi-runs</th><th>MD</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</details>
"""


def generate_html(all_data):
    """Assemble le dashboard : charge le template, substitue les placeholders."""
    data = _compute_per_h(all_data)
    per_h = data["per_h"]
    totals = data["totals"]
    h_list = data["h_list"]
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    kpis = _compute_dashboard_kpis(all_data, totals)

    # === Dashboard MD-only ===
    # Choix : ne plus mentionner les multi-runs dans le resume. Les helpers
    # _compute_stability / _compute_dashboard_kpis (accord MR/MD) /
    # _render_alerts (divergences MR vs MD) / _render_md_section (avec
    # comparaison MR vs MD) / _collect_method_compare_points existent
    # toujours et restent appelables, mais on ne les rend pas dans la page.

    # Section MD masquee : redondante avec le hero et le tableau "Par taille"
    # qui sont deja MD-only. Helper _render_md_section conserve dans le code.
    md_section = ""
    md_nav = ""

    # Sections multi-runs masquees du dashboard (mais pas du code) :
    stability_section = ""

    template = Template(_load_template("report.html"))
    return template.safe_substitute(
        now=now,
        h_min=h_list[0][1:],
        h_max=h_list[-1][1:],
        total_molecules=totals["molecules"],
        total_solutions=totals["solutions"],
        total_planar=totals["planar"],
        total_non_planar=totals["non_planar"],
        hero_section=_render_hero(totals, kpis, h_list[0][1:], h_list[-1][1:], now),
        # Alertes et divergences sont des signaux MR vs MD : retires du
        # dashboard MD-only mais helpers conserves dans le code.
        alerts_section="",
        divergences_block="",
        bar_chart_svg=generate_bar_chart_svg(data["chart_data"]),
        donut_svg=generate_3bucket_donut_svg(totals["buckets"]),
        rows_html=_render_rows_html(per_h, all_data),
        cards_html=_render_h_cards(per_h),
        batch_rows=_render_batch_rows(h_list),
        batch_rows_md=_render_batch_rows_md(h_list),
        batch_rows_mr=_render_batch_rows_mr(h_list),
        stability_section=stability_section,
        md_section=md_section,
        md_nav=md_nav,
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
