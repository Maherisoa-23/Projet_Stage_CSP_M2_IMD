"""
Phase A : Reconstruction topologique du benzenoide modifie.

A partir du graphe hexagonal original et d'une solution CSP (assignation
de tailles 5/6/7 a chaque hexagone), ce module construit la topologie
correcte de la molecule : quels sommets existent, quelles liaisons, et
quel est l'ordre cyclique des sommets pour chaque cycle.

Invariant fondamental : les cotes partages (sigma[i]=1) entre hexagones
ne sont JAMAIS affectes par les modifications, car celles-ci n'operent
que sur le bloc libre (cotes ou sigma[i]=0).
"""

from utils.parser import BenzenoidGraph


class CycleTopology:
    """Gere les modifications topologiques du benzenoide.

    Apres build(), les attributs suivants sont disponibles :
        cycle_vertices : dict[int, list[str]]
            Pour chaque hexagone, la liste ordonnee (cyclique) des labels
            de sommets du cycle modifie.
        vertex_set : set[str]
            Tous les labels de carbones (originaux survivants + nouveaux).
        bond_set : set[frozenset[str, str]]
            Toutes les liaisons C-C sous forme de frozensets.
    """

    def __init__(self, graph: BenzenoidGraph, solution: dict):
        self.graph = graph
        self.solution = solution

        # Resultats (peuples par build())
        self.cycle_vertices: dict[int, list[str]] = {}
        self.vertex_set: set[str] = set(graph.vertices)
        self.bond_set: set[frozenset] = set()

        # Initialiser bond_set depuis les aretes du graphe original
        for s1, s2 in graph.edges:
            self.bond_set.add(frozenset((s1, s2)))

    def build(self):
        """Applique toutes les modifications topologiques."""
        for v_idx in range(self.graph.h):
            target = self.solution[v_idx]
            hex_verts = self.graph.hexagons[v_idx]

            if target == 6:
                self.cycle_vertices[v_idx] = list(hex_verts)
            elif target == 5:
                self._apply_pentagon(v_idx)
            elif target == 7:
                self._apply_heptagon(v_idx)

    def _get_interior_free_vertices(self, hex_idx: int) -> list[int]:
        """Retourne les indices des sommets interieurs au bloc libre.

        Un sommet h[i] est interieur au bloc libre si ses deux cotes
        incidents dans le cycle (cote i-1 et cote i) sont tous deux libres.
        Ces sommets n'appartiennent a aucun autre hexagone et peuvent
        etre retires en toute securite.

        Returns:
            Liste d'indices (dans l'hexagone) des sommets interieurs.
        """
        pattern = self.graph.patterns[hex_idx]
        n = len(pattern)  # toujours 6 pour un hexagone
        interior = []
        for i in range(n):
            if pattern[(i - 1) % n] == 0 and pattern[i] == 0:
                interior.append(i)
        return interior

    def _apply_pentagon(self, hex_idx: int):
        """Hexagone -> pentagone : retire le sommet interieur du milieu."""
        hex_verts = self.graph.hexagons[hex_idx]
        interior = self._get_interior_free_vertices(hex_idx)

        if not interior:
            raise ValueError(
                f"Hexagone {hex_idx}: impossible de creer un pentagone, "
                f"aucun sommet interieur libre. Pattern={self.graph.patterns[hex_idx]}"
            )

        # Choisir le sommet du milieu du bloc interieur
        mid = interior[len(interior) // 2]
        removed_label = hex_verts[mid]
        n = len(hex_verts)

        # Voisins dans le cycle
        prev_label = hex_verts[(mid - 1) % n]
        next_label = hex_verts[(mid + 1) % n]

        # Retirer le sommet
        self.vertex_set.discard(removed_label)

        # Retirer les deux aretes incidentes dans ce cycle
        self.bond_set.discard(frozenset((prev_label, removed_label)))
        self.bond_set.discard(frozenset((removed_label, next_label)))

        # Ajouter la nouvelle arete (reconnexion)
        self.bond_set.add(frozenset((prev_label, next_label)))

        # Construire le cycle modifie (ordre cyclique sans le sommet retire)
        new_cycle = [v for v in hex_verts if v != removed_label]
        self.cycle_vertices[hex_idx] = new_cycle

    def _apply_heptagon(self, hex_idx: int):
        """Hexagone -> heptagone : insere un sommet au milieu du bloc libre."""
        hex_verts = self.graph.hexagons[hex_idx]
        pattern = self.graph.patterns[hex_idx]
        n = len(hex_verts)

        # Identifier les cotes libres
        free_sides = [i for i in range(n) if pattern[i] == 0]

        if not free_sides:
            raise ValueError(
                f"Hexagone {hex_idx}: impossible de creer un heptagone, "
                f"aucun cote libre. Pattern={pattern}"
            )

        # Cote libre du milieu
        mid_side = free_sides[len(free_sides) // 2]
        v1_label = hex_verts[mid_side]
        v2_label = hex_verts[(mid_side + 1) % n]

        # Nouveau sommet avec label synthetique
        new_label = f"new_{hex_idx}_{mid_side}"

        # Ajouter le nouveau sommet
        self.vertex_set.add(new_label)

        # Retirer l'ancienne arete
        self.bond_set.discard(frozenset((v1_label, v2_label)))

        # Ajouter les deux nouvelles aretes
        self.bond_set.add(frozenset((v1_label, new_label)))
        self.bond_set.add(frozenset((new_label, v2_label)))

        # Construire le cycle modifie (insertion du nouveau sommet)
        new_cycle = []
        for i in range(n):
            new_cycle.append(hex_verts[i])
            if i == mid_side:
                new_cycle.append(new_label)
        self.cycle_vertices[hex_idx] = new_cycle
