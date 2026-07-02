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


def _run_md(graph, sol, i, threshold, opt_level, output_dir, sol_str,
            md_params=None, deterministic=True, cache_db_path=None):
    """1 run protocole MD + opt finale (Yannick Carissan).

    Reconstruit la molecule (variante 0), ecrit source.xyz, puis lance
    optimizer_md.md_then_optimize qui :
      1. xtb --md --input md.inp  -> xtb.trj
      2. extraction de la derniere frame
      3. xtb --opt sur la frame   -> md_final_opt.xyz

    Sortie dans output_dir/sol_X_sizes/md_validation/ :
        md.inp, md_traj.xyz, md_geom.xyz, md_final_opt.xyz

    Le test de planarite est fait sur md_final_opt.xyz.
    Si deterministic=True (defaut), xTB tourne en single-thread pour
    reproductibilite parfaite entre runs.

    Si cache_db_path est fourni, cherche d'abord un resultat deja calcule
    pour ce source.xyz + ces parametres (cf. csp_solver/xtb/cache.py) :
    la reconstruction 3D et le protocole det-opt sont tous deux
    byte-deterministes, donc deux solutions identiques (meme graphe +
    meme substitution) produisent le meme source.xyz et sont garanties
    de donner le meme resultat xTB. En cas de hit, on ecrit directement
    md_final_opt.xyz depuis le cache et on saute l'appel xTB (le plus
    couteux du pipeline). En cas de miss, le calcul est lance normalement
    puis le resultat est stocke pour les prochains hits.
    """
    sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))
    sol_dir = output_dir / f"sol_{i}_{sizes_str}"
    sol_dir.mkdir(parents=True, exist_ok=True)

    # Reconstruction unique (variante 0, comme multi-runs)
    try:
        mol = reconstruct_molecule(graph, sol, None)
    except Exception as e:
        print(f"  ERREUR reconstruction : {e}")
        return {"index": i, "planar": False, "message": f"Reconstruction echouee: {e}"}

    source_path = sol_dir / "source.xyz"
    export_xyz(mol, str(source_path), comment=f"Solution {i}: {sol_str}")

    # MD + opt protocole (artefacts dans md_validation/)
    md_dir = sol_dir / "md_validation"

    # Import local pour eviter de charger optimizer_md si la strategy
    # MD n'est pas utilisee. DEFAULT_PERTURB_PARAMS vient de det_opt.py
    # directement : le shim retro-compat xtb/md.py ne le re-exporte pas.
    from csp_solver.xtb.md import md_then_optimize
    from csp_solver.xtb.det_opt import DEFAULT_PERTURB_PARAMS

    cache_key = None
    cached = None
    if cache_db_path:
        from csp_solver.xtb import cache as xtb_cache
        perturb_params = dict(DEFAULT_PERTURB_PARAMS)
        if md_params:
            perturb_params.update({k: v for k, v in md_params.items()
                                   if k in ("amplitude", "phase", "mode", "seed")})
        source_text = source_path.read_text(encoding="utf-8")
        cache_key = xtb_cache.compute_cache_key(source_text, opt_level, perturb_params)
        try:
            cached = xtb_cache.lookup(cache_db_path, cache_key)
        except Exception:
            cached = None  # cache indisponible (DB verrouillee, etc.) : on retombe sur xTB

    if cached is not None:
        md_dir.mkdir(parents=True, exist_ok=True)
        final_path = md_dir / "md_final_opt.xyz"
        final_path.write_text(cached["xyz_text"], encoding="utf-8")
        success = True
        final_xyz = final_path
        info = {
            "method": "det-opt",
            "params": {},
            "deterministic": deterministic,
            "converged": cached["converged"],
            "trajectory_file": None,
            "final_opt_file": final_path.name,
            "message": "Resultat repris du cache (solution identique deja calculee)",
            "attempts": [],
            "n_attempts": 0,
            "n_frames": 2,
            "expected_frames": 2,
            "from_cache": True,
        }
        print(f"  Cache HIT : resultat xTB repris (source.xyz identique)")
    else:
        success, final_xyz, info = md_then_optimize(
            str(source_path), str(md_dir),
            params=md_params, opt_level=opt_level,
            deterministic=deterministic,
        )
        info["from_cache"] = False

    # Persistance des metadonnees du run MD (retries, frames, etc.) dans
    # md_validation/md_meta.json. aggregate_md.py les relit pour les
    # surfacer dans data.json (cles 'n_attempts', 'attempts', 'n_frames').
    # Sans ce fichier, ces infos seraient perdues entre _run_md et l'agregateur.
    import json as _json
    md_dir.mkdir(parents=True, exist_ok=True)
    meta_path = md_dir / "md_meta.json"
    try:
        meta = {
            "success": bool(success),
            "n_attempts": info.get("n_attempts"),
            "attempts": info.get("attempts", []),
            "n_frames": info.get("n_frames"),
            "expected_frames": info.get("expected_frames"),
            "ejection_threshold": info.get("ejection_threshold"),
            "converged": info.get("converged"),
            "deterministic": info.get("deterministic"),
            "message": info.get("message", ""),
            "from_cache": info.get("from_cache", False),
        }
        meta_path.write_text(_json.dumps(meta, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    except OSError:
        pass

    if not success:
        n_att = info.get("n_attempts", "?")
        print(f"  ECHEC MD apres {n_att} tentatives : {info.get('message', '?')}")
        for err in info.get("attempts", [])[-3:]:
            print(f"    - {err}")
        return {
            "index": i, "solution": sol,
            "planar": False, "angle_deg": 0.0,
            "message": f"MD failed: {info.get('message', '?')}",
            "md_info": info,
        }

    # Test planarite sur md_final_opt.xyz
    from utils.validate import test_planarity_from_xyz
    plan = test_planarity_from_xyz(str(final_xyz), threshold)

    status = "PLAN" if plan["planar"] else f"NON PLAN ({plan['angle_deg']:.1f} deg)"
    n_att = info.get("n_attempts", 1)
    retry_note = f" [{n_att} tentatives]" if n_att and n_att > 1 else ""
    print(f"  MD + opt : {status} {'(converge)' if info['converged'] else '(non converge)'}{retry_note}")

    # Alimente le cache seulement pour un calcul frais (pas la peine de
    # re-stocker un hit) : angle + XYZ optimise, associes a cache_key.
    if not info.get("from_cache") and cache_db_path and cache_key:
        try:
            from csp_solver.xtb import cache as xtb_cache
            xtb_cache.store(
                cache_db_path, cache_key,
                Path(final_xyz).read_text(encoding="utf-8"),
                angle_deg=plan["angle_deg"],
                converged=info.get("converged", False),
                source_sol_name=sol_dir.name,
                opt_level=opt_level,
            )
        except Exception:
            pass  # le cache est une acceleration best-effort, jamais bloquant

    return {
        "index": i,
        "solution": sol,
        "planar": plan["planar"],
        "angle_deg": plan["angle_deg"],
        "rmsd": plan["rmsd"],
        "height": plan["height"],
        "message": status,
        "md_info": info,
    }


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
                             output_dir=None, n_runs=1, method="md",
                             md_params=None, md_deterministic=True,
                             cache_db_path=None):
    """Pour chaque solution CSP, reconstruit la molecule et la valide.

    La validation est deleguee a une 'strategy' selectionnee par le parametre
    `method`. Les strategies sont definies dans utils.validation. Chaque
    strategy a sa propre logique (multi-runs xTB, MD courte + opt, ...) et
    produit son propre format de sortie dans data.json (blocs 'runs',
    'md_validation', ...).

    Strategies disponibles :
      - "md" (defaut depuis mai 2026) : 1 run protocole MD (~1 ps a 298 K)
        + opt finale. Sortie dans sol_X/md_validation/. Stats agregees par
        aggregate_md.py.
      - "multi-runs" : comportement historique. Si n_runs=1, single-run
        avec selection de la meilleure variante multi-blocs ; si n_runs>1,
        structure sol_X/run_NN_opt.xyz avec stats calculees par aggregate_runs.py.
      - autres a venir : voir utils.validation.list_strategies().

    cache_db_path : si fourni (et method="md"), active le cache xTB
        (cf. csp_solver/xtb/cache.py) -- evite de relancer xTB pour une
        solution deja calculee (meme source.xyz + memes parametres).
        Ignore pour les autres strategies.
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
    elif method == "md":
        if md_params is not None:
            strategy_kwargs["md_params"] = md_params
        strategy_kwargs["deterministic"] = md_deterministic
        if cache_db_path is not None:
            strategy_kwargs["cache_db_path"] = cache_db_path
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
