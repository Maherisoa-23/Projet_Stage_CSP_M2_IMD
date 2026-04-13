"""Configuration globale pour le générateur de structures non-benzenoïdes"""

# Géométrie
BOND_LENGTH_CC_SINGLE = 1.42  # Å
BOND_LENGTH_CC_DOUBLE = 1.34  # Å  
BOND_LENGTH_CH = 1.08         # Å

# Angles tétraédriques (pour placement des H)
TETRAHEDRAL_ANGLE = 109.5  # degrés

# Cycles supportés
VALID_CYCLE_SIZES = [5, 6, 7]

# Contraintes de voisinage par taille de cycle central
NEIGHBOR_CONSTRAINTS = {
    5: {'min': 2, 'max': 4, 'n_positions': 5},
    6: {'min': 2, 'max': 6, 'n_positions': 6},
    7: {'min': 2, 'max': 5, 'n_positions': 7}  # 7 positions, max 5 voisins
}

# Valeurs possibles pour les voisins (0=vide, 5/6/7=taille)
NEIGHBOR_VALUES = [0, 5, 6, 7]

# Seuils pour validation
MAX_DEVIATION_PLANARITY = 0.1  # Å (écart RMS max pour considérer planaire)