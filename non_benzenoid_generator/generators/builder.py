"""Orchestrateur de construction : sequence -> fichier CML"""

from pathlib import Path
from typing import Optional
from core.topology import MolecularGraph
from core.geometry import GeometryEngine
from core.valence_solver import ValenceSolver
from utils.exporters import CMLExporter


class StructureBuilder:
    """Construit une structure complete a partir d'une sequence"""

    def build(self, central_size: int, sequence: tuple,
              output_dir: Path = Path("output")) -> Optional[Path]:
        """
        Construit la structure et sauvegarde le fichier CML.
        Retourne le chemin du fichier cree ou None si echec.
        """
        # 1. Construction topologique et geometrique
        graph = MolecularGraph()
        engine = GeometryEngine(graph)
        engine.build_from_sequence(central_size, sequence)

        # 2. Resolution des valences (doubles liaisons + H)
        solver = ValenceSolver(graph)
        if not solver.solve():
            print(f"Echec resolution valences pour {central_size}_{sequence}")
            return None

        # 3. Export CML
        seq_str = '_'.join(map(str, sequence))
        output_path = output_dir / f"cycle{central_size}" / f"{seq_str}.cml"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        comment = (f"cycle={central_size} sequence={seq_str} "
                   f"n_C={graph.count_carbons()}")
        CMLExporter.export(graph, str(output_path), comment)

        return output_path
