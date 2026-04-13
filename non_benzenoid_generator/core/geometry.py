"""Moteur de placement géométrique 3D avec gestion correcte des fusions coadjacentes"""

import math
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from core.topology import MolecularGraph, Cycle

# Constantes
RADIUS_CC = 1.42  # Distance C-C

def radius_from_side(n: int, side: float = RADIUS_CC) -> float:
    """Rayon du cercle circonscrit d'un polygone régulier de n côtés"""
    return side / (2 * math.sin(math.pi / n))

def apothem_from_side(n: int, side: float = RADIUS_CC) -> float:
    """Apothème (distance centre -> milieu d'arête)"""
    return side / (2 * math.tan(math.pi / n))

def circle_intersections(c1: Tuple[float, float], r1: float, 
                        c2: Tuple[float, float], r2: float) -> List[Tuple[float, float]]:
    """
    Calcule les intersections de deux cercles.
    Retourne 0, 1 ou 2 points d'intersection.
    """
    x1, y1 = c1
    x2, y2 = c2
    d = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    
    # Vérification des cas dégénérés
    if d > r1 + r2 or d < abs(r1 - r2) or (d == 0 and r1 == r2):
        return []
    
    # Distance du centre 1 à la ligne des intersections
    a = (r1**2 - r2**2 + d**2) / (2 * d)
    h = math.sqrt(max(0, r1**2 - a**2))
    
    # Point sur la ligne entre les deux centres
    xm = x1 + a * (x2 - x1) / d
    ym = y1 + a * (y2 - y1) / d
    
    # Deux points d'intersection (symétriques)
    xs1 = xm + h * (y2 - y1) / d
    ys1 = ym - h * (x2 - x1) / d
    
    xs2 = xm - h * (y2 - y1) / d
    ys2 = ym + h * (x2 - x1) / d
    
    if h == 0:
        return [(xm, ym)]  # Un seul point (tangence)
    
    return [(xs1, ys1), (xs2, ys2)]

class GeometryEngine:
    """Calculateur de géométrie pour molécules polycycliques planaires"""
    
    def __init__(self, graph: MolecularGraph):
        self.graph = graph
        self.placed_vertices: Dict[int, Tuple[float, float, float]] = {}
        # Stocke pour chaque position: (centre, rayon, liste_ids_sommets)
        self.cycle_geoms: Dict[int, Tuple[Tuple[float, float], float, List[int]]] = {}
        
    def place_central_cycle(self, size: int, offset_angle: float = math.pi/2) -> List[int]:
        """
        Place le cycle central en (0,0) dans le plan XY
        Retourne la liste des IDs des sommets créés
        """
        R = radius_from_side(size)
        vertex_ids = []
        
        for i in range(size):
            angle = 2 * math.pi * i / size + offset_angle
            x = R * math.cos(angle)
            y = R * math.sin(angle)
            z = 0.0
            
            vid = self.graph.add_vertex('C', x, y, z)
            vertex_ids.append(vid)
            self.placed_vertices[vid] = (x, y, z)
        
        # Créer les liaisons du cycle central
        for i in range(size):
            self.graph.add_bond(vertex_ids[i], vertex_ids[(i+1) % size], 1)
        
        # Ajouter au graphe comme cycle
        self.graph.cycles.append(Cycle(vertices=vertex_ids, size=size))
        
        return vertex_ids
    
    def compute_cycle_center(self, v1_id: int, v2_id: int, 
                            n_sides: int, direction: int = 1) -> Tuple[float, float]:
        """
        Calcule le centre d'un cycle voisin fusionné sur l'arête (v1, v2)
        """
        v1 = self.graph.vertices[v1_id]
        v2 = self.graph.vertices[v2_id]
        
        # Milieu de l'arête
        mx = (v1.x + v2.x) / 2
        my = (v1.y + v2.y) / 2
        
        # Vecteur perpendiculaire
        dx = v2.x - v1.x
        dy = v2.y - v1.y
        perp_x, perp_y = -dy, dx
        
        # Normaliser
        norm = math.sqrt(perp_x**2 + perp_y**2)
        if norm > 0:
            perp_x, perp_y = perp_x/norm, perp_y/norm
        
        # Orienter vers l'extérieur
        if (perp_x * mx + perp_y * my) < 0:
            perp_x, perp_y = -perp_x, -perp_y
        
        # Centre du nouveau polygone
        apo = apothem_from_side(n_sides)
        cx = mx + perp_x * apo * direction
        cy = my + perp_y * apo * direction
        
        return (cx, cy)
    
    def place_cycle_with_shared_vertex(self, v1_id: int, v2_id: int, n_sides: int,
                                      shared_vertex_id: Optional[int] = None) -> Tuple[List[int], Tuple[float, float]]:
        """
        Place un cycle polygonal régulier fusionné sur l'arête (v1, v2).

        Si shared_vertex_id est fourni, ce sommet existant est réutilisé en position
        k=n_sides-1 (adjacent à v1), sans modifier ses coordonnées : elles restent
        celles du polygone régulier du cycle précédent, ce qui garantit des liaisons
        de 1.42 Å pour ce cycle-là. L'arête de fermeture (shared→v1) sera légèrement
        distordue et sera corrigée par l'optimisation UFF ultérieure.

        Retourne: (liste ordonnée des IDs du cycle, centre du cycle)
        """
        cx, cy = self.compute_cycle_center(v1_id, v2_id, n_sides)
        R = radius_from_side(n_sides)

        v1 = self.graph.vertices[v1_id]
        angle_0 = math.atan2(v1.y - cy, v1.x - cx)
        
        cycle_vertices = [v1_id, v2_id]  # Indices 0 et 1

        # Sommets 2 à n_sides-1, sens horaire depuis v1
        # (v2 est à angle_0 - 2π/n depuis le centre, donc on décrémente)
        for k in range(2, n_sides):
            if k == n_sides - 1 and shared_vertex_id is not None:
                # Sommet partagé avec le cycle précédent : adjacent à v1 (dernière position)
                cycle_vertices.append(shared_vertex_id)
            else:
                # Créer nouveau sommet
                angle = angle_0 - k * (2 * math.pi / n_sides)
                x = cx + R * math.cos(angle)
                y = cy + R * math.sin(angle)
                z = 0.0
                vid = self.graph.add_vertex('C', x, y, z)
                cycle_vertices.append(vid)
                self.placed_vertices[vid] = (x, y, z)
        
        # Créer les liaisons (éviter les doublons)
        n = len(cycle_vertices)
        for i in range(n):
            a = cycle_vertices[i]
            b = cycle_vertices[(i+1) % n]
            if a != b:
                # Vérifier si la liaison existe déjà
                exists = any(v == b for v, _ in self.graph.vertices[a].bonds)
                if not exists:
                    self.graph.add_bond(a, b, 1)
        
        # Ajouter le cycle au graphe
        self.graph.cycles.append(Cycle(vertices=cycle_vertices, size=n_sides))
        
        return cycle_vertices, (cx, cy)
    
    def build_from_sequence(self, central_size: int, sequence: Tuple[int, ...]) -> MolecularGraph:
        """
        Construit la géométrie complète avec gestion correcte de la coadjacence
        """
        # 1. Cycle central
        central_vertices = self.place_central_cycle(central_size)
        
        # 2. Dictionnaire pour stocker les infos de chaque cycle placé
        # position -> (centre, rayon, liste_vertices, external_vertex_id)
        placed_cycles = {}
        
        n_pos = len(sequence)
        
        # Premier passage : placer tous les cycles avec leurs centres
        for pos, size in enumerate(sequence):
            if size == 0:
                continue
            
            v1 = central_vertices[pos % central_size]
            v2 = central_vertices[(pos + 1) % central_size]
            
            # Vérifier si voisin précédent consécutif (coadjacence)
            prev_pos = (pos - 1) % n_pos
            shared_vertex = None

            if sequence[prev_pos] != 0 and prev_pos in placed_cycles:
                # Index 2 = vertex adjacent à v2_prev = v1_current = C_{pos}
                shared_vertex = placed_cycles[prev_pos]['vertices'][2]

            # Placer le cycle
            cycle_verts, center = self.place_cycle_with_shared_vertex(
                v1, v2, size, shared_vertex
            )
            
            placed_cycles[pos] = {
                'vertices': cycle_verts,
                'center': center,
                'size': size
            }
        
        # Gestion du wrap-around : pos=0 et pos=n_pos-1 sont consécutifs,
        # donc le sommet k=n_sides-1 du cycle[0] et le sommet k=2 du cycle[n_pos-1]
        # devraient être le même atome (adjacent à central_vertices[0]).
        # Ce cas ne se produit que quand toutes les positions sont remplies (cycle 6 complet).
        last_pos = n_pos - 1
        if (sequence[0] != 0 and sequence[last_pos] != 0
                and 0 in placed_cycles and last_pos in placed_cycles):
            # Le sommet partagé vu depuis pos=0 : dernier vertex du cycle[0] (adjacent à C0)
            keep_id = placed_cycles[0]['vertices'][-1]
            # Le sommet créé par le cycle[last_pos] adjacent à C0 : index 2 dans ce cycle
            remove_id = placed_cycles[last_pos]['vertices'][2]
            if keep_id != remove_id:
                # Mettre à jour la liste des vertices du dernier cycle
                placed_cycles[last_pos]['vertices'][2] = keep_id
                # Mettre à jour les cycles du graphe
                for cycle in self.graph.cycles:
                    cycle.vertices = [keep_id if v == remove_id else v
                                      for v in cycle.vertices]
                # Fusionner les deux sommets dans le graphe
                self._merge_vertices(keep_id, remove_id)

        return self.graph

    def _merge_vertices(self, keep_id: int, remove_id: int):
        """
        Fusionne remove_id dans keep_id :
        - Toutes les liaisons de remove_id sont redirigées vers keep_id
        - remove_id est supprimé du graphe
        - Les doublons de liaisons (keep_id déjà lié à un voisin) sont ignorés
        """
        remove_v = self.graph.vertices[remove_id]
        keep_v = self.graph.vertices[keep_id]

        for neighbor_id, order in list(remove_v.bonds):
            neighbor_v = self.graph.vertices[neighbor_id]
            # Supprimer la référence à remove_id chez le voisin
            neighbor_v.bonds = [(v, o) for v, o in neighbor_v.bonds if v != remove_id]
            # Ajouter la liaison vers keep_id si elle n'existe pas déjà
            if not any(v == keep_id for v, _ in neighbor_v.bonds):
                neighbor_v.bonds.append((keep_id, order))
                keep_v.bonds.append((neighbor_id, order))

        # Supprimer remove_id du graphe
        del self.graph.vertices[remove_id]
        if remove_id in self.placed_vertices:
            del self.placed_vertices[remove_id]