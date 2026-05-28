"""
Test rapide : reconstruit un benzenoide (tout hexagonal) depuis un .graph
et verifie sa planarite avec xTB.

Utilise le meme pipeline de reconstruction que main.py (reconstruct_molecule)
avec la solution {v: 6 pour tout v}, pour garantir des resultats comparables.

Usage:
    python test.py data/second.graph
"""

import sys
import shutil
import importlib.util
from pathlib import Path

# --- Imports du generateur ---
_gen_root = Path(__file__).parent.parent / "non_benzenoid_generator"
_gen_str = str(_gen_root)
if _gen_str not in sys.path:
    sys.path.insert(0, _gen_str)

from csp_solver.xtb.optimizer import optimize_xtb, read_optimized_coords

# planarity via importlib (evite conflit avec utils/ local)
_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_gen_root / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar

# --- Import du parser et du pipeline de reconstruction ---
sys.path.insert(0, str(Path(__file__).parent))
from utils.parser import parse
from reconstruction.pipeline import reconstruct_molecule
from reconstruction.assembler import export_xyz

# Re-prioriser non_benzenoid_generator dans sys.path : valence_solver.py fait
# `from config import BOND_LENGTH_CH` (import tardif) et on ne veut pas tomber
# sur csp_solver/config.py qui n'a pas cette constante.
if _gen_str in sys.path:
    sys.path.remove(_gen_str)
sys.path.insert(0, _gen_str)


def main():
    if len(sys.argv) < 2:
        print("Usage: python test.py data/fichier.graph")
        sys.exit(1)

    filepath = sys.argv[1]
    if "--output-dir" in sys.argv:
        idx = sys.argv.index("--output-dir")
        output_dir = Path(sys.argv[idx + 1])
    else:
        output_dir = Path(__file__).parent / "output" / "test"
    output_dir.mkdir(parents=True, exist_ok=True)

    n_runs = 1
    if "--n-runs" in sys.argv:
        idx = sys.argv.index("--n-runs")
        try:
            n_runs = max(1, int(sys.argv[idx + 1]))
        except (ValueError, IndexError):
            n_runs = 1

    # Parse
    print(f"=== Lecture de {filepath} ===")
    graph = parse(filepath)
    print(f"  {graph.h} hexagones, {len(graph.vertices)} carbones, {len(graph.edges)} liaisons")

    # Construire le XYZ via le pipeline de reconstruction (solution tout-6)
    name = Path(filepath).stem
    print(f"\n=== Construction du benzenoide (reconstruction, tout hexagonal) ===")
    solution_all_6 = {v: 6 for v in range(graph.h)}
    mol = reconstruct_molecule(graph, solution_all_6)
    atoms = sorted(mol.vertices.values(), key=lambda v: v.id)
    print(f"  Atomes : {len(atoms)} ({sum(1 for a in atoms if a.element=='C')} C, "
          f"{sum(1 for a in atoms if a.element=='H')} H)")

    # xTB
    if not shutil.which("xtb"):
        print("\nERREUR : xtb non trouve dans le PATH.")
        sys.exit(1)

    if n_runs == 1:
        # Mode single-run : structure plate (compatible view.py classique)
        xyz_path = output_dir / f"{name}_original.xyz"
        export_xyz(mol, str(xyz_path), comment="Benzenoide original (tout hexagonal)")
        print(f"  XYZ genere : {xyz_path}")

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
    else:
        # Mode multi-runs : sous-dossier + N runs avec seeds
        sol_dir = output_dir / f"{name}_original"
        sol_dir.mkdir(parents=True, exist_ok=True)
        source_path = sol_dir / "source.xyz"
        export_xyz(mol, str(source_path), comment="Benzenoide original (tout hexagonal)")
        print(f"  source: {source_path}")

        print(f"\n=== Optimisation xTB x{n_runs} ===")
        n_ok = 0
        for run_id in range(1, n_runs + 1):
            seed = hash(("original", name, run_id)) & 0xFFFFFFFF
            opt_path = sol_dir / f"run_{run_id:02d}_opt.xyz"
            success, msg = optimize_xtb(str(source_path), str(opt_path),
                                        opt_level="tight", seed=seed)
            if not success:
                print(f"  run {run_id:02d}/{n_runs}: ECHEC ({msg})")
                continue
            coords = read_optimized_coords(str(opt_path))
            metrics = compute_planarity(coords)
            planar = is_planar(metrics, 10.0)
            status = "PLAN" if planar else f"NON PLAN ({metrics['max_angle_deg']:.1f}°)"
            print(f"  run {run_id:02d}/{n_runs}: {status}")
            n_ok += 1
        print(f"\n  → {n_ok}/{n_runs} runs reussis")


if __name__ == "__main__":
    main()
