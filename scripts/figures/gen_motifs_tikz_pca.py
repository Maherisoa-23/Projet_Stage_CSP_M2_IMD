"""Genere des figures TikZ des motifs de bord (top 10 favorisants + top 10
defavorisants, w=4 et w=5) en utilisant les coordonnees 3D reelles d'un sol
exemple pour chaque motif.

Approche :
  1. Pour chaque motif, prendre le 1er sol_id exemple (preferentiellement plan
     pour les favorisants, non-plan pour les defavorisants).
  2. Lire xyz_optimized_gz + graph_content_gz + csp_solution_json.
  3. PCA sur les coords C pour obtenir la projection 2D la plus "plate".
  4. Identifier le bord externe (sequence de cycles).
  5. Localiser la fenetre du motif sur le bord (premiere occurrence).
  6. Dessiner :
     - cycles : polygone teinte (pent=rouge clair, hex=gris clair, hept=bleu clair)
     - cycles de la fenetre motif : bordure or epaisse
     - atomes : petits cercles noirs
     - liaisons : segments
     - label cycle : taille (5/6/7) au centroide
  7. Ecrire un fichier LaTeX standalone par categorie, ou un PDF unique.

Sortie : doc/motifs_bord_h8.tex + .pdf
"""

import csv
import gzip
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


# -------- IO / parsing --------

def parse_xyz_to_coords(xyz_text):
    """Retourne (atom_idx -> (x,y,z)) pour les seuls C."""
    lines = xyz_text.strip().split("\n")
    n = int(lines[0])
    coords = []
    for i in range(n):
        parts = lines[2 + i].split()
        el = parts[0]
        x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        coords.append((el, x, y, z))
    # On veut seulement les C, dans l'ordre de leur apparition
    return [(x, y, z) for el, x, y, z in coords if el == "C"]


def parse_graph(graph_content):
    """Retourne (hexs, atoms_set). hexs : liste d'ordres cycliques des
    indices d'atomes pour chaque cycle (entiers 0-indexed depuis le .graph)."""
    hexs = []
    atoms_set = set()
    for line in graph_content.strip().split("\n"):
        line = line.strip()
        if line.startswith("h "):
            atom_labels = line.split()[1:]
            hex_idx = [int(a) for a in atom_labels]
            hexs.append(hex_idx)
            atoms_set.update(hex_idx)
    return hexs, sorted(atoms_set)


# -------- PCA 2D --------

def pca_2d(coords):
    """Projette N points 3D sur leur plan principal (2D) via PCA simple.
    coords : list[(x,y,z)]. Retourne list[(u,v)] et le centre.
    """
    n = len(coords)
    cx = sum(c[0] for c in coords) / n
    cy = sum(c[1] for c in coords) / n
    cz = sum(c[2] for c in coords) / n
    # Matrice de covariance 3x3
    sxx = syy = szz = sxy = sxz = syz = 0.0
    for x, y, z in coords:
        dx, dy, dz = x - cx, y - cy, z - cz
        sxx += dx*dx; syy += dy*dy; szz += dz*dz
        sxy += dx*dy; sxz += dx*dz; syz += dy*dz
    sxx /= n; syy /= n; szz /= n
    sxy /= n; sxz /= n; syz /= n
    # Eigen via methode des puissances pour les 2 plus grandes vp
    # Plus simple : on cherche les 2 vp les plus grandes de la matrice 3x3
    # On le fait avec numpy si dispo, sinon iteration
    try:
        import numpy as np
        cov = np.array([[sxx, sxy, sxz], [sxy, syy, syz], [sxz, syz, szz]])
        w, v = np.linalg.eigh(cov)
        # vp triees croissantes -> on prend les 2 dernieres
        e1 = v[:, 2]
        e2 = v[:, 1]
    except ImportError:
        # Fallback naif : prendre les axes x,y du repere
        e1 = (1.0, 0.0, 0.0)
        e2 = (0.0, 1.0, 0.0)

    out = []
    for x, y, z in coords:
        dx, dy, dz = x - cx, y - cy, z - cz
        u = dx*e1[0] + dy*e1[1] + dz*e1[2]
        v = dx*e2[0] + dy*e2[1] + dz*e2[2]
        out.append((u, v))
    return out, (cx, cy, cz)


# -------- Bord externe + motifs --------

def boundary_cycle_seq(hexs):
    """Retourne sequence cyclique de cycles le long du bord externe (apres
    dedup consecutif). Methode identique a extract_boundary_motifs_h8.py.
    """
    edges_by_cycle = []
    for h in hexs:
        edges = [tuple(sorted([h[i], h[(i+1) % len(h)]])) for i in range(len(h))]
        edges_by_cycle.append(edges)
    edge_cycles = defaultdict(list)
    for ci, edges in enumerate(edges_by_cycle):
        for e in edges:
            edge_cycles[e].append(ci)
    boundary_edges = {e for e, cyc in edge_cycles.items() if len(cyc) == 1}
    if not boundary_edges:
        return None
    bd_neighbors = defaultdict(list)
    bd_edge_cycle = {}
    for e in boundary_edges:
        a, b = e
        bd_neighbors[a].append(b)
        bd_neighbors[b].append(a)
        bd_edge_cycle[e] = edge_cycles[e][0]
    start = next(iter(bd_neighbors))
    visited = {start}
    cycle_seq = []
    cur = start
    prev = None
    while True:
        nbrs = bd_neighbors[cur]
        nxt = None
        for n in nbrs:
            if n != prev:
                nxt = n
                break
        if nxt is None:
            break
        edge = tuple(sorted([cur, nxt]))
        cycle_seq.append(bd_edge_cycle[edge])
        if nxt == start:
            break
        if nxt in visited:
            break
        visited.add(nxt)
        prev = cur
        cur = nxt
    return cycle_seq


def dedup_consecutive(seq):
    if not seq: return seq
    out = [seq[0]]
    for x in seq[1:]:
        if x != out[-1]: out.append(x)
    if len(out) > 1 and out[-1] == out[0]: out.pop()
    return out


def canonical_window(w):
    rev = tuple(reversed(w))
    return min(w, rev)


def find_motif_window_in_seq(seq, sizes, motif_target):
    """Cherche dans la sequence cyclique 'seq' (cycles indices) une fenetre
    de longueur len(motif_target) dont les tailles match motif_target
    (en forme canonique). Retourne la liste des indices de cycle dans la
    fenetre, ou None si pas trouve.
    """
    L = len(seq)
    k = len(motif_target)
    for i in range(L):
        win = tuple(seq[(i + j) % L] for j in range(k))
        win_sizes = tuple(sizes[c] for c in win)
        if canonical_window(win_sizes) == motif_target:
            return list(win)
    return None


# -------- Geometrie pour TikZ --------

def cycle_polygon_2d(cycle_atoms, coords2d, all_atoms_sorted):
    """Retourne la liste des points 2D (u,v) du polygone du cycle.
    cycle_atoms : indices ATOMS dans le label .graph (numerotes >=1).
    all_atoms_sorted : liste triee des atoms (mapping label -> idx coord).
    """
    label_to_idx = {a: i for i, a in enumerate(all_atoms_sorted)}
    pts = []
    for a in cycle_atoms:
        if a in label_to_idx:
            pts.append(coords2d[label_to_idx[a]])
    return pts


def cycle_centroid(pts):
    n = len(pts)
    return (sum(p[0] for p in pts)/n, sum(p[1] for p in pts)/n)


# -------- TikZ generation --------

CYCLE_COLOR = {5: "pent5color", 6: "hex6color", 7: "hept7color"}
CYCLE_COLOR_HIGHLIGHT = {5: "pent5hl", 6: "hex6hl", 7: "hept7hl"}


def gen_tikz_figure(motif_str, motif_target, sol_id, scale, conn):
    """Genere le code tikzpicture pour un sol exemple d'un motif.
    Retourne le contenu LaTeX (sans le \\begin{figure}) ou None si echec.
    """
    row = conn.execute("""
        SELECT graph_content_gz, csp_solution_json, xyz_optimized_gz, angle_deg, verdict
        FROM final_solutions WHERE sol_id=?
    """, (sol_id,)).fetchone()
    if not row:
        return None
    g = gzip.decompress(row[0]).decode()
    sol = json.loads(row[1])
    xyz = gzip.decompress(row[2]).decode()
    angle = row[3]
    verdict = row[4]

    hexs, atoms_sorted = parse_graph(g)
    sizes = [int(sol.get(str(i), 6)) for i in range(len(hexs))]

    coords3d = parse_xyz_to_coords(xyz)
    if len(coords3d) != len(atoms_sorted):
        return None
    coords2d, _ = pca_2d(coords3d)

    # Bord externe
    seq = boundary_cycle_seq(hexs)
    if seq is None:
        return None
    ddup = dedup_consecutive(seq)
    if len(ddup) < len(motif_target):
        return None

    # Localise fenetre motif
    motif_cycles = find_motif_window_in_seq(ddup, sizes, motif_target)
    motif_cycles_set = set(motif_cycles) if motif_cycles else set()

    # Compute aretes (paires d'atomes)
    edges = set()
    for h in hexs:
        for i in range(len(h)):
            a, b = h[i], h[(i+1) % len(h)]
            edges.add(tuple(sorted([a, b])))

    label_to_idx = {a: i for i, a in enumerate(atoms_sorted)}

    # Bounding box pour centrer
    xs = [p[0] for p in coords2d]
    ys = [p[1] for p in coords2d]
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    coords2d = [(p[0]-cx, p[1]-cy) for p in coords2d]

    # Generation TikZ
    lines = []
    lines.append(f"\\begin{{tikzpicture}}[scale={scale}]")

    # 1. cycles colores (fond) : on dessine d'abord les non-mis-en-avant
    for ci, atoms in enumerate(hexs):
        size = sizes[ci]
        is_hl = ci in motif_cycles_set
        color = CYCLE_COLOR_HIGHLIGHT[size] if is_hl else CYCLE_COLOR[size]
        pts = cycle_polygon_2d(atoms, coords2d, atoms_sorted)
        if len(pts) < 3:
            continue
        coords_str = " -- ".join(f"({p[0]:.3f},{p[1]:.3f})" for p in pts)
        if is_hl:
            lines.append(f"  \\filldraw[fill={color}, draw=motifedge, line width=1.4pt] {coords_str} -- cycle;")
        else:
            lines.append(f"  \\filldraw[fill={color}, draw=cycleedge, line width=0.3pt] {coords_str} -- cycle;")

    # 2. liaisons (par-dessus pour bien voir les bonds)
    for (a, b) in sorted(edges):
        if a in label_to_idx and b in label_to_idx:
            pa = coords2d[label_to_idx[a]]
            pb = coords2d[label_to_idx[b]]
            lines.append(f"  \\draw[bondline] ({pa[0]:.3f},{pa[1]:.3f}) -- ({pb[0]:.3f},{pb[1]:.3f});")

    # 3. atomes
    for i, p in enumerate(coords2d):
        lines.append(f"  \\fill[atomfill] ({p[0]:.3f},{p[1]:.3f}) circle (0.05);")

    # 4. labels de taille au centre de chaque cycle de la fenetre motif
    if motif_cycles:
        for ci in motif_cycles:
            pts = cycle_polygon_2d(hexs[ci], coords2d, atoms_sorted)
            cnt = cycle_centroid(pts)
            lines.append(f"  \\node[cyclelabel] at ({cnt[0]:.3f},{cnt[1]:.3f}) {{\\textbf{{{sizes[ci]}}}}};")

    lines.append("\\end{tikzpicture}")
    return "\n".join(lines), angle, verdict


# -------- Selection des motifs --------

def load_motif_csv(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        r["n_total"] = int(r["n_total"])
        r["n_plan"] = int(r["n_plan"])
        r["n_nonplan"] = int(r["n_nonplan"])
        r["pct_plan"] = float(r["pct_plan"])
        r["delta_pp"] = float(r["delta_pp"])
        r["motif_tuple"] = tuple(int(x) for x in r["motif"].split("-"))
        r["score"] = abs(r["delta_pp"]) * math.sqrt(r["n_total"])
    return rows


def select_top(rows, n=10, sense=+1, min_total=1000):
    filt = [r for r in rows if r["n_total"] >= min_total and (sense * r["delta_pp"]) > 0]
    filt.sort(key=lambda r: -r["score"])
    return filt[:n]


# -------- Main --------

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db)

    rows_w4 = load_motif_csv("tmp/motifs_h8_w4.csv")
    rows_w5 = load_motif_csv("tmp/motifs_h8_w5.csv")

    top_fav_w4 = select_top(rows_w4, n=10, sense=+1)
    top_def_w4 = select_top(rows_w4, n=10, sense=-1)
    top_fav_w5 = select_top(rows_w5, n=10, sense=+1)
    top_def_w5 = select_top(rows_w5, n=10, sense=-1)

    print("Top w4 favorisants :", [r["motif"] for r in top_fav_w4])
    print("Top w4 defavorisants :", [r["motif"] for r in top_def_w4])

    # Generation LaTeX
    preamble = r"""\documentclass[a4paper,11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1.5cm]{geometry}
\usepackage{tikz}
\usepackage{xcolor}
\usepackage{booktabs}
\usepackage{caption}
\usepackage{subcaption}
\usepackage{float}
\usetikzlibrary{shapes,calc}

% Couleurs des cycles (saturation faible pour fond)
\definecolor{pent5color}{RGB}{254,232,232}
\definecolor{hex6color}{RGB}{240,240,240}
\definecolor{hept7color}{RGB}{226,235,254}
% Couleurs des cycles surlignes (saturation forte)
\definecolor{pent5hl}{RGB}{252,165,165}
\definecolor{hex6hl}{RGB}{200,200,200}
\definecolor{hept7hl}{RGB}{147,179,255}
\definecolor{motifedge}{RGB}{217,119,6}
\definecolor{cycleedge}{RGB}{130,130,130}
\definecolor{bondline}{RGB}{40,40,40}
\definecolor{atomfill}{RGB}{20,20,20}
\definecolor{cyclelabelcol}{RGB}{40,40,40}

\tikzset{
  cyclelabel/.style={text=cyclelabelcol, font=\small\sffamily},
}

\title{Motifs de bord -- non-benzenoides h8 \\
\large{Caracterisation topologique de la planarite par sequences de cycles le long du bord externe}}
\author{}
\date{}

\begin{document}
\maketitle

\section{Methodologie}

Pour chaque solution h8 \texttt{C1 done} (107 764 sols, 60.08\% PLAN), nous extrayons la sequence
ordonnee des cycles le long du \emph{bord externe} du graphe dual.
Chaque arete de la frontiere appartient a un unique cycle ; le parcours
cyclique de ces aretes definit une suite de cycles.
Sur cette suite, nous extrayons toutes les fenetres glissantes de longueur
$w \in \{4, 5\}$ (canonisees par symetrie miroir).

Pour chaque motif canonique $m$, on calcule
\[
\Delta_{\mathrm{pp}}(m) = \mathrm{P}(\mathrm{PLAN} \mid m \in \text{sol}) - \mathrm{baseline}
\]
ou la baseline vaut $60.08\%$ (frequence globale de PLAN pour h8 C1).
Le score d'interet est $|\Delta_{\mathrm{pp}}| \cdot \sqrt{N}$, qui favorise
les motifs simultanement \emph{discriminants} et \emph{frequents}.

\paragraph{Convention graphique.} Pentagone = rouge clair, hexagone = gris clair,
heptagone = bleu clair. Les cycles de la \textbf{fenetre du motif} sont en couleur
plus saturee avec une bordure orange, et leur taille est annotee au centre.

"""

    # Sections
    sections = []

    def section(title, intro, top_list, scale=0.5):
        body = [f"\\section{{{title}}}", intro]
        body.append("\\begin{figure}[H]")
        body.append("\\centering")
        # 2 colonnes : 5 figures par ligne
        for i, r in enumerate(top_list):
            res = gen_tikz_figure(
                r["motif"], r["motif_tuple"],
                int(r["ex_plan"].split(",")[0]) if r["ex_plan"] else int(r["ex_nonplan"].split(",")[0]),
                scale, conn,
            )
            if res is None:
                body.append(f"% Echec motif {r['motif']}")
                continue
            tikz, angle, verdict = res
            cap = (
                f"\\texttt{{{r['motif']}}} -- "
                f"$N{{=}}{r['n_total']}$, "
                f"\\%PLAN${{=}}{r['pct_plan']:.1f}$, "
                f"$\\Delta{{=}}{r['delta_pp']:+.1f}$~pp \\\\"
                f"\\footnotesize{{sol\\_id={int(r['ex_plan'].split(',')[0]) if r['ex_plan'] else int(r['ex_nonplan'].split(',')[0])}, "
                f"angle={angle:.2f}$^\\circ$, {verdict}}}"
            )
            body.append("\\begin{minipage}{0.19\\textwidth}\\centering")
            body.append(tikz)
            body.append(f"\\\\\\footnotesize {cap}")
            body.append("\\end{minipage}\\hfill")
            if (i + 1) % 5 == 0:
                body.append("\\\\[0.6em]")
        body.append("\\end{figure}")
        return "\n".join(body)

    sections.append(section(
        "Top 10 motifs FAVORISANT la planarite (w=4)",
        r"Motifs a 4 cycles consecutifs sur le bord dont la presence est associee a un \emph{plus grand} taux de planarite que la baseline.",
        top_fav_w4
    ))
    sections.append(section(
        "Top 10 motifs DEFAVORISANT la planarite (w=4)",
        r"Motifs a 4 cycles consecutifs sur le bord dont la presence est associee a un \emph{plus faible} taux de planarite.",
        top_def_w4
    ))
    sections.append(section(
        "Top 10 motifs FAVORISANT la planarite (w=5)",
        r"Idem avec une fenetre etendue a 5 cycles consecutifs.",
        top_fav_w5
    ))
    sections.append(section(
        "Top 10 motifs DEFAVORISANT la planarite (w=5)",
        r"Sequences de 5 cycles les plus penalisantes pour la planarite.",
        top_def_w5
    ))

    sections.append(r"""
\section{Lecture statistique}

\begin{itemize}
\item Un \textbf{motif favorisant} contient typiquement un defaut isole (pent ou hept seul) entoure d'hexagones, qui realise la compensation locale Gauss-Bonnet (motif Stone-Wales).
\item Un \textbf{motif defavorisant} concentre plusieurs cycles de meme nature (\texttt{7-7-7-7}, \texttt{5-5-5-5}) ou un melange mal positionne (\texttt{5-7-7-7}, \texttt{5-5-7-7}).
\item Le contraste est tres net en $w=5$ : \texttt{7-7-7-7-7} chute a 14\% PLAN, \texttt{5-5-5-5-5} a 20\%, alors que des sequences a un seul defaut isole atteignent 75-80\% PLAN.
\item Ces signatures rappellent les notions de \emph{cove}, \emph{deep bay} et \emph{ultra-deep bay} introduites en topologie des benzenoides, etendues ici aux cycles 5/7.
\end{itemize}

\end{document}
""")

    tex = preamble + "\n\n".join(sections)
    out_path = Path("doc/motifs_bord_h8.tex")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tex, encoding="utf-8")
    print(f"\nEcrit : {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
