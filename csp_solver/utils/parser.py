"""
Lecture d'un fichier Benzai et construction du graphe dual.

Format d'entrée (fichier .ben) :
    p DIMACS <V> <E> <F>
    e <s1> <s2>           — arête entre deux carbones
    h <s1> ... <s6>       — hexagone (6 sommets dans l'ordre cyclique)

Les identifiants de sommets sont des paires x_y (coordonnées réseau hexagonal).
"""

import networkx as nx
from dataclasses import dataclass, field


@dataclass
class BenzenoidGraph:
    """Représentation du benzénoïde et de son graphe dual."""

    # Nombre d'hexagones
    h: int = 0

    # Graphe dual (NetworkX) : sommets = hexagones, arêtes = adjacences
    dual: nx.Graph = field(default_factory=nx.Graph)

    # Hexagones : liste de listes de sommets (ordre cyclique)
    hexagons: list = field(default_factory=list)

    # Pattern σ(v) pour chaque hexagone v : tuple de 0/1
    # σ_i = 1 si le côté i est partagé avec un voisin
    patterns: dict = field(default_factory=dict)

    # Positions d'arêtes : {(u,v): (pos_u, pos_v)}
    # pos_u = indice du côté dans l'hexagone u qui est partagé avec v
    edge_positions: dict = field(default_factory=dict)

    # Sommets (carbones) du graphe original
    vertices: set = field(default_factory=set)

    # Arêtes du graphe original
    edges: set = field(default_factory=set)

    def degree(self, v: int) -> int:
        """Degré du sommet v dans le graphe dual."""
        return self.dual.degree(v)

    def neighbors(self, v: int) -> list:
        """Voisins de v dans le graphe dual, triés."""
        return sorted(self.dual.neighbors(v))

    def is_fully_surrounded(self, v: int) -> bool:
        """True si l'hexagone v a 6 voisins (completement entoure)."""
        return self.degree(v) == 6

    def has_separated_free_edges(self, v: int) -> bool:
        """True si b(v) >= 2 (aretes libres en blocs separes)."""
        return count_zero_blocks(self.patterns[v]) >= 2

    def is_frozen(self, v: int, freeze_b2: bool = True) -> bool:
        """True si l'hexagone v est gele.

        Args:
            freeze_b2: si True, geler aussi les hexagones avec b(v)>=2.
                       Si False, ne geler que ceux avec deg=6.
        """
        if self.is_fully_surrounded(v):
            return True
        if freeze_b2 and self.has_separated_free_edges(v):
            return True
        return False

    def summary(self) -> str:
        """Résumé textuel du graphe."""
        lines = [
            f"Benzenoide : h={self.h}, |V|={len(self.vertices)}, |E|={len(self.edges)}",
            f"Graphe dual : {self.dual.number_of_nodes()} sommets, {self.dual.number_of_edges()} arêtes",
        ]
        for v in range(self.h):
            status = "libre"
            if self.is_fully_surrounded(v):
                status = "GELE (deg=6)"
            elif self.has_separated_free_edges(v):
                status = "GELE (b>=2)"
            lines.append(
                f"  v{v}: deg={self.degree(v)}, pattern={self.patterns[v]}, "
                f"b={count_zero_blocks(self.patterns[v])}, {status}"
            )
        return "\n".join(lines)


def count_zero_blocks(pattern: tuple) -> int:
    """Compte le nombre de blocs de 0 consécutifs dans un pattern cyclique.

    Exemples:
        (1,1,0,0,0,0) → 1 bloc
        (1,0,0,1,0,0) → 2 blocs
        (1,0,1,0,1,0) → 3 blocs
        (1,1,1,1,1,1) → 0 blocs
    """
    n = len(pattern)
    if all(p == 1 for p in pattern):
        return 0
    if all(p == 0 for p in pattern):
        return 1

    # Trouver un point de départ sur un 1 (pour éviter de couper un bloc de 0)
    start = None
    for i in range(n):
        if pattern[i] == 1:
            start = i
            break

    if start is None:
        return 1  # tout est 0

    blocks = 0
    in_zero = False
    for offset in range(n):
        idx = (start + offset) % n
        if pattern[idx] == 0:
            if not in_zero:
                blocks += 1
                in_zero = True
        else:
            in_zero = False

    return blocks


def parse(filepath: str) -> BenzenoidGraph:
    """Parse un fichier Benzai et construit le graphe dual.

    Args:
        filepath: chemin vers le fichier .ben

    Returns:
        BenzenoidGraph avec le graphe dual, les patterns et les positions.
    """
    graph = BenzenoidGraph()
    hexagons_raw = []

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            kind = parts[0]

            if kind == "p":
                # p DIMACS V E F
                graph.h = int(parts[4])

            elif kind == "e":
                # e s1 s2
                s1, s2 = parts[1], parts[2]
                graph.vertices.add(s1)
                graph.vertices.add(s2)
                graph.edges.add((s1, s2))

            elif kind == "h":
                # h s1 s2 s3 s4 s5 s6
                vertices = parts[1:]
                hexagons_raw.append(vertices)
                for v in vertices:
                    graph.vertices.add(v)

    graph.hexagons = hexagons_raw

    # Construire les arêtes de chaque hexagone (côtés)
    hex_edges = []
    for hex_verts in hexagons_raw:
        n = len(hex_verts)
        edges = set()
        for i in range(n):
            e = frozenset({hex_verts[i], hex_verts[(i + 1) % n]})
            edges.add(e)
        hex_edges.append(edges)

    # Construire le graphe dual : trouver les paires d'hexagones adjacents
    h = len(hexagons_raw)
    for u in range(h):
        graph.dual.add_node(u)

    for u in range(h):
        for v in range(u + 1, h):
            shared = hex_edges[u] & hex_edges[v]
            if shared:
                # Les deux hexagones partagent au moins une arête
                graph.dual.add_edge(u, v)

                # Trouver la position de l'arête partagée dans chaque hexagone
                shared_edge = next(iter(shared))
                s1, s2 = tuple(shared_edge)

                pos_u = _find_edge_position(hexagons_raw[u], s1, s2)
                pos_v = _find_edge_position(hexagons_raw[v], s1, s2)

                graph.edge_positions[(u, v)] = (pos_u, pos_v)
                graph.edge_positions[(v, u)] = (pos_v, pos_u)

    # Calculer les patterns σ(v) pour chaque hexagone
    for v in range(h):
        n_sides = len(hexagons_raw[v])
        pattern = [0] * n_sides

        for u in graph.dual.neighbors(v):
            if (v, u) in graph.edge_positions:
                pos = graph.edge_positions[(v, u)][0]
                pattern[pos] = 1

        graph.patterns[v] = tuple(pattern)

    return graph


def _find_edge_position(hex_verts: list, s1: str, s2: str) -> int:
    """Trouve l'indice du côté (s1,s2) dans un hexagone.

    Le côté i est l'arête entre hex_verts[i] et hex_verts[(i+1) % n].
    """
    n = len(hex_verts)
    for i in range(n):
        a = hex_verts[i]
        b = hex_verts[(i + 1) % n]
        if (a == s1 and b == s2) or (a == s2 and b == s1):
            return i
    raise ValueError(f"Arête ({s1}, {s2}) non trouvée dans l'hexagone {hex_verts}")


# --- Test rapide ---
if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        filepath = str(Path(__file__).parent / "data" / "example_3hex.ben")
    else:
        filepath = sys.argv[1]

    g = parse(filepath)
    print(g.summary())
