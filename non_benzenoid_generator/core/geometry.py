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
                                      shared_vertex_id: Optional[int] = None,
                                      prev_cycle_center: Optional[Tuple[float, float]] = None,
                                      prev_cycle_size: Optional[int] = None) -> Tuple[List[int], Tuple[float, float]]:
        """
        Place un cycle avec éventuellement un sommet déjà existant (partagé avec le voisin précédent)
        
        Si shared_vertex_id est fourni, ce sommet est utilisé comme 3ème sommet du cycle.
        Sinon, crée un nouveau sommet à la position calculée.
        
        Retourne: (liste des IDs du cycle, centre du cycle)
        """
        # Centre de ce cycle
        cx, cy = self.compute_cycle_center(v1_id, v2_id, n_sides)
        R = radius_from_side(n_sides)
        
        # Si on a un sommet partagé et le centre du cycle précédent,
        # on doit vérifier que ce sommet est bien à l'intersection des deux cercles
        if shared_vertex_id is not None and prev_cycle_center is not None:
            # Calculer les intersections des deux cercles circonscrits
            r_prev = radius_from_side(prev_cycle_size) if prev_cycle_size is not None else R
            intersections = circle_intersections(
                prev_cycle_center, r_prev,
                (cx, cy), R
            )

            # Les deux intersections sont v1 (C_{pos}) et le sommet externe A.
            # On exclut v1 pour obtenir A.
            v1_ref = self.graph.vertices[v1_id]
            shared_pos = None

            for ix, iy in intersections:
                dist_to_v1 = math.sqrt((ix - v1_ref.x)**2 + (iy - v1_ref.y)**2)
                if dist_to_v1 > 0.5:  # C'est le sommet externe A
                    shared_pos = (ix, iy)
                    sv = self.graph.vertices[shared_vertex_id]
                    sv.x = ix
                    sv.y = iy
                    self.placed_vertices[shared_vertex_id] = (ix, iy, 0.0)
                    break
        
        # Construire les sommets du cycle
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
            
            # Vérifier si voisin précédent consécutif
            prev_pos = (pos - 1) % n_pos
            shared_vertex = None
            prev_center = None
            prev_size = None

            if sequence[prev_pos] != 0 and prev_pos in placed_cycles:
                # Le sommet partagé est à l'index 2 du cycle précédent :
                # c'est le vertex adjacent à v2_prev = v1_current = C_{pos}
                prev_data = placed_cycles[prev_pos]
                shared_vertex = prev_data['vertices'][2]
                prev_center = prev_data['center']
                prev_size = prev_data['size']

            # Placer le cycle
            cycle_verts, center = self.place_cycle_with_shared_vertex(
                v1, v2, size, shared_vertex, prev_center, prev_size
            )
            
            placed_cycles[pos] = {
                'vertices': cycle_verts,
                'center': center,
                'size': size
            }
        
        return self.graph