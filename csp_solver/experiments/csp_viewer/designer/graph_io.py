"""
Conversion entre representation canvas (liste d'hexagones en coords axiales)
et format .graph BenzAI (DIMACS-like).

CONVENTION DE COORDONNEES :
  Chaque hexagone est repere par des coordonnees AXIALES (q, r) entieres.
  La conversion vers les coordonnees d'atomes BenzAI est :

      cx_base = 2*q + r
      cy_base = 2*r

  Les 6 atomes de l'hexagone (q, r), dans l'ordre anti-horaire en partant
  du sommet bas, sont aux positions :

      C0 (bas)         : (cx_base,     cy_base)
      C1 (bas-droite)  : (cx_base + 1, cy_base + 1)
      C2 (haut-droite) : (cx_base + 1, cy_base + 2)
      C3 (haut)        : (cx_base,     cy_base + 3)
      C4 (haut-gauche) : (cx_base - 1, cy_base + 2)
      C5 (bas-gauche)  : (cx_base - 1, cy_base + 1)

  Cette formule est exactement celle utilisee par BenzAI dans ses
  fichiers .graph (verifie sur csp_solver/data/1.graph qui contient 4 hex
  catacondenses). Les hexagones adjacents partagent automatiquement 2
  atomes (par construction de la formule, sans deduplication explicite).

VOISINAGE AXIAL :
  Les 6 hex voisins de (q, r) sont :
      (q+1, r), (q-1, r)         : droite, gauche
      (q,   r+1), (q-1, r+1)     : haut-droite, haut-gauche
      (q,   r-1), (q+1, r-1)     : bas-gauche, bas-droite

FORMAT .graph BenzAI :
  Ligne 1 : p DIMACS <nc> <nl> <nh>
            (nc = nb atomes, nl = nb liaisons, nh = nb hexagones)
  Lignes e : e <id_atome_a> <id_atome_b>
  Lignes h : h <id_a1> <id_a2> ... <id_a6>

  Les ids d'atomes sont des chaines "<x>_<y>" ou (x, y) sont des entiers
  (eventuellement negatifs).
"""

from typing import List, Tuple


def hex_corners(q: int, r: int) -> List[str]:
    """Retourne les 6 ids d'atomes de l'hexagone (q, r), dans l'ordre anti-horaire
    en partant du sommet bas (C0).
    """
    cx = 2 * q + r
    cy = 2 * r
    return [
        f"{cx}_{cy}",          # C0 bas
        f"{cx + 1}_{cy + 1}",  # C1 bas-droite
        f"{cx + 1}_{cy + 2}",  # C2 haut-droite
        f"{cx}_{cy + 3}",      # C3 haut
        f"{cx - 1}_{cy + 2}",  # C4 haut-gauche
        f"{cx - 1}_{cy + 1}",  # C5 bas-gauche
    ]


def hex_from_c0(c0_id: str) -> Tuple[int, int]:
    """Inverse de hex_corners : retourne (q, r) a partir de l'id du sommet bas C0.

    Si c0_id = "<cx>_<cy>" alors r = cy / 2, q = (cx - r) / 2.
    """
    cx_str, cy_str = c0_id.split("_")
    cx, cy = int(cx_str), int(cy_str)
    if cy % 2 != 0:
        raise ValueError(f"Atome {c0_id} : cy={cy} doit etre pair pour etre un C0")
    r = cy // 2
    q = (cx - r) // 2
    if (cx - r) % 2 != 0:
        raise ValueError(f"Atome {c0_id} : (cx-r) doit etre pair pour etre un C0")
    return q, r


def hex_from_atoms(atoms: List[str]) -> Tuple[int, int]:
    """Deduit (q, r) d'un hexagone a partir de la liste de ses 6 atomes.

    Robuste a la rotation : ne suppose pas que les atomes sont donnes dans
    l'ordre C0..C5. On retrouve le centre par moyenne des coords, puis on
    inverse la formule pour obtenir (q, r).
    """
    if len(atoms) != 6:
        raise ValueError(f"Hexagone doit avoir 6 atomes, recu : {len(atoms)}")
    sum_cx, sum_cy = 0, 0
    for a in atoms:
        cx_str, cy_str = a.split("_")
        sum_cx += int(cx_str)
        sum_cy += int(cy_str)
    # Centre : sum_cx/6, sum_cy/6
    # Or par formule : centre de l'hex (q, r) = (2q + r, 2r + 1.5)
    # Donc 6 * 2q + 6 * r = sum_cx, 6 * (2r + 1.5) = sum_cy
    # r = (sum_cy / 6 - 1.5) / 2 = (sum_cy - 9) / 12
    # q = (sum_cx / 6 - r) / 2 = (sum_cx - 6r) / 12
    if (sum_cy - 9) % 12 != 0:
        raise ValueError(f"Hexagone {atoms} : sum_cy={sum_cy} n'est pas valide")
    r = (sum_cy - 9) // 12
    if (sum_cx - 6 * r) % 12 != 0:
        raise ValueError(f"Hexagone {atoms} : sum_cx={sum_cx} n'est pas valide")
    q = (sum_cx - 6 * r) // 12
    return q, r


def serialize_to_graph(hexes: List[Tuple[int, int]]) -> str:
    """Convertit une liste d'hexagones (q, r) en contenu .graph.

    Args:
        hexes : liste de tuples (q, r). L'ordre determine l'ordre des
                lignes 'h' dans le fichier. Les hex en doublon sont
                deduplique automatiquement.

    Returns:
        Contenu .graph (string, terminee par newline).
    """
    # Dedup des hex en preservant l'ordre
    seen = set()
    uniq_hexes = []
    for h in hexes:
        if h not in seen:
            seen.add(h)
            uniq_hexes.append(h)

    if not uniq_hexes:
        # Cas degenere : aucune hex
        return "p DIMACS 0 0 0\n"

    # Tous les atomes et les listes par hex
    atoms_set = set()
    hex_corner_lists = []
    for (q, r) in uniq_hexes:
        corners = hex_corners(q, r)
        atoms_set.update(corners)
        hex_corner_lists.append(corners)

    # Toutes les aretes (entre atomes consecutifs dans chaque hex)
    edges_set = set()
    for corners in hex_corner_lists:
        for i in range(6):
            a, b = corners[i], corners[(i + 1) % 6]
            edge = tuple(sorted([a, b]))
            edges_set.add(edge)

    n_atoms = len(atoms_set)
    n_edges = len(edges_set)
    n_hex = len(uniq_hexes)

    lines = [f"p DIMACS {n_atoms} {n_edges} {n_hex}"]
    # Tri canonique des aretes (par 1er atome puis 2e)
    for a, b in sorted(edges_set):
        lines.append(f"e {a} {b}")
    for corners in hex_corner_lists:
        lines.append("h " + " ".join(corners) + " ")

    return "\n".join(lines) + "\n"


def parse_graph_to_hexes(content: str) -> List[Tuple[int, int]]:
    """Inverse de serialize_to_graph : extrait la liste des (q, r) d'un .graph.

    Args:
        content : contenu du .graph (string).

    Returns:
        Liste de tuples (q, r), dans l'ordre des lignes 'h' du fichier.

    Note :
        Robuste a l'ordre des atomes dans chaque ligne 'h' (utilise
        hex_from_atoms qui calcule par centre, pas par C0 specifique).
    """
    hexes = []
    for line in content.splitlines():
        parts = line.strip().split()
        if not parts or parts[0] != "h":
            continue
        atoms = parts[1:7]
        try:
            q, r = hex_from_atoms(atoms)
            hexes.append((q, r))
        except ValueError:
            # Ligne h avec des coords non-conformes a notre convention :
            # on saute silencieusement. C'est rare et signale un fichier
            # genere par un outil autre que notre designer / BenzAI.
            continue
    return hexes


def validate_hex_set(hexes: List[Tuple[int, int]]) -> Tuple[bool, str]:
    """Verifie qu'un ensemble d'hexagones forme un benzenoide CONNEXE valide.

    Returns:
        (ok, message). Si ok=False, message explique le probleme.
    """
    if not hexes:
        return False, "Aucun hexagone dessine"

    # Dedup
    hex_set = set(hexes)
    if len(hex_set) != len(hexes):
        return False, "Hexagones en doublon"

    # Connexite dans le graphe d'adjacence hex (par arete partagee)
    # 2 hex partagent une arete ssi ils ont 2 atomes en commun.
    # En coords axiales, les 6 voisins de (q, r) sont :
    NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (-1, 1), (0, -1), (1, -1)]

    visited = set()
    start = next(iter(hex_set))
    stack = [start]
    while stack:
        h = stack.pop()
        if h in visited:
            continue
        visited.add(h)
        q, r = h
        for dq, dr in NEIGHBOR_OFFSETS:
            n = (q + dq, r + dr)
            if n in hex_set and n not in visited:
                stack.append(n)

    if visited != hex_set:
        n_disconnected = len(hex_set) - len(visited)
        return False, (f"Le benzenoide n'est pas connexe : "
                       f"{n_disconnected} hex isoles")

    return True, "OK"
