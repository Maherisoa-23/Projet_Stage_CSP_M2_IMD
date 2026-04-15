"""
Orchestration du pipeline de reconstruction.

Fonctions publiques :
    reconstruct_molecule  — reconstruit une molecule a partir d'une solution CSP
    reconstruct_and_validate — reconstruit et valide toutes les solutions
"""

import shutil
from pathlib import Path

from utils.parser import BenzenoidGraph
from utils.validate import validate_xyz
from reconstruction.topology import CycleTopology
from reconstruction.placement import CyclePlacer
from reconstruction.assembler import build_molecular_graph, export_xyz


def reconstruct_molecule(graph: BenzenoidGraph, solution: dict):
    """Reconstruit la molecule 3D complete a partir du benzenoide et d'une solution CSP.

    Pipeline :
        1. Phase A — Topologie : modifier les cycles (pentagone/heptagone)
        2. Phase B — Geometrie : placer les cycles en BFS comme polygones reguliers
        3. Phase C — Assemblage : construire le MolecularGraph + ValenceSolver

    Args:
        graph: BenzenoidGraph depuis parser.py
        solution: dict {v: taille} depuis le solveur CSP

    Returns:
        MolecularGraph avec tous les atomes (C + H) et liaisons
    """
    # Phase A : topologie
    topo = CycleTopology(graph, solution)
    topo.build()

    # Phase B : geometrie
    placer = CyclePlacer(graph, solution, topo.cycle_vertices)
    placer.build()

    # Phase C : assemblage
    mol = build_molecular_graph(topo, placer)

    return mol


def reconstruct_and_validate(graph: BenzenoidGraph, solutions: list,
                             threshold=10.0, opt_level="tight"):
    """Pour chaque solution CSP, reconstruit la molecule et la valide.

    Args:
        graph: BenzenoidGraph
        solutions: liste de dicts {v: taille}
        threshold: seuil de planarite en degres
        opt_level: niveau de convergence xTB
    """
    output_dir = Path(__file__).parent.parent / "output" / "molecules"

    # Nettoyer les anciens fichiers (rmtree peut echouer sur Windows
    # si le dossier est verrouille par l'Explorateur ou un autre processus)
    if output_dir.exists():
        for f in output_dir.iterdir():
            try:
                if f.is_file():
                    f.unlink()
            except OSError:
                pass
    output_dir.mkdir(parents=True, exist_ok=True)

    # Verifier xtb
    if not shutil.which("xtb"):
        print("ERREUR : xtb non trouve dans le PATH.")
        return

    results = []

    for i, sol in enumerate(solutions, 1):
        sol_str = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
        substituted = [v for v in sorted(sol.keys()) if sol[v] != 6]

        print(f"\n--- Solution {i}/{len(solutions)} : {sol_str} ---")

        if not substituted:
            print("  Tous hexagones, pas de reconstruction necessaire.")
            results.append({"index": i, "planar": True,
                            "message": "Tout hexagonal"})
            continue

        # Reconstruction
        try:
            mol = reconstruct_molecule(graph, sol)
        except Exception as e:
            print(f"  ERREUR reconstruction : {e}")
            results.append({"index": i, "planar": False,
                            "message": f"Erreur: {e}"})
            continue

        # Export XYZ
        sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))
        xyz_path = output_dir / f"sol_{i}_{sizes_str}.xyz"
        export_xyz(mol, str(xyz_path),
                   comment=f"Solution {i}: {sol_str}")
        print(f"  XYZ genere : {xyz_path.name}")

        # Validation xTB + planarite
        result = validate_xyz(str(xyz_path), threshold=threshold,
                              opt_level=opt_level)
        print(f"  Resultat : {result['message']}")
        if result.get("angle_deg", 0) > 0:
            print(f"  Angle max : {result['angle_deg']:.2f} deg")

        result["index"] = i
        result["solution"] = sol
        results.append(result)

    # Resume
    n_valid = sum(1 for r in results if r.get("planar", False))
    n_invalid = sum(1 for r in results if not r.get("planar", False))
    print(f"\n=== Resume validation globale ===")
    print(f"Solutions testees : {len(results)}")
    print(f"Planes (valides)  : {n_valid}")
    print(f"Non planes        : {n_invalid}")

    return results
