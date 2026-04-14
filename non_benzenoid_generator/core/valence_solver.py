"""Résolution des valences : placement des doubles liaisons et H

Approche : couplage maximum pondéré (algorithme de Blossom via NetworkX)
sur le graphe carbone-carbone.

  - Chaque lien C-C est un candidat pour double liaison (y compris les
    liaisons de fusion internes).
  - Poids plus élevé pour les arêtes appartenant à des cycles à 7 sommets :
    les structures azuléniques préfèrent les doubles liaisons dans le cycle 7.
  - maxcardinality=True garantit d'abord le maximum de doubles liaisons,
    puis optimise le poids.
  - Cas impair (radical) : un carbone reste sans double liaison ni H.
"""

import math
from typing import List, Set
from core.topology import MolecularGraph

try:
    import networkx as nx
except ImportError:
    raise ImportError(
        "NetworkX est requis pour le placement des doubles liaisons "
        "(algorithme de Blossom). Installez-le avec : pip install networkx"
    )


# Poids des arêtes selon la taille du cycle d'appartenance
_WEIGHT_IN_7 = 10   # forte préférence pour les doubles des cycles 7
_WEIGHT_IN_5 = 3    # légère préférence pour les cycles 5 vs liaisons de fusion
_WEIGHT_DEFAULT = 1


class ValenceSolver:
    """
    Résout le problème de satisfaction des valences via couplage maximum pondéré.

    Paramètres
    ----------
    graph : MolecularGraph
        Le graphe moléculaire AVANT placement des H.  Les cycles doivent être
        renseignés (graph.cycles) afin de pouvoir identifier les cycles à 7.
    """

    def __init__(self, graph: MolecularGraph):
        self.graph = graph

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def solve(self) -> bool:
        """
        Place les doubles liaisons puis les hydrogènes.
        Retourne True si au moins un couplage a été trouvé.
        """
        carbons = [vid for vid, v in self.graph.vertices.items()
                   if v.element == 'C']

        matched = self._solve_matching(carbons)

        self._place_hydrogens(carbons, matched)
        return True

    # ------------------------------------------------------------------
    # Méthode principale : couplage maximum pondéré (NetworkX / Blossom)
    # ------------------------------------------------------------------

    def _solve_matching(self, carbons: List[int]) -> Set[int]:
        """
        Construit un graphe NetworkX carbon-only, pondère les arêtes, puis
        appelle max_weight_matching.

        Retourne l'ensemble des carbones couverts par le couplage (i.e. ceux
        qui ont une double liaison).
        """
        # --- Identifier les arêtes par cycle ---
        edges_in_7: Set[tuple] = set()
        edges_in_5: Set[tuple] = set()
        for cycle in self.graph.cycles:
            verts = cycle.vertices
            n = len(verts)
            for i in range(n):
                a, b = verts[i], verts[(i + 1) % n]
                key = (min(a, b), max(a, b))
                if cycle.size == 7:
                    edges_in_7.add(key)
                elif cycle.size == 5:
                    edges_in_5.add(key)

        # --- Construire le graphe pondéré ---
        G = nx.Graph()
        G.add_nodes_from(carbons)

        carbon_set = set(carbons)
        for vid in carbons:
            for other_id, _ in self.graph.vertices[vid].bonds:
                if other_id <= vid:
                    continue
                if other_id not in carbon_set:
                    continue
                key = (vid, other_id)
                if key in edges_in_7:
                    w = _WEIGHT_IN_7
                elif key in edges_in_5:
                    w = _WEIGHT_IN_5
                else:
                    w = _WEIGHT_DEFAULT
                G.add_edge(vid, other_id, weight=w)

        # --- Couplage maximum pondéré ---
        # maxcardinality=True : maximise d'abord le nombre de paires (doubles
        # liaisons), puis parmi les couplages de même cardinalité, maximise le
        # poids (préférence cycle 7).
        matching = nx.max_weight_matching(G, maxcardinality=True)

        # --- Appliquer le couplage ---
        covered: Set[int] = set()
        for v1, v2 in matching:
            self._set_bond_order(v1, v2, 2)
            covered.add(v1)
            covered.add(v2)

        return covered

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_bond_order(self, v1: int, v2: int, order: int):
        """Modifie l'ordre d'une liaison existante dans les deux sens."""
        for i, (v, _) in enumerate(self.graph.vertices[v1].bonds):
            if v == v2:
                self.graph.vertices[v1].bonds[i] = (v, order)
                break
        for i, (v, _) in enumerate(self.graph.vertices[v2].bonds):
            if v == v1:
                self.graph.vertices[v2].bonds[i] = (v, order)
                break

    def _place_hydrogens(self, carbons: List[int], covered: Set[int]):
        """
        Place les H selon le type de carbone (procédure du chimiste) :

        Carbone COUVERT (sp², une double liaison) :
          - degré 2 C-C : 1H  (valence = 1simple + 2double + 1H = 4)
          - degré 3 C-C : 0H  (valence = 2simples + 2double = 4)

        Carbone NON couvert (radical, valence 3) :
          - degré >= 3 C-C : 0H  (3 liaisons C-C, électron célibataire)
          - degré 2 C-C    : 1H  (2 C-C simples + 1H + électron célibataire)
          - degré 1 C-C    : 2H  (rare dans nos polycycles)

        Règle générale radical : n_H = 4 - cc_degree - 1 (réserve 1 pour l'électron)
        """
        for vid in carbons:
            cc_degree = self.graph.get_carbon_degree(vid)

            if vid in covered:
                # Carbone sp² : exactement 1H si la valence le permet
                valence_used = self.graph.get_valence_used(vid)
                remaining = 4 - valence_used
                if remaining >= 1:
                    self._add_hydrogen(vid)
            else:
                # Carbone radical
                if cc_degree >= 3:
                    pass  # valence 3 par les seules liaisons C-C, pas de H
                else:
                    n_h = max(0, 4 - cc_degree - 1)
                    for _ in range(n_h):
                        self._add_hydrogen(vid)

    def _add_hydrogen(self, carbon_id: int):
        """Ajoute un atome H à un carbone selon la direction externe."""
        c = self.graph.vertices[carbon_id]

        vx, vy, vz = 0.0, 0.0, 0.0
        for other_id, _ in c.bonds:
            other = self.graph.vertices[other_id]
            vx += other.x - c.x
            vy += other.y - c.y
            vz += other.z - c.z

        norm = math.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
        if norm > 0.1:
            vx, vy, vz = -vx / norm, -vy / norm, -vz / norm
        else:
            vx, vy, vz = 1.0, 0.0, 0.0

        from config import BOND_LENGTH_CH
        hx = c.x + vx * BOND_LENGTH_CH
        hy = c.y + vy * BOND_LENGTH_CH
        hz = c.z + vz * BOND_LENGTH_CH

        h_id = self.graph.add_vertex('H', hx, hy, hz)
        self.graph.add_bond(carbon_id, h_id, 1)
