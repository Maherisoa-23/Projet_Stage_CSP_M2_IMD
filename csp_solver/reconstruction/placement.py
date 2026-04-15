"""
Phase B : Placement geometrique des cycles via BFS sur le graphe dual.

Chaque cycle est place comme un polygone regulier, ancre sur l'arete
partagee avec son parent dans l'arbre BFS. Les sommets deja places
(partages avec d'autres cycles) conservent leurs coordonnees existantes.

xTB corrigera les imperfections geometriques residuelles.
"""

import math
from collections import deque

from utils.parser import BenzenoidGraph


# Constantes
BOND_CC = 1.42  # Distance C-C en angstroms


def radius_from_side(n: int, side: float = BOND_CC) -> float:
    """Rayon du cercle circonscrit d'un polygone regulier de n cotes."""
    return side / (2 * math.sin(math.pi / n))


def apothem_from_side(n: int, side: float = BOND_CC) -> float:
    """Apotheme (distance centre -> milieu d'arete) d'un polygone regulier."""
    return side / (2 * math.tan(math.pi / n))


class CyclePlacer:
    """Place les cycles comme polygones reguliers via BFS sur le dual.

    Apres build(), l'attribut coords contient les coordonnees 2D
    de tous les sommets :
        coords : dict[str, tuple[float, float]]
            label -> (x, y)
    """

    def __init__(self, graph: BenzenoidGraph, solution: dict,
                 cycle_vertices: dict[int, list[str]]):
        self.graph = graph
        self.solution = solution
        self.cycle_vertices = cycle_vertices

        # Resultat
        self.coords: dict[str, tuple[float, float]] = {}

        # Centres des cycles places (pour orienter les perpendiculaires)
        self._cycle_centers: dict[int, tuple[float, float]] = {}

    def build(self):
        """Parcours BFS du dual et placement de chaque cycle."""
        root = self._choose_root()

        visited = set()
        queue = deque()

        # Placer le cycle racine
        self._place_root_cycle(root)
        visited.add(root)

        # Enfiler les voisins de la racine
        for neighbor in self.graph.neighbors(root):
            queue.append((neighbor, root))

        # BFS
        while queue:
            current, parent = queue.popleft()
            if current in visited:
                continue

            self._place_cycle(current, parent)
            visited.add(current)

            for neighbor in self.graph.neighbors(current):
                if neighbor not in visited:
                    queue.append((neighbor, current))

    def _choose_root(self) -> int:
        """Choisit la racine du BFS.

        Prefere un hexagone inchange (taille 6) de degre maximal dans le dual.
        """
        best = None
        best_score = -1

        for v in range(self.graph.h):
            deg = self.graph.degree(v)
            # Bonus pour les hexagones inchanges (plus stables comme ancrage)
            score = deg + (0.5 if self.solution[v] == 6 else 0)
            if score > best_score:
                best_score = score
                best = v

        return best

    def _place_root_cycle(self, root: int):
        """Place le cycle racine comme polygone regulier centre en (0,0)."""
        verts = self.cycle_vertices[root]
        n = len(verts)
        R = radius_from_side(n)

        for i, label in enumerate(verts):
            angle = 2 * math.pi * i / n + math.pi / 2  # premier sommet en haut
            x = R * math.cos(angle)
            y = R * math.sin(angle)
            self.coords[label] = (x, y)

        # Centre du cycle racine
        self._cycle_centers[root] = (0.0, 0.0)

    def _place_cycle(self, hex_idx: int, parent_idx: int):
        """Place un cycle adjacent a son parent dans le BFS.

        Utilise l'arete partagee (deja placee) comme ancrage, calcule le
        centre du nouveau cycle sur la perpendiculaire, puis place les
        sommets restants comme polygone regulier.
        """
        # Recuperer les positions de l'arete partagee
        pos_p, pos_v = self.graph.edge_positions[(parent_idx, hex_idx)]

        # Sommets de l'arete partagee (labels de l'hexagone parent original)
        parent_hex = self.graph.hexagons[parent_idx]
        v1_label = parent_hex[pos_p]
        v2_label = parent_hex[(pos_p + 1) % len(parent_hex)]

        v1x, v1y = self.coords[v1_label]
        v2x, v2y = self.coords[v2_label]

        # Taille du cycle a placer
        n = self.solution[hex_idx]

        # Centre du nouveau cycle : milieu de l'arete + apotheme * perpendiculaire
        mx = (v1x + v2x) / 2
        my = (v1y + v2y) / 2

        dx = v2x - v1x
        dy = v2y - v1y

        # Perpendiculaire (deux directions possibles)
        perp_x, perp_y = -dy, dx
        norm = math.sqrt(perp_x ** 2 + perp_y ** 2)
        if norm > 1e-10:
            perp_x /= norm
            perp_y /= norm

        # Orienter vers l'exterieur (direction opposee au centre du parent)
        parent_cx, parent_cy = self._cycle_centers[parent_idx]
        to_mid_x = mx - parent_cx
        to_mid_y = my - parent_cy
        if perp_x * to_mid_x + perp_y * to_mid_y < 0:
            perp_x, perp_y = -perp_x, -perp_y

        apo = apothem_from_side(n)
        cx = mx + perp_x * apo
        cy = my + perp_y * apo

        self._cycle_centers[hex_idx] = (cx, cy)

        # Placer les sommets du cycle comme polygone regulier
        R = radius_from_side(n)
        verts = self.cycle_vertices[hex_idx]

        # Identifier les sommets de l'arete partagee du cote de l'enfant
        # (memes sommets physiques que v1/v2 du parent, ordre possiblement inverse)
        child_hex = self.graph.hexagons[hex_idx]
        child_v1_label = child_hex[pos_v]
        child_v2_label = child_hex[(pos_v + 1) % len(child_hex)]

        # Position de child_v1 dans le cycle modifie de l'enfant
        idx_v1 = verts.index(child_v1_label)

        # Angles de child_v1 et child_v2 vus depuis le centre de l'enfant
        cv1x, cv1y = self.coords[child_v1_label]
        cv2x, cv2y = self.coords[child_v2_label]
        angle_cv1 = math.atan2(cv1y - cy, cv1x - cx)
        angle_cv2 = math.atan2(cv2y - cy, cv2x - cx)

        # Sens de rotation : de child_v1 vers child_v2 dans le cycle enfant
        step = 2 * math.pi / n
        diff = (angle_cv2 - angle_cv1 + math.pi) % (2 * math.pi) - math.pi
        if diff < 0:
            step = -step  # sens horaire

        # Placer chaque sommet du cycle
        for k in range(n):
            idx = (idx_v1 + k) % n
            label = verts[idx]

            if label in self.coords:
                # Sommet deja place (partage avec un autre cycle) : garder
                continue

            angle = angle_cv1 + k * step
            x = cx + R * math.cos(angle)
            y = cy + R * math.sin(angle)
            self.coords[label] = (x, y)
