"""
Genere un fichier .graph au format Benzai a partir d'un ensemble
de positions de cellules hexagonales en coordonnees axiales (cx, cy).

Format .graph (inspire DIMACS) :
  p DIMACS <nb_vertices> <nb_edges> <nb_hexagons>
  e <label1> <label2>       (aretes C-C)
  h <v1> <v2> ... <v6>      (hexagones, 6 sommets sens horaire depuis le bas)
"""

from pathlib import Path
from hex_grid import (
    hexagon_vertices, vertex_label, cells_are_adjacent, shared_edge
)


def generate_graph_content(cell_positions):
    """
    Genere le contenu d'un fichier .graph pour un ensemble de cellules hex.

    Args:
        cell_positions: liste/set de tuples (cx, cy) — positions axiales

    Returns:
        string — contenu du fichier .graph
    """
    cells = list(cell_positions)
    if not cells:
        raise ValueError("Aucune cellule fournie")

    # Collecter tous les sommets et aretes
    all_vertices = set()
    all_edges = set()
    hex_lines = []

    for cx, cy in cells:
        verts = hexagon_vertices(cx, cy)
        vert_tuples = [tuple(v) for v in verts]

        for v in vert_tuples:
            all_vertices.add(v)

        # Aretes de l'hexagone (6 cotes)
        for i in range(6):
            v1 = vert_tuples[i]
            v2 = vert_tuples[(i + 1) % 6]
            edge = tuple(sorted([v1, v2]))
            all_edges.add(edge)

        # Ligne h
        labels = " ".join(vertex_label(*v) for v in vert_tuples)
        hex_lines.append(f"h {labels} ")

    # Header
    n_vertices = len(all_vertices)
    n_edges = len(all_edges)
    n_hexagons = len(cells)

    lines = [f"p DIMACS {n_vertices} {n_edges} {n_hexagons}"]

    # Aretes
    for v1, v2 in sorted(all_edges):
        lines.append(f"e {vertex_label(*v1)} {vertex_label(*v2)}")

    # Hexagones
    lines.extend(hex_lines)

    return "\n".join(lines) + "\n"


def write_graph_file(cell_positions, output_path):
    """
    Ecrit un fichier .graph pour un ensemble de cellules.

    Args:
        cell_positions: liste/set de tuples (cx, cy)
        output_path: chemin du fichier de sortie
    """
    content = generate_graph_content(cell_positions)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(content)
    return output_path


def validate_graph_file(graph_path, parser_path=None):
    """
    Valide un fichier .graph en le relisant avec le parser existant.

    Args:
        graph_path: chemin du fichier .graph
        parser_path: chemin vers le dossier contenant utils/parser.py

    Returns:
        (success, message) — tuple (bool, str)
    """
    import sys
    if parser_path:
        sys.path.insert(0, str(parser_path))

    try:
        from utils.parser import parse
        graph = parse(str(graph_path))
        return True, (
            f"OK: h={graph.h}, "
            f"|V|={len(graph.vertices)}, "
            f"|E|={len(graph.edges)}"
        )
    except Exception as e:
        return False, f"ERREUR: {e}"


if __name__ == "__main__":
    # Test : generer le benzene (1 hexagone)
    print("=== Test: benzene ===")
    content = generate_graph_content([(0, 0)])
    print(content)

    # Test : anthracene (3 hexagones en ligne)
    print("=== Test: anthracene (3 hex lineaire) ===")
    content = generate_graph_content([(0, 0), (0, 1), (0, 2)])
    print(content)

    # Test : coronene-like (hex central + 6 voisins... non, c'est 7 hex)
    print("=== Test: hex central + 2 voisins ===")
    content = generate_graph_content([(0, 0), (1, 0), (0, 1)])
    print(content)
