"""
Systeme de coordonnees hexagonales pour generer des fichiers .graph Benzai.

Coordonnees axiales (cx, cy) pour les cellules hexagonales :
  - (0, 0) = hexagone a l'origine
  - 6 voisins : (+1,0), (0,+1), (-1,+1), (-1,0), (0,-1), (+1,-1)

Conversion vers les labels de sommets x_y du format .graph :
  - Sommet bas de l'hex (cx, cy) : bx = 2*cx + cy, by = 2*cy
  - 6 sommets de l'hex : (bx,by), (bx+1,by+1), (bx+1,by+2),
                          (bx,by+3), (bx-1,by+2), (bx-1,by+1)
"""

# Les 6 directions voisines en coordonnees axiales (cx, cy)
#   0: droite       1: haut-droite   2: haut-gauche
#   3: gauche       4: bas-gauche    5: bas-droite
NEIGHBOR_OFFSETS = [
    (1, 0),    # droite
    (0, 1),    # haut-droite
    (-1, 1),   # haut-gauche
    (-1, 0),   # gauche
    (0, -1),   # bas-gauche
    (1, -1),   # bas-droite
]


def cell_to_bottom_vertex(cx, cy):
    """Convertit coordonnees axiales (cx, cy) en sommet bas (bx, by)."""
    return (2 * cx + cy, 2 * cy)


def bottom_vertex_to_cell(bx, by):
    """Convertit sommet bas (bx, by) en coordonnees axiales (cx, cy)."""
    cy = by // 2
    cx = (bx - cy) // 2
    return (cx, cy)


def hexagon_vertices(cx, cy):
    """
    Retourne les 6 sommets de l'hexagone a la position (cx, cy)
    dans l'ordre du format .graph (sens horaire depuis le bas).

    Returns: liste de 6 tuples (vx, vy) — labels pour le format x_y
    """
    bx, by = cell_to_bottom_vertex(cx, cy)
    return [
        (bx, by),           # bas
        (bx + 1, by + 1),   # bas-droite
        (bx + 1, by + 2),   # haut-droite
        (bx, by + 3),       # haut
        (bx - 1, by + 2),   # haut-gauche
        (bx - 1, by + 1),   # bas-gauche
    ]


def neighbors(cx, cy):
    """Retourne les 6 positions voisines de (cx, cy)."""
    return [(cx + dx, cy + dy) for dx, dy in NEIGHBOR_OFFSETS]


def shared_edge(cell_a, cell_b):
    """
    Retourne l'arete partagee entre deux hexagones adjacents,
    ou None s'ils ne sont pas adjacents.

    Returns: tuple ((vx1, vy1), (vx2, vy2)) ou None
    """
    verts_a = set(map(tuple, hexagon_vertices(*cell_a)))
    verts_b = set(map(tuple, hexagon_vertices(*cell_b)))
    common = verts_a & verts_b
    if len(common) == 2:
        return tuple(sorted(common))
    return None


def vertex_label(vx, vy):
    """Convertit (vx, vy) en label string 'x_y' pour le format .graph."""
    return f"{vx}_{vy}"


def parse_vertex_label(label):
    """Convertit un label 'x_y' en tuple (vx, vy)."""
    parts = label.split("_")
    return (int(parts[0]), int(parts[1]))


def cells_are_adjacent(cell_a, cell_b):
    """Verifie si deux cellules hexagonales sont adjacentes."""
    dx = cell_b[0] - cell_a[0]
    dy = cell_b[1] - cell_a[1]
    return (dx, dy) in NEIGHBOR_OFFSETS
