"""
Orchestration du pipeline de reconstruction.

Fonctions publiques :
    reconstruct_molecule  — reconstruit une molecule a partir d'une solution CSP
    reconstruct_and_validate — reconstruit et valide toutes les solutions
"""

import shutil
from pathlib import Path
from itertools import product

from utils.parser import BenzenoidGraph
from utils.validate import validate_xyz
from reconstruction.topology import CycleTopology
from reconstruction.placement import CyclePlacer
from reconstruction.assembler import build_molecular_graph, export_xyz


def reconstruct_molecule(graph: BenzenoidGraph, solution: dict,
                         block_choices: dict = None):
    """Reconstruit la molecule 3D complete.

    Args:
        graph: BenzenoidGraph depuis parser.py
        solution: dict {v: taille}
        block_choices: dict {hex_idx: block_index} pour les hexagones multi-blocs

    Returns:
        MolecularGraph avec tous les atomes (C + H) et liaisons
    """
    topo = CycleTopology(graph, solution)
    topo.build(block_choices=block_choices)

    placer = CyclePlacer(graph, solution, topo.cycle_vertices)
    placer.build()

    mol = build_molecular_graph(topo, placer)
    return mol


def _enumerate_block_variants(graph: BenzenoidGraph, solution: dict) -> list:
    """Enumere toutes les combinaisons de blocs pour les hexagones multi-blocs.

    Retourne une liste de dicts {hex_idx: block_index}.
    Si aucun hexagone n'a de choix, retourne [{}] (une seule variante).
    """
    topo_probe = CycleTopology(graph, solution)
    multiblock = topo_probe.get_multiblock_hexagons()

    if not multiblock:
        return [{}]

    # Produit cartesien des choix de blocs
    hex_indices = [v_idx for v_idx, n_blocks in multiblock]
    block_ranges = [range(n_blocks) for _, n_blocks in multiblock]

    variants = []
    for combo in product(*block_ranges):
        choice = {hex_indices[i]: combo[i] for i in range(len(hex_indices))}
        variants.append(choice)

    return variants


MAX_VARIANTS = 50  # Limite pour eviter l'explosion combinatoire


def _run_single(graph, sol, i, threshold, opt_level, output_dir, sol_str):
    """Logique actuelle : 1 run par variante, on garde la meilleure variante."""
    variants = _enumerate_block_variants(graph, sol)
    n_variants = len(variants)
    if n_variants > MAX_VARIANTS:
        print(f"  {n_variants} variantes (limite a {MAX_VARIANTS})")
        variants = variants[:MAX_VARIANTS]
        n_variants = len(variants)
    if n_variants > 1:
        topo_probe = CycleTopology(graph, sol)
        multiblock = topo_probe.get_multiblock_hexagons()
        mb_str = ", ".join(f"v{v}({nb} blocs)" for v, nb in multiblock)
        print(f"  Multi-blocs : {mb_str} -> {n_variants} variantes")

    best_result = None
    best_angle = float('inf')
    sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))

    for vi, block_choices in enumerate(variants):
        variant_tag = f"_var{vi}" if n_variants > 1 else ""
        try:
            mol = reconstruct_molecule(graph, sol, block_choices)
        except Exception as e:
            msg = f"  Variante {vi+1}/{n_variants} : ERREUR — {e}" if n_variants > 1 else f"  ERREUR reconstruction : {e}"
            print(msg)
            continue

        xyz_path = output_dir / f"sol_{i}_{sizes_str}{variant_tag}.xyz"
        export_xyz(mol, str(xyz_path), comment=f"Solution {i}{variant_tag}: {sol_str}")
        result = validate_xyz(str(xyz_path), threshold=threshold, opt_level=opt_level)
        angle = result.get("angle_deg", 999)

        if n_variants > 1:
            status = "PLAN" if result.get('planar') else f"NON PLAN ({angle:.1f} deg)"
            bc_str = ", ".join(f"v{k}=bloc_{v}" for k, v in block_choices.items())
            print(f"  Variante {vi+1}/{n_variants} [{bc_str}] : {status}")

        if angle < best_angle:
            best_angle = angle
            best_result = result
            best_result["index"] = i
            best_result["solution"] = sol
            best_result["variant"] = vi
            best_result["block_choices"] = block_choices

    if best_result is None:
        return {"index": i, "planar": False, "message": "Toutes les variantes ont echoue"}
    if n_variants == 1:
        print(f"  XYZ genere : sol_{i}_{sizes_str}.xyz")
        print(f"  Resultat : {best_result['message']}")
    else:
        print(f"  -> Meilleure variante : {best_result['variant']+1} "
              f"({best_result.get('angle_deg', 0):.1f} deg)")
    return best_result


def _run_multi(graph, sol, i, threshold, opt_level, output_dir, sol_str, n_runs):
    """N runs xTB sur la variante 0, stockes dans solutions/sol_X_sizes/run_NN_opt.xyz.
    Les stats/classification sont calculees par aggregate_runs.py.
    """
    sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))
    sol_dir = output_dir / f"sol_{i}_{sizes_str}"
    sol_dir.mkdir(parents=True, exist_ok=True)

    # Reconstruction unique (variante 0)
    try:
        mol = reconstruct_molecule(graph, sol, None)
    except Exception as e:
        print(f"  ERREUR reconstruction : {e}")
        return {"index": i, "planar": False, "message": f"Reconstruction echouee: {e}"}

    source_path = sol_dir / "source.xyz"
    export_xyz(mol, str(source_path), comment=f"Solution {i}: {sol_str}")
    print(f"  source: {source_path.relative_to(output_dir)}")

    # N runs avec seeds deterministes
    last_result = None
    n_ok = 0
    for run_id in range(1, n_runs + 1):
        seed = hash(("sol", i, run_id)) & 0xFFFFFFFF
        opt_path = sol_dir / f"run_{run_id:02d}_opt.xyz"
        try:
            result = validate_xyz(str(source_path), opt_path=str(opt_path),
                                  threshold=threshold, opt_level=opt_level, seed=seed)
            if result.get("optimized"):
                n_ok += 1
                last_result = result
                status = "PLAN" if result.get('planar') else f"NON PLAN ({result.get('angle_deg', 0):.1f}°)"
                print(f"  run {run_id:02d}/{n_runs}: {status}")
            else:
                print(f"  run {run_id:02d}/{n_runs}: ECHEC xTB")
        except Exception as e:
            print(f"  run {run_id:02d}/{n_runs}: EXCEPTION {e}")

    print(f"  -> {n_ok}/{n_runs} runs reussis")

    if last_result is None:
        return {"index": i, "planar": False, "message": "Tous les runs ont echoue"}
    last_result["index"] = i
    last_result["solution"] = sol
    return last_result


def reconstruct_and_validate(graph: BenzenoidGraph, solutions: list,
                             threshold=10.0, opt_level="tight",
                             output_dir=None, n_runs=1, method="multi-runs"):
    """Pour chaque solution CSP, reconstruit la molecule et la valide.

    La validation est deleguee a une 'strategy' selectionnee par le parametre
    `method`. Les strategies sont definies dans utils.validation. Chaque
    strategy a sa propre logique (multi-runs xTB, MD/MTD, ...) et produit son
    propre format de sortie dans data.json (cf. blocs 'runs', 'md_validation').

    Strategies disponibles :
      - "multi-runs" (defaut) : comportement historique. Si n_runs=1, single-run
        avec selection de la meilleure variante multi-blocs ; si n_runs>1,
        structure sol_X/run_NN_opt.xyz avec stats calculees par aggregate_runs.py.
      - autres strategies a venir : voir utils.validation.list_strategies().
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "output" / "molecules"
        if output_dir.exists():
            for f in output_dir.iterdir():
                try:
                    if f.is_file():
                        f.unlink()
                except OSError:
                    pass
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("xtb"):
        print("ERREUR : xtb non trouve dans le PATH.")
        return

    # Selection de la strategy. Pour "multi-runs", on propage n_runs ;
    # d'autres strategies prendront leurs propres parametres (ex. md_time,
    # md_temp pour la methode MD a venir).
    from utils.validation import get_strategy
    strategy_kwargs = {"threshold": threshold, "opt_level": opt_level}
    if method == "multi-runs":
        strategy_kwargs["n_runs"] = n_runs
    strategy = get_strategy(method, **strategy_kwargs)

    results = strategy.validate_solutions(graph, solutions, output_dir)

    n_valid = sum(1 for r in results if r.get("planar", False))
    n_invalid = sum(1 for r in results if not r.get("planar", False))
    print(f"\n=== Resume validation globale ===")
    print(f"Methode           : {method}")
    print(f"Solutions testees : {len(results)}")
    print(f"Planes (valides)  : {n_valid}")
    print(f"Non planes        : {n_invalid}")
    return results
