"""
Test rapide : reconstruit un benzenoide (tout hexagonal) depuis un .graph
et verifie sa planarite avec xTB.

Usage:
    python test.py data/second.graph
"""

import sys
import math
import shutil
import importlib.util
from pathlib import Path

# --- Imports du generateur ---
_gen_root = Path(__file__).parent.parent / "non_benzenoid_generator"
_gen_str = str(_gen_root)
if _gen_str not in sys.path:
    sys.path.insert(0, _gen_str)

from core.topology import MolecularGraph
from core.valence_solver import ValenceSolver
from core.optimizer import optimize_xtb, read_optimized_coords

# planarity via importlib (evite conflit avec utils/ local)
_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_gen_root / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar

# --- Import du parser ---
sys.path.insert(0, str(Path(__file__).parent))
from utils.parser import parse

# --- Coordonnees hexagonales -> cartesiennes ---
BOND_CC = 1.42

def hex_to_cartesian(label):
    parts = label.split("_")
    hx, hy = int(parts[0]), int(parts[1])
    x = BOND_CC * (hx + hy * 0.5)
    y = BOND_CC * (hy * math.sqrt(3) / 2)
    return x, y, 0.0


def build_benzenoid_xyz(graph, output_path):
    """Construit le XYZ du benzenoide original (tout hexagonal)."""
    mol = MolecularGraph()
    label_to_id = {}

    # Carbones
    all_labels = set()
    for hex_verts in graph.hexagons:
        for label in hex_verts:
            all_labels.add(label)

    for label in all_labels:
        x, y, z = hex_to_cartesian(label)
        vid = mol.add_vertex("C", x, y, z)
        label_to_id[label] = vid

    # Liaisons C-C
    for s1, s2 in graph.edges:
        if s1 in label_to_id and s2 in label_to_id:
            mol.add_bond(label_to_id[s1], label_to_id[s2], order=1)

    # Hydrogenes
    solver = ValenceSolver(mol)
    solver.solve()

    # Export XYZ
    atoms = sorted(mol.vertices.values(), key=lambda v: v.id)
    with open(output_path, 'w') as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"Benzenoide original (tout hexagonal)\n")
        for a in atoms:
            f.write(f"{a.element:<2s}  {a.x:14.5f}  {a.y:14.5f}  {a.z:14.5f}\n")

    print(f"  XYZ genere : {output_path}")
    print(f"  Atomes : {len(atoms)} ({sum(1 for a in atoms if a.element=='C')} C, "
          f"{sum(1 for a in atoms if a.element=='H')} H)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test.py data/fichier.graph")
        sys.exit(1)

    filepath = sys.argv[1]
    output_dir = Path(__file__).parent / "output" / "test"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse
    print(f"=== Lecture de {filepath} ===")
    graph = parse(filepath)
    print(f"  {graph.h} hexagones, {len(graph.vertices)} carbones, {len(graph.edges)} liaisons")

    # Construire le XYZ
    name = Path(filepath).stem
    xyz_path = output_dir / f"{name}_original.xyz"
    print(f"\n=== Construction du benzenoide ===")
    build_benzenoid_xyz(graph, str(xyz_path))

    # xTB
    if not shutil.which("xtb"):
        print("\nERREUR : xtb non trouve dans le PATH.")
        sys.exit(1)

    opt_path = output_dir / f"{name}_original_opt.xyz"
    print(f"\n=== Optimisation xTB ===")
    success, msg = optimize_xtb(str(xyz_path), str(opt_path), opt_level="tight")
    if not success:
        print(f"  ECHEC : {msg}")
        sys.exit(1)
    print(f"  {msg}")

    # Planarite
    print(f"\n=== Test de planarite ===")
    coords = read_optimized_coords(str(opt_path))
    metrics = compute_planarity(coords)
    planar = is_planar(metrics, 10.0)

    print(f"  Angle max    : {metrics['max_angle_deg']:.2f} deg")
    print(f"  RMSD plan    : {metrics['rmsd_plane']:.4f} A")
    print(f"  Hauteur      : {metrics['height']:.4f} A")
    print(f"  Resultat     : {'PLAN' if planar else 'NON PLAN'}")


if __name__ == "__main__":
    main()
