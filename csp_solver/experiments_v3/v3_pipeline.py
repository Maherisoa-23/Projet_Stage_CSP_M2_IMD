"""Pipeline POST-CSP de experiments_v3.

Remplace reconstruction.pipeline.reconstruct_and_validate par une variante
qui intercale un filtre MMFF 3-tier entre la reconstruction et xTB.

Pour chaque solution CSP :
  1. Reconstruction 3D -> source.xyz (variante 0)
  2. MMFF sur source.xyz -> mmff_opt.xyz + mmff_meta.json (angle, decision)
  3. Decision selon mmff_angle :
       angle < th_sure_plan  -> "mmff_sure_plan"
            on accepte sans xTB. mmff_opt.xyz devient le xyz de reference.
       angle > th_sure_non_plan -> "mmff_sure_non_plan"
            on rejette. PAS d'xTB. Une trace minimale est ecrite pour audit.
       sinon -> "mmff_gray"
            xTB MD + opt comme v2 (md_final_opt.xyz). Verdict xTB final.
  4. Si MMFF echoue (typage impossible, etc) -> fallback "mmff_failed" :
     on tombe en mode v2 (xTB sur source.xyz) pour ne rien perdre.

Sortie scratch (compatible db_helpers_v3.ingest_mol_dir) :
  sol_X_sizes/
      source.xyz
      mmff_validation/
          mmff_opt.xyz       (si MMFF a tourne)
          mmff_meta.json     (angle, decision_path, ok)
      md_validation/         (uniquement pour gray ou mmff_failed)
          md_final_opt.xyz   (xTB output, comme v2)
          md_meta.json
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Optional

from csp_solver.experiments_v3.mmff_oracle import (
    mmff_planarity, mmff_planarity_with_coords,
)


# Constantes par defaut (alignees sur validation B)
DEFAULT_TH_SURE_PLAN = 5.0     # degres
DEFAULT_TH_SURE_NON_PLAN = 25.0  # degres
DEFAULT_TH_XTB = 10.0           # seuil planarite final (xTB)
DEFAULT_OPT_LEVEL = "tight"


def _write_mmff_meta(mmff_dir: Path, decision: str, mmff_result: dict | None,
                      threshold_xtb: float) -> None:
    mmff_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "decision_path": decision,
        "mmff_ok": mmff_result is not None,
        "mmff_angle_deg": (mmff_result["angle_deg"] if mmff_result else None),
        "mmff_rmsd": (mmff_result["rmsd"] if mmff_result else None),
        "mmff_height": (mmff_result["height"] if mmff_result else None),
        "mmff_planar_pred": (mmff_result["planar"] if mmff_result else None),
        "threshold_xtb": threshold_xtb,
    }
    (mmff_dir / "mmff_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _run_mmff_optimize_and_save(source_xyz: Path, mmff_dir: Path) -> dict | None:
    """Lit source.xyz, optimise MMFF, ecrit mmff_opt.xyz, renvoie dict.

    Retourne le dict de mmff_planarity ou None.
    Effet de bord : ecrit mmff_dir/mmff_opt.xyz si MMFF a tourne.
    """
    try:
        text = source_xyz.read_text(encoding="utf-8")
    except OSError:
        return None
    result, opt_xyz = mmff_planarity_with_coords(text)
    if result is None or opt_xyz is None:
        return None
    mmff_dir.mkdir(parents=True, exist_ok=True)
    try:
        (mmff_dir / "mmff_opt.xyz").write_text(opt_xyz, encoding="utf-8")
    except OSError:
        pass
    return result


# ---------------- Pipeline principal ----------------

def reconstruct_filter_validate_v3(
        graph, solutions: list,
        output_dir: Path | str,
        # MMFF 3-tier params
        th_sure_plan: float = DEFAULT_TH_SURE_PLAN,
        th_sure_non_plan: float = DEFAULT_TH_SURE_NON_PLAN,
        threshold_xtb: float = DEFAULT_TH_XTB,
        opt_level: str = DEFAULT_OPT_LEVEL,
        # xTB MD params
        md_params: Optional[dict] = None,
        md_deterministic: bool = True,
) -> list[dict]:
    """Pour chaque solution CSP : reconstruction -> MMFF 3-tier -> xTB conditionnel.

    Args:
        graph             : BenzenoidGraph
        solutions         : liste de dicts {v: 5|6|7}
        output_dir        : repertoire de sortie (scratch / vrai)
        th_sure_plan      : MMFF angle < this -> sure_plan (skip xTB)
        th_sure_non_plan  : MMFF angle > this -> sure_non_plan (skip everything)
        threshold_xtb     : seuil planarite final (sur xTB output)
        opt_level         : niveau d'opt xTB
        md_params         : dict optionnel pour personnaliser xTB MD
        md_deterministic  : single-thread xTB (reproductibilite)

    Returns:
        liste de dicts {index, decision_path, planar, angle_deg, ...} aligne
        sur l'API existante (les viewers/aggregateurs de v2 lisent ces dicts).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Verifier disponibilite xTB ; si absent, on saute completement les
    # solutions gray (et on log).
    have_xtb = bool(shutil.which("xtb"))
    if not have_xtb:
        print("  WARN : xTB introuvable dans le PATH. Les sols gray seront skip.",
              flush=True)

    # Path setup pour reconstruction (importe paresseusement)
    _csp_root = Path(__file__).resolve().parents[1]
    if str(_csp_root) not in sys.path:
        sys.path.insert(0, str(_csp_root))

    from reconstruction.pipeline import reconstruct_molecule
    from reconstruction.assembler import export_xyz

    results = []
    n_sure_plan = 0
    n_sure_non_plan = 0
    n_gray = 0
    n_mmff_failed = 0
    n_xtb_failed = 0
    n_recon_failed = 0

    for i, sol in enumerate(solutions, 1):
        sol_str = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
        print(f"\n--- Solution {i}/{len(solutions)} : {sol_str} ---", flush=True)

        sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))
        sol_dir = output_dir / f"sol_{i}_{sizes_str}"
        sol_dir.mkdir(parents=True, exist_ok=True)
        mmff_dir = sol_dir / "mmff_validation"

        # 1. Reconstruction
        try:
            mol = reconstruct_molecule(graph, sol, None)
        except Exception as e:
            n_recon_failed += 1
            print(f"  ERREUR reconstruction : {e}", flush=True)
            results.append({
                "index": i, "solution": sol,
                "decision_path": "geom_infeasible",
                "planar": False, "angle_deg": None,
                "message": f"recon: {e}",
            })
            continue

        source_path = sol_dir / "source.xyz"
        export_xyz(mol, str(source_path), comment=f"Solution {i}: {sol_str}")

        # 2. MMFF
        mmff_res = _run_mmff_optimize_and_save(source_path, mmff_dir)

        if mmff_res is None:
            # MMFF echec -> fallback xTB (comportement v2)
            n_mmff_failed += 1
            decision = "mmff_failed"
            _write_mmff_meta(mmff_dir, decision, None, threshold_xtb)
        else:
            angle = mmff_res["angle_deg"]
            if angle < th_sure_plan:
                decision = "mmff_sure_plan"
                n_sure_plan += 1
            elif angle > th_sure_non_plan:
                decision = "mmff_sure_non_plan"
                n_sure_non_plan += 1
            else:
                decision = "mmff_gray"
                n_gray += 1
            _write_mmff_meta(mmff_dir, decision, mmff_res, threshold_xtb)

        # 3. Decisions
        if decision == "mmff_sure_plan":
            # Accept sans xTB
            angle = mmff_res["angle_deg"]
            print(f"  MMFF sure_plan : angle={angle:.2f} deg -> ACCEPTE (skip xTB)",
                  flush=True)
            results.append({
                "index": i, "solution": sol,
                "decision_path": "mmff_sure_plan",
                "planar": True, "angle_deg": angle,
                "rmsd": mmff_res["rmsd"], "height": mmff_res["height"],
                "source": "mmff",
            })
            continue

        if decision == "mmff_sure_non_plan":
            angle = mmff_res["angle_deg"]
            print(f"  MMFF sure_non_plan : angle={angle:.2f} deg -> REJET (skip xTB)",
                  flush=True)
            results.append({
                "index": i, "solution": sol,
                "decision_path": "mmff_sure_non_plan",
                "planar": False, "angle_deg": angle,
                "rmsd": mmff_res["rmsd"], "height": mmff_res["height"],
                "source": "mmff",
            })
            continue

        # 4. Sinon (gray OU mmff_failed) : on lance xTB MD + opt
        if not have_xtb:
            print(f"  WARN : pas d'xTB dispo, skip sol {i}", flush=True)
            results.append({
                "index": i, "solution": sol,
                "decision_path": "xtb_skipped_no_binary",
                "planar": False, "angle_deg": None,
                "message": "xTB binary missing",
            })
            continue

        try:
            from core.optimizer_md import md_then_optimize  # via path setup ci-dessus
        except ImportError:
            _gen_root = _csp_root.parent / "non_benzenoid_generator"
            sys.path.insert(0, str(_gen_root))
            from core.optimizer_md import md_then_optimize  # noqa

        md_dir = sol_dir / "md_validation"
        success, final_xyz, info = md_then_optimize(
            str(source_path), str(md_dir),
            params=md_params, opt_level=opt_level,
            deterministic=md_deterministic,
        )
        md_dir.mkdir(parents=True, exist_ok=True)
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
            }
            (md_dir / "md_meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

        if not success:
            n_xtb_failed += 1
            print(f"  xTB ECHEC : {info.get('message', '?')}", flush=True)
            results.append({
                "index": i, "solution": sol,
                "decision_path": f"{decision}_xtb_failed",
                "planar": False, "angle_deg": None,
                "message": f"xTB failed: {info.get('message', '?')}",
            })
            continue

        # Planarite sur md_final_opt.xyz
        from utils.validate import test_planarity_from_xyz
        plan = test_planarity_from_xyz(str(final_xyz), threshold_xtb)
        verdict = "plan" if plan["planar"] else "non_plan"
        full_decision = f"{decision}_xtb_{verdict}"
        print(f"  xTB final : angle={plan['angle_deg']:.2f} deg -> {verdict.upper()}",
              flush=True)
        results.append({
            "index": i, "solution": sol,
            "decision_path": full_decision,
            "planar": plan["planar"], "angle_deg": plan["angle_deg"],
            "rmsd": plan["rmsd"], "height": plan["height"],
            "source": "xtb",
        })

    # Resume
    n_plan_total = sum(1 for r in results if r.get("planar"))
    n_xtb_calls = n_gray + n_mmff_failed - n_xtb_failed
    print(f"\n=== Resume pipeline v3 ===", flush=True)
    print(f"  Solutions             : {len(solutions)}", flush=True)
    print(f"  geom_infeasible       : {n_recon_failed}", flush=True)
    print(f"  mmff_sure_plan        : {n_sure_plan}  (acceptes sans xTB)", flush=True)
    print(f"  mmff_sure_non_plan    : {n_sure_non_plan}  (rejetes sans xTB)", flush=True)
    print(f"  mmff_gray (xTB)       : {n_gray}", flush=True)
    print(f"  mmff_failed (xTB fb)  : {n_mmff_failed}", flush=True)
    print(f"  xtb_failed            : {n_xtb_failed}", flush=True)
    print(f"  ==> plans generes     : {n_plan_total}", flush=True)
    return results
