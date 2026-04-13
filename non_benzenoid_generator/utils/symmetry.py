"""Gestion des symétries (groupe diédral) pour réduction des configurations"""

from typing import Tuple, List

def get_dihedral_transforms(seq: Tuple) -> List[Tuple]:
    """Génère toutes les transformations du groupe diédral D_n"""
    n = len(seq)
    transforms = []
    
    # Rotations
    for k in range(n):
        rot = tuple(seq[(i + k) % n] for i in range(n))
        transforms.append(rot)
    
    # Réflexions (miroirs)
    for k in range(n):
        ref = tuple(seq[(k - i) % n] for i in range(n))
        transforms.append(ref)
    
    return transforms

def canonical_form(seq: Tuple) -> Tuple:
    """
    Retourne la forme canonique :
    - Zéros regroupés à droite (si possible)
    - Maximisation lexicographique parmi les rotations/réflexions valides
    """
    transforms = get_dihedral_transforms(seq)
    
    best = None
    
    for candidate in transforms:
        # Vérifier si les zéros sont consécutifs à la fin
        try:
            first_zero = candidate.index(0)
        except ValueError:
            first_zero = len(candidate)
        
        # Vérifier que tous les éléments à partir du premier zéro sont des zéros
        is_valid = all(candidate[i] == 0 for i in range(first_zero, len(candidate)))
        
        if is_valid:
            if best is None or candidate > best:  # Ordre lexicographique décroissant
                best = candidate
    
    # Fallback : si aucun candidat n'a les zéros à droite, prendre le max lexico
    if best is None:
        best = max(transforms)
    
    return best

def generate_canonical_sequences(central_size: int, n_positions: int, 
                                max_neighbors: int, min_neighbors: int = 2) -> set:
    """Génère toutes les séquences canoniques pour un cycle central donné"""
    from itertools import product
    from config import NEIGHBOR_VALUES
    
    sequences = set()
    
    for seq in product(NEIGHBOR_VALUES, repeat=n_positions):
        # Compter voisins (non-nuls)
        neighbors = [s for s in seq if s != 0]
        k = len(neighbors)
        
        if k < min_neighbors or k > max_neighbors:
            continue
        
        # Exclure benzenoïde pur pour cycle 6
        if central_size == 6 and all(s == 6 or s == 0 for s in seq):
            continue
        
        # Forme canonique
        canon = canonical_form(seq)
        sequences.add((central_size, canon))
    
    return sorted(sequences)