#!/usr/bin/env python3
"""Générateur principal de structures non-benzenoïdes"""

from pathlib import Path
from utils.symmetry import generate_canonical_sequences
from generators.builder import StructureBuilder
from config import NEIGHBOR_CONSTRAINTS

def main():
    output_dir = Path("output")
    builder = StructureBuilder()
    
    total = 0
    
    # Pour chaque taille de cycle central
    for size in [5, 6, 7]:
        constraints = NEIGHBOR_CONSTRAINTS[size]
        configs = generate_canonical_sequences(
            size, 
            constraints['n_positions'],
            constraints['max'],
            constraints['min']
        )
        
        print(f"Cycle {size}: {len(configs)} configurations canoniques")
        
        for central_size, seq in configs:
            result = builder.build(central_size, seq, output_dir)
            if result:
                total += 1
        
        print(f"  Générés: {len(list((output_dir/f'cycle{size}').glob('*.cml')))} fichiers")
    
    print(f"\nTotal général: {total} structures créées")

if __name__ == "__main__":
    main()