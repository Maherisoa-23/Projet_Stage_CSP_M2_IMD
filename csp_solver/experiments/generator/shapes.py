"""
Templates de formes de benzenoides en coordonnees axiales (cx, cy).

Chaque fonction retourne un set de tuples (cx, cy) representant les
positions des hexagones dans la grille hexagonale.

Familles inspirees de la these Varet (2022) :
  - Polyacenes (lineaires)
  - Zigzag
  - Rectangulaires
  - Losanges
  - Coronenoides (couronnes concentriques)
  - Formes L, T
  - Compacts (remplissage glouton)
"""

from hex_grid import NEIGHBOR_OFFSETS


def linear_chain(h):
    """
    Chaine lineaire de h hexagones (polyacene).
    Direction : haut-droite (offset 0,+1).
    Ex: h=3 → anthracene.
    """
    return {(0, i) for i in range(h)}


def zigzag_chain(h):
    """
    Chaine en zigzag de h hexagones.
    Alterne entre direction droite (+1,0) et haut-droite (0,+1).
    """
    cells = set()
    cx, cy = 0, 0
    for i in range(h):
        cells.add((cx, cy))
        if i % 2 == 0:
            cx += 1  # droite
        else:
            cy += 1  # haut-droite
    return cells


def rectangular(rows, cols):
    """
    Benzenoide rectangulaire de dimension rows x cols.
    (these Varet sec. 3.4.3, fig. 3.12)

    rows : nombre de lignes (hauteur)
    cols : nombre de colonnes (largeur)

    La premiere ligne est a y=0, la deuxieme a y=1, etc.
    Les colonnes sont decalees pour former le pattern hexagonal.
    """
    cells = set()
    for r in range(rows):
        for c in range(cols):
            # Decalage pour les lignes paires/impaires
            cx = c + (r // 2)
            cy = r
            # Correction : dans le systeme hex, la ligne r a un decalage
            # qui depend de la parite de r
            if r % 2 == 0:
                cells.add((c, r))
            else:
                cells.add((c, r))
    # Approche simplifiee : grille reguliere en coordonnees axiales
    # On utilise le fait que les voisins (0,+1) et (-1,+1) donnent
    # les deux directions "vers le haut"
    cells = set()
    for r in range(rows):
        for c in range(cols):
            cells.add((c, r))
    return cells


def diamond(k):
    """
    Losange de cote k (these Varet sec. 3.4.4, fig. 3.15).
    Equivalent a rectangular(k, k).
    """
    return rectangular(k, k)


def coronenoid(k):
    """
    Coronenoide de taille k (these Varet sec. 3.4.2, fig. 3.3).
    k=1 : benzene (1 hex)
    k=2 : coronene (7 hex)
    k=3 : 19 hex
    k=4 : 37 hex
    """
    cells = set()
    for q in range(-k + 1, k):
        for r in range(-k + 1, k):
            # Condition du coronenoide : |q| + |r| + |q+r| <= 2*(k-1)
            # Equivalent a : max(|q|, |r|, |q+r|) <= k-1
            if max(abs(q), abs(r), abs(q + r)) <= k - 1:
                cells.add((q, r))
    return cells


def L_shape(a, b):
    """
    Forme en L : a hexagones verticaux + b hexagones horizontaux.
    Le coin est a (0, 0).
    """
    cells = set()
    # Branche verticale (haut-droite)
    for i in range(a):
        cells.add((0, i))
    # Branche horizontale (droite) depuis le bas
    for i in range(1, b):
        cells.add((i, 0))
    return cells


def T_shape(stem, top):
    """
    Forme en T : stem hexagones de tige + top hexagones de barre.
    La barre est centree en haut de la tige.
    """
    cells = set()
    # Tige (direction haut-droite)
    for i in range(stem):
        cells.add((0, i))
    # Barre au sommet (direction droite, centree)
    top_y = stem - 1
    half = top // 2
    for i in range(-half, top - half):
        cells.add((i, top_y))
    return cells


def compact_cluster(h):
    """
    Cluster compact de h hexagones par remplissage BFS
    depuis l'origine (maximise les hexagones internes).
    """
    if h <= 0:
        return set()

    cells = {(0, 0)}
    # BFS : ajouter les voisins couche par couche
    frontier = [(0, 0)]
    while len(cells) < h:
        next_frontier = []
        for cx, cy in frontier:
            for dx, dy in NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) not in cells and len(cells) < h:
                    cells.add((nx, ny))
                    next_frontier.append((nx, ny))
                if len(cells) >= h:
                    break
            if len(cells) >= h:
                break
        if not next_frontier:
            break
        frontier = next_frontier
    return cells


def from_positions(positions):
    """
    Cree un benzenoide a partir de positions arbitraires.

    Args:
        positions: iterable de tuples (cx, cy)

    Returns:
        set de tuples (cx, cy)
    """
    return set(positions)


# --- Utilitaires ---

def describe_shape(cells):
    """Retourne des informations sur un ensemble de cellules."""
    if not cells:
        return {"h": 0}

    cells = set(cells)
    h = len(cells)

    # Compter les adjacences
    n_edges = 0
    for cx, cy in cells:
        for dx, dy in NEIGHBOR_OFFSETS:
            if (cx + dx, cy + dy) in cells:
                n_edges += 1
    n_edges //= 2  # chaque arete comptee 2 fois

    # Hexagones internes (6 voisins dans l'ensemble)
    n_internal = 0
    for cx, cy in cells:
        n_neighbors = sum(
            1 for dx, dy in NEIGHBOR_OFFSETS
            if (cx + dx, cy + dy) in cells
        )
        if n_neighbors == 6:
            n_internal += 1

    return {
        "h": h,
        "n_dual_edges": n_edges,
        "n_internal": n_internal,
        "n_boundary": h - n_internal,
    }
