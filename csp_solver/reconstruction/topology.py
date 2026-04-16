"""
Phase A : Reconstruction topologique du benzenoide modifie.

A partir du graphe hexagonal original et d'une solution CSP (assignation
de tailles 5/6/7 a chaque hexagone), ce module construit la topologie
correcte de la molecule : quels sommets existent, quelles liaisons, et
quel est l'ordre cyclique des sommets pour chaque cycle.

Invariant fondamental : les cotes partages (sigma[i]=1) entre hexagones
ne sont JAMAIS affectes par les modifications, car celles-ci n'operent
que sur un bloc libre (cotes ou sigma[i]=0).

Quand b(v) >= 2 (blocs libres separes), l'heptagone peut etre cree dans
n'importe lequel des blocs. Le parametre block_choices permet de choisir.
"""

from utils.parser import BenzenoidGraph, count_zero_blocks


class CycleTopology:
    """Gere les modifications topologiques du benzenoide.

    Apres build(), les attributs suivants sont disponibles :
        cycle_vertices : dict[int, list[str]]
        vertex_set : set[str]
        bond_set : set[frozenset[str, str]]
    """

    def __init__(self, graph: BenzenoidGraph, solution: dict):
        self.graph = graph
        self.solution = solution

        self.cycle_vertices: dict[int, list[str]] = {}
        self.vertex_set: set[str] = set(graph.vertices)
        self.bond_set: set[frozenset] = set()

        for s1, s2 in graph.edges:
            self.bond_set.add(frozenset((s1, s2)))

    def build(self, block_choices: dict = None):
        """Applique toutes les modifications topologiques.

        Args:
            block_choices: dict optionnel {hex_idx: block_index}.
                Pour les hexagones avec b(v)>=2 et taille=7, indique
                dans quel bloc libre inserer le sommet (0, 1, ...).
                Si absent, le premier bloc est utilise.
        """
        if block_choices is None:
            block_choices = {}

        for v_idx in range(self.graph.h):
            target = self.solution[v_idx]
            hex_verts = self.graph.hexagons[v_idx]

            if target == 6:
                self.cycle_vertices[v_idx] = list(hex_verts)
            elif target == 5:
                self._apply_pentagon(v_idx)
            elif target == 7:
                bc = block_choices.get(v_idx, 0)
                self._apply_heptagon(v_idx, block_choice=bc)

    def get_free_blocks(self, hex_idx: int) -> list:
        """Retourne la liste des blocs de cotes libres (consecutifs).

        Chaque bloc est une liste d'indices de cotes ou sigma=0.
        Parcours cyclique depuis un cote partage pour ne pas couper un bloc.

        Exemple : pattern (0, 1, 0, 1, 1, 1) → [[0], [2]]
        Exemple : pattern (0, 0, 1, 0, 0, 0) → [[3, 4, 5, 0, 1]]  (wrap-around)
        """
        pattern = self.graph.patterns[hex_idx]
        n = len(pattern)

        if all(p == 0 for p in pattern):
            return [list(range(n))]

        # Trouver un cote partage comme point de depart
        start = next(i for i in range(n) if pattern[i] == 1)

        blocks = []
        current_block = []
        for offset in range(n):
            idx = (start + offset) % n
            if pattern[idx] == 0:
                current_block.append(idx)
            else:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
        if current_block:
            blocks.append(current_block)

        return blocks

    def get_multiblock_hexagons(self) -> list:
        """Retourne les hexagones avec b>=2 et taille != 6 (qui ont plusieurs variantes)."""
        result = []
        for v_idx in range(self.graph.h):
            if self.solution[v_idx] == 6:
                continue
            blocks = self.get_free_blocks(v_idx)
            if len(blocks) >= 2:
                result.append((v_idx, len(blocks)))
        return result

    def _get_interior_free_vertices(self, hex_idx: int) -> list:
        """Retourne les indices des sommets interieurs au bloc libre."""
        pattern = self.graph.patterns[hex_idx]
        n = len(pattern)
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

        mid = interior[len(interior) // 2]
        removed_label = hex_verts[mid]
        n = len(hex_verts)

        prev_label = hex_verts[(mid - 1) % n]
        next_label = hex_verts[(mid + 1) % n]

        self.vertex_set.discard(removed_label)
        self.bond_set.discard(frozenset((prev_label, removed_label)))
        self.bond_set.discard(frozenset((removed_label, next_label)))
        self.bond_set.add(frozenset((prev_label, next_label)))

        new_cycle = [v for v in hex_verts if v != removed_label]
        self.cycle_vertices[hex_idx] = new_cycle

    def _apply_heptagon(self, hex_idx: int, block_choice: int = 0):
        """Hexagone -> heptagone : insere un sommet dans un bloc libre.

        Args:
            block_choice: index du bloc libre dans lequel inserer (0 = premier bloc).
        """
        hex_verts = self.graph.hexagons[hex_idx]
        pattern = self.graph.patterns[hex_idx]
        n = len(hex_verts)

        blocks = self.get_free_blocks(hex_idx)

        if not blocks:
            raise ValueError(
                f"Hexagone {hex_idx}: impossible de creer un heptagone, "
                f"aucun cote libre. Pattern={pattern}"
            )

        # Choisir le bloc
        block_idx = min(block_choice, len(blocks) - 1)
        block = blocks[block_idx]

        # Cote libre du milieu du bloc choisi
        mid_side = block[len(block) // 2]
        v1_label = hex_verts[mid_side]
        v2_label = hex_verts[(mid_side + 1) % n]

        new_label = f"new_{hex_idx}_{mid_side}"

        self.vertex_set.add(new_label)
        self.bond_set.discard(frozenset((v1_label, v2_label)))
        self.bond_set.add(frozenset((v1_label, new_label)))
        self.bond_set.add(frozenset((new_label, v2_label)))

        new_cycle = []
        for i in range(n):
            new_cycle.append(hex_verts[i])
            if i == mid_side:
                new_cycle.append(new_label)
        self.cycle_vertices[hex_idx] = new_cycle
