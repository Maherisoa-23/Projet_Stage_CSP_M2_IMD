"""
Construction du graphe dual d'une solution (vue topologique 2D).

Le rendu 3D (mode skip surtout) peut deformer la geometrie au point que les
tailles de cycles affichees ne correspondent plus a la solution CSP. Le graphe
dual, lui, est la VERITE TOPOLOGIQUE : un noeud par hexagone du graphe d'entree,
positionne par le centroide de ses 6 sommets, colore par la taille de cycle que
la solution CSP lui a assignee (5/6/7), avec une arete entre deux hexagones
adjacents (partageant une liaison = 2 sommets).

Sources de donnees :
  - graph_content (.graph DIMACS) : lignes "h q1_r1 q2_r2 ..." donnant les 6
    sommets de chaque hexagone en coordonnees axiales.
  - sizes : la taille assignee a chaque hexagone, lue depuis le nom de
    solution (sol_<idx>_<s1>_<s2>_...). L'ordre des sizes suit l'ordre des
    lignes "h" du .graph.

Sortie : un dict serialisable JSON consomme par le frontend pour un rendu SVG
2D a cote du viewer 3D.
"""

import re
from typing import List, Optional, Tuple


# "h q1_r1 q2_r2 ..." -> les 6 sommets (q,r) d'un hexagone.
_HEX_LINE_RE = re.compile(r"^h\s+(.+)$")
# Coordonnee axiale "q_r" (q et r peuvent etre negatifs).
_COORD_RE = re.compile(r"^(-?\d+)_(-?\d+)$")


def parse_graph_hexes(graph_text: str) -> List[List[Tuple[int, int]]]:
    """Parse les lignes 'h' du .graph -> liste d'hexagones.

    Chaque hexagone = liste de (q, r) (ses 6 sommets en coords axiales).
    L'ordre des hexagones suit l'ordre des lignes 'h' (= l'ordre des sizes
    dans le nom de solution).
    """
    hexes: List[List[Tuple[int, int]]] = []
    for line in graph_text.splitlines():
        m = _HEX_LINE_RE.match(line.strip())
        if not m:
            continue
        coords: List[Tuple[int, int]] = []
        for tok in m.group(1).split():
            cm = _COORD_RE.match(tok)
            if cm:
                coords.append((int(cm.group(1)), int(cm.group(2))))
        if coords:
            hexes.append(coords)
    return hexes


def _axial_to_xy(q: int, r: int) -> Tuple[float, float]:
    """Convertit une coord axiale (q, r) de la grille hex en cartesien 2D.

    Convention "pointy-top" classique. On garde la meme orientation que le
    designer pour que le dual soit lisible cote-a-cote avec la grille d'entree.
    x augmente vers la droite, y vers le bas (repere ecran).
    """
    x = q + r / 2.0
    y = r * 0.8660254  # sqrt(3)/2
    return x, y


def build_dual(graph_text: str, sizes: List[int]) -> Optional[dict]:
    """Construit le graphe dual d'une solution.

    Args:
        graph_text : contenu .graph (DIMACS, avec lignes 'h').
        sizes      : taille de chaque hexagone, dans l'ordre des lignes 'h'.
                     Typiquement lu depuis le nom de solution.

    Returns:
        dict {nodes: [...], edges: [...]} ou None si parsing impossible.
          nodes[i] = {id, x, y, size}   (x,y = centroide cartesien)
          edges    = [{a, b}]           (indices d'hexagones adjacents)
        Retourne None si le .graph n'a pas de lignes 'h' ou si le nombre
        d'hexagones ne correspond pas au nombre de sizes (incoherence ->
        on prefere ne rien afficher plutot qu'un dual faux).
    """
    hexes = parse_graph_hexes(graph_text)
    if not hexes:
        return None
    if sizes and len(sizes) != len(hexes):
        # Incoherence entre le .graph et le nom de solution : on s'abstient.
        return None

    # Noeuds : centroide cartesien + taille
    nodes = []
    centroids_xy = []
    for i, hx in enumerate(hexes):
        xs, ys = zip(*(_axial_to_xy(q, r) for q, r in hx))
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        centroids_xy.append((cx, cy))
        nodes.append({
            "id": i,
            "x": round(cx, 4),
            "y": round(cy, 4),
            "size": int(sizes[i]) if sizes else None,
        })

    # Aretes : 2 hexagones adjacents s'ils partagent au moins 2 sommets
    # (= une arete commune du graphe carbone = liaison partagee).
    edges = []
    hex_sets = [set(hx) for hx in hexes]
    for i in range(len(hexes)):
        for j in range(i + 1, len(hexes)):
            if len(hex_sets[i] & hex_sets[j]) >= 2:
                edges.append({"a": i, "b": j})

    return {"nodes": nodes, "edges": edges}


# "sol_<idx>_<s1>_<s2>_..." -> liste des tailles [s1, s2, ...]
_SOL_SIZES_RE = re.compile(r"sol_?\d+_((?:\d+_)*\d+)")


def parse_sizes_from_name(name_or_path: str) -> Optional[List[int]]:
    """Extrait les tailles de cycles depuis un nom/chemin de solution.

    Ex. "sol_16_5_5_7_7_7_5" -> [5, 5, 7, 7, 7, 5].
    Retourne None si le motif n'est pas trouve.
    """
    m = _SOL_SIZES_RE.search(name_or_path.replace("\\", "/"))
    if not m:
        return None
    try:
        return [int(s) for s in m.group(1).split("_")]
    except ValueError:
        return None
