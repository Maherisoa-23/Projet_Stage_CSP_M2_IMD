"""Orchestrateur de construction : sequence -> fichier CML + XYZ"""

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
        Construit la structure et sauvegarde CML + XYZ.
        Retourne le chemin du fichier CML cree ou None si echec.
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
        cycle_dir = output_dir / f"cycle{central_size}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        cml_path = cycle_dir / f"{seq_str}.cml"
        comment = (f"cycle={central_size} sequence={seq_str} "
                   f"n_C={graph.count_carbons()}")
        CMLExporter.export(graph, str(cml_path), comment)

        # 4. Export XYZ (pour xTB)
        xyz_path = cycle_dir / f"{seq_str}.xyz"
        _export_xyz(graph, str(xyz_path))

        return cml_path


def _export_xyz(graph: MolecularGraph, filename: str):
    """Exporte le graphe au format XYZ standard."""
    atoms = sorted(graph.vertices.values(), key=lambda v: v.id)
    with open(filename, 'w') as f:
        f.write(f"{len(atoms)}\n")
        f.write("\n")
        for v in atoms:
            f.write(f"{v.element:<2s}  {v.x:14.5f}  {v.y:14.5f}  {v.z:14.5f}\n")
