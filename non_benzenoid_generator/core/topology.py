"""Graphe moléculaire pour structures polycycliques avec gestion des fusions"""

from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, field

@dataclass
class Vertex:
    id: int
    element: str  # 'C' ou 'H'
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    bonds: List[Tuple[int, int]] = field(default_factory=list)  # (voisin_id, ordre)

@dataclass 
class Cycle:
    vertices: List[int]  # IDs des sommets dans l'ordre
    size: int

class MolecularGraph:
    """Graphe moléculaire gérant les cycles fusionnés"""
    
    def __init__(self):
        self.vertices: Dict[int, Vertex] = {}
        self.next_id = 1
        self.cycles: List[Cycle] = []
        
    def add_vertex(self, element: str = 'C', x: float = 0.0, y: float = 0.0, z: float = 0.0) -> int:
        """Ajoute un sommet et retourne son ID"""
        vid = self.next_id
        self.vertices[vid] = Vertex(id=vid, element=element, x=x, y=y, z=z)
        self.next_id += 1
        return vid
    
    def add_bond(self, v1: int, v2: int, order: int = 1):
        """Ajoute une liaison entre deux sommets (évite les doublons)"""
        if v1 not in self.vertices or v2 not in self.vertices:
            raise ValueError(f"Sommet inexistant: {v1} ou {v2}")
        
        # Vérifier si la liaison existe déjà
        existing = any(v == v2 for v, _ in self.vertices[v1].bonds)
        if not existing:
            self.vertices[v1].bonds.append((v2, order))
            self.vertices[v2].bonds.append((v1, order))
    
    def get_carbon_neighbors(self, vid: int) -> List[int]:
        """Retourne les voisins carbones d'un sommet"""
        return [v for v, _ in self.vertices[vid].bonds 
                if self.vertices[v].element == 'C']
    
    def get_degree(self, vid: int) -> int:
        """Degré dans le graphe (nombre de voisins, tous éléments)"""
        return len(self.vertices[vid].bonds)
    
    def get_carbon_degree(self, vid: int) -> int:
        """Nombre de voisins carbones"""
        return len(self.get_carbon_neighbors(vid))
    
    def get_valence_used(self, vid: int) -> int:
        """Somme des ordres de liaison"""
        return sum(order for _, order in self.vertices[vid].bonds)
    
    def get_cycle_sizes(self) -> List[int]:
        """Retourne les tailles de tous les cycles"""
        return [len(c.vertices) for c in self.cycles]
    
    def is_valid_non_benzenoid(self) -> bool:
        """Vérifie qu'il n'y a que des cycles 5, 6 ou 7"""
        return all(len(c.vertices) in [5, 6, 7] for c in self.cycles)
    
    def count_carbons(self) -> int:
        """Nombre d'atomes de carbone"""
        return sum(1 for v in self.vertices.values() if v.element == 'C')
    
    def to_cml_data(self) -> Tuple[List[dict], List[dict]]:
        """Prépare les données pour export CML"""
        atoms = []
        for v in self.vertices.values():
            atoms.append({
                'id': f'a{v.id}',
                'elementType': v.element,
                'x3': f'{v.x:.6f}',
                'y3': f'{v.y:.6f}',
                'z3': f'{v.z:.6f}'
            })
        
        bonds = []
        seen = set()
        for v in self.vertices.values():
            for other_id, order in v.bonds:
                key = tuple(sorted([v.id, other_id]))
                if key not in seen:
                    bonds.append({
                        'atomRefs2': f'a{key[0]} a{key[1]}',
                        'order': str(order)
                    })
                    seen.add(key)
        
        return atoms, bonds