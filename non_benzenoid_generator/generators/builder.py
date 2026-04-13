"""Orchestrateur de construction : séquence → fichier CML"""

from pathlib import Path
from typing import Optional
from core.topology import MolecularGraph
from core.geometry import GeometryEngine
from core.valence_solver import ValenceSolver
from utils.exporters import CMLExporter
from config import NEIGHBOR_CONSTRAINTS

class StructureBuilder:
    """Construit une structure complète à partir d'une séquence"""
    
    def __init__(self):
        pass
    
    def build(self, central_size: int, sequence: tuple, 
             output_dir: Path = Path("output")) -> Optional[Path]:
        """
        Construit la structure complète et sauvegarde
        Retourne le chemin du fichier créé ou None si échec
        """
        # Créer le graphe et la géométrie
        graph = MolecularGraph()
        engine = GeometryEngine(graph)
        
        # 1. Construction topologique et géométrique
        engine.build_from_sequence(central_size, sequence)
        
        # 2. Résolution des valences (doubles liaisons, H)
        solver = ValenceSolver(graph)
        if not solver.solve():
            print(f"Échec résolution valences pour {central_size}_{sequence}")
            return None
        
        # 3. Export CML
        output_path = output_dir / f"cycle{central_size}" / f"{'_'.join(map(str, sequence))}.cml"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        comment = f"cycle={central_size} sequence={'_'.join(map(str, sequence))} n_C={graph.count_carbons()}"
        CMLExporter.export(graph, str(output_path), comment)
        
        return output_path