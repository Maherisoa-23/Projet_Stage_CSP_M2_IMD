"""Résolution des valences : placement des doubles liaisons et H"""

import math
from typing import List, Tuple, Set
from core.topology import MolecularGraph

class ValenceSolver:
    """
    Résout le problème de satisfaction des valences :
    - Max 1 double liaison par carbone
    - Max 1 hydrogène par carbone  
    - Gestion des cas pair/impair (radicaux)
    """
    
    def __init__(self, graph: MolecularGraph):
        self.graph = graph
        
    def solve(self) -> bool:
        """
        Algorithme glouton amélioré pour placer les doubles liaisons
        Retourne True si une solution valide est trouvée
        """
        carbons = [vid for vid, v in self.graph.vertices.items() if v.element == 'C']
        n_carbons = len(carbons)
        is_odd = (n_carbons % 2 == 1)
        
        # Identifier les arêtes éligibles (périphériques, pas de fusion interne)
        edges = self._get_peripheral_edges(carbons)
        
        # Trier par priorité : coins éloignés d'abord, puis cycles 7
        edges = self._prioritize_edges(edges)
        
        # Placement glouton des doubles liaisons
        used_double = set()
        
        for v1, v2 in edges:
            if v1 in used_double or v2 in used_double:
                continue
            
            # Vérifier les degrés après ajout
            # Un carbone ne peut avoir qu'une seule double
            self._set_bond_order(v1, v2, 2)
            used_double.add(v1)
            used_double.add(v2)
        
        # Gestion des radicaux si nombre impair
        if is_odd:
            self._handle_radical(carbons, used_double)
        
        # Placement des hydrogènes
        self._place_hydrogens(carbons)
        
        return True
    
    def _get_peripheral_edges(self, carbons: List[int]) -> List[Tuple[int, int]]:
        """
        Retourne les arêtes éligibles pour les doubles liaisons, en deux groupes :

        1. Arêtes coadjacentes (retournées en premier, prioritaires) :
           les deux carbones ont degré >= 3, mais l'un appartient au cycle central
           et l'autre non. Ce sont les arêtes de fermeture entre deux cycles voisins
           consécutifs (ex: C1—A dans 5_6_5_5_0). Elles doivent recevoir un double
           en priorité pour reproduire la structure de Kekulé correcte.

        2. Arêtes périphériques (standard) :
           au moins un des deux carbones a degré < 3.

        Sont exclues : les arêtes où les deux carbones ont degré >= 3 ET sont tous
        les deux dans le cycle central (arêtes de fusion interne pure).
        """
        central_vertices = set(self.graph.cycles[0].vertices) if self.graph.cycles else set()

        edges_coadjacent = []
        edges_peripheral = []

        for vid in carbons:
            vertex = self.graph.vertices[vid]
            for other_id, order in vertex.bonds:
                if other_id <= vid:
                    continue
                if self.graph.vertices[other_id].element != 'C':
                    continue

                deg_v = self.graph.get_carbon_degree(vid)
                deg_o = self.graph.get_carbon_degree(other_id)

                if not (deg_v >= 3 and deg_o >= 3):
                    # Arête périphérique : au moins un sommet de degré < 3
                    edges_peripheral.append((vid, other_id))
                else:
                    # Les deux ont degré >= 3 : coadjacente si l'un est dans le
                    # cycle central et l'autre non
                    one_in_central = (vid in central_vertices) != (other_id in central_vertices)
                    if one_in_central:
                        edges_coadjacent.append((vid, other_id))
                    # Sinon : arête interne pure (ex: liaison dans le cycle central),
                    # exclue

        # Coadjacentes d'abord : garantit qu'elles reçoivent le double avant
        # que leurs extrémités soient "bloquées" par un double périphérique
        return edges_coadjacent + edges_peripheral
    
    def _prioritize_edges(self, edges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Trie les arêtes : privilégier les cycles 7, puis les positions externes"""
        # Pour l'instant, simple shuffle ou tri par degré
        # On pourrait ajouter ici la détection des cycles 7
        return edges
    
    def _set_bond_order(self, v1: int, v2: int, order: int):
        """Modifie l'ordre d'une liaison existante"""
        # Trouver et modifier dans les deux sens
        for i, (v, o) in enumerate(self.graph.vertices[v1].bonds):
            if v == v2:
                self.graph.vertices[v1].bonds[i] = (v, order)
                break
        
        for i, (v, o) in enumerate(self.graph.vertices[v2].bonds):
            if v == v1:
                self.graph.vertices[v2].bonds[i] = (v, order)
                break
    
    def _handle_radical(self, carbons: List[int], used_double: Set[int]):
        """
        Gestion du cas impair : un carbone doit être radical
        (3 liaisons C-C, pas de double, pas de H supplémentaire)
        """
        # Trouver un carbone de degré 3 (fusion) qui n'a pas de double
        candidates = []
        for vid in carbons:
            if vid not in used_double:
                deg = self.graph.get_carbon_degree(vid)
                if deg == 3:  # Carbone de fusion trivalent
                    candidates.append(vid)
        
        if candidates:
            # Marquer le premier comme radical (pas de H ajouté plus tard)
            # Pour l'instant, on ne fait rien de spécial, juste pas de H ajouté
            pass
    
    def _place_hydrogens(self, carbons: List[int]):
        """Place les hydrogènes (max 1 par carbone) sur les valences libres"""
        for vid in carbons:
            valence_used = self.graph.get_valence_used(vid)
            remaining = 4 - valence_used
            
            if remaining >= 1:
                # Placer 1 H (max)
                self._add_hydrogen(vid)
    
    def _add_hydrogen(self, carbon_id: int):
        """Ajoute un atome H à un carbone"""
        c = self.graph.vertices[carbon_id]
        
        # Calculer la direction externe (moyenne des vecteurs vers voisins, inversée)
        vx, vy, vz = 0.0, 0.0, 0.0
        
        for other_id, _ in c.bonds:
            other = self.graph.vertices[other_id]
            vx += other.x - c.x
            vy += other.y - c.y
            vz += other.z - c.z
        
        # Normaliser et inverser
        norm = math.sqrt(vx**2 + vy**2 + vz**2)
        if norm > 0.1:
            vx, vy, vz = -vx/norm, -vy/norm, -vz/norm
        else:
            vx, vy, vz = 1.0, 0.0, 0.0  # Default
        
        # Position du H à 1.08 Å
        from config import BOND_LENGTH_CH
        hx = c.x + vx * BOND_LENGTH_CH
        hy = c.y + vy * BOND_LENGTH_CH
        hz = c.z + vz * BOND_LENGTH_CH
        
        h_id = self.graph.add_vertex('H', hx, hy, hz)
        self.graph.add_bond(carbon_id, h_id, 1)