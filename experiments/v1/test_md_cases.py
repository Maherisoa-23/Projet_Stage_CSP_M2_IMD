"""
Test cible des cas borderline MD : reproduit le protocole de validation
(maintenant DET-OPT, ex MD) sur des (molecule, sizes) specifiques, plusieurs
fois, et reporte la stabilite du verdict + le DETERMINISME byte-pour-byte.

Critere de succes du test
-------------------------
Apres bascule du protocole MD vers det-opt (perturbation z structuree +
xtb --opt), la sortie doit etre IDENTIQUE a chaque run pour le meme input :
  - md5(md_final_opt.xyz) constant sur les N runs
  - angle_deg, planar, rmsd : valeurs strictement identiques
Si ce n'est pas le cas, c'est une regression -- a investiguer.

Usage :
    python test_md_cases.py                # Cas hardcodes (h6 borderline)

Pour chaque cas, le script :
  1. Parse le .graph -> BenzenoidGraph
  2. Construit l'assignation x_v depuis les `sizes`
  3. Appelle reconstruct_molecule -> source.xyz dans un tempdir
  4. Lance md_then_optimize N fois
  5. Pour chaque run, reporte : verdict, angle, md5(md_final_opt), retries

A la fin, resume :
  - Determinisme : tous les runs produisent-ils le MEME md5 ?
  - Verdict stable ?
  - Echecs apres retry ?

Cas hardcodes (h6, config adj-57_no-freeze_no-table -- les 4 cas ou la
divergence a ete observee dans le batch precedent) :
  - 0-7-8-14-15-16  v0=7 v1=5 v2=5 v3=7 v4=5 v5=7
  - 2-7-8-9-10-16   v0=6 v1=6 v2=7 v3=5 v4=5 v5=7
  - 2-7-8-9-15-16   v0=7 v1=5 v2=5 v3=7 v4=7 v5=5
  - 2-8-9-14-15-16  v0=5 v1=7 v2=6 v3=6 v4=6 v5=6
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from statistics import mean, stdev


# Make csp_solver and non_benzenoid_generator importable.
# IMPORTANT : csp_solver doit etre EN PREMIER dans sys.path. Les 2 packages
# ont chacun un sous-paquet `utils/` ; si non_benzenoid_generator est en
# tete, `from utils.parser import parse` echoue (parser.py n'est que dans
# csp_solver/utils/). On import donc csp_solver avant, puis on ajoute
# non_benzenoid_generator EN FIN de path pour que `core.optimizer_md` se
# resolve sans masquer `utils.*` de csp_solver.
_HERE = Path(__file__).resolve().parent
_CSP_ROOT = _HERE.parent
_GEN_ROOT = _CSP_ROOT.parent / "non_benzenoid_generator"
sys.path.insert(0, str(_CSP_ROOT))

from utils.parser import parse                                  # noqa: E402
from reconstruction.pipeline import reconstruct_molecule        # noqa: E402
from reconstruction.assembler import export_xyz                 # noqa: E402
from utils.validate import test_planarity_from_xyz              # noqa: E402

# Import optimizer_md APRES les imports csp_solver pour ne pas que son
# `utils/` masque celui de csp_solver dans le resolver d'imports.
sys.path.append(str(_GEN_ROOT))
from csp_solver.xtb.md import md_then_optimize                  # noqa: E402


# Cas observes en divergence (h6, config adj-57_no-freeze_no-table)
DEFAULT_CASES = [
    {
        "h": "h6",
        "mol": "0-7-8-14-15-16",
        "sizes": {0: 7, 1: 5, 2: 5, 3: 7, 4: 5, 5: 7},
    },
    {
        "h": "h6",
        "mol": "2-7-8-9-10-16",
        "sizes": {0: 6, 1: 6, 2: 7, 3: 5, 4: 5, 5: 7},
    },
    {
        "h": "h6",
        "mol": "2-7-8-9-15-16",
        "sizes": {0: 7, 1: 5, 2: 5, 3: 7, 4: 7, 5: 5},
    },
    {
        "h": "h6",
        "mol": "2-8-9-14-15-16",
        "sizes": {0: 5, 1: 7, 2: 6, 3: 6, 4: 6, 5: 6},
    },
]


N_RUNS_PER_CASE = 5
THRESHOLD_DEG = 10.0


def graph_path(h: str, mol: str) -> Path:
    """Resoudre le chemin du .graph dans plane/benzdb/<h>/<mol>.graph."""
    return _HERE / "plane" / "benzdb" / h / f"{mol}.graph"


def sizes_str(sizes: dict) -> str:
    return " ".join(f"v{v}={sizes[v]}" for v in sorted(sizes.keys()))


def run_one(case: dict, run_id: int, base_tmp: Path) -> dict:
    """Lance le pipeline MD complet sur un cas, retourne un dict de resultats."""
    gp = graph_path(case["h"], case["mol"])
    if not gp.exists():
        return {"error": f".graph absent : {gp}", "run_id": run_id}

    graph = parse(str(gp))
    sol = case["sizes"]

    # Reconstruct + export source.xyz
    mol = reconstruct_molecule(graph, sol)
    work = base_tmp / f"run_{run_id}"
    work.mkdir(parents=True, exist_ok=True)
    src = work / "source.xyz"
    export_xyz(mol, str(src), comment=sizes_str(sol))

    # MD + opt avec retry logic
    md_dir = work / "md_validation"
    success, final, info = md_then_optimize(
        str(src), str(md_dir), opt_level="tight", deterministic=True
    )

    out = {
        "run_id": run_id,
        "success": bool(success),
        "n_attempts": info.get("n_attempts"),
        "attempts": info.get("attempts", []),
        "method": info.get("method"),
        "converged": info.get("converged"),
        "message": info.get("message", ""),
        "md5_final": None,        # md5 de md_final_opt.xyz : critere de determinisme
        "md5_perturbed": None,    # md5 de md_geom.xyz (input de l'opt)
    }

    if success and final and final.exists():
        plan = test_planarity_from_xyz(str(final), THRESHOLD_DEG)
        out.update({
            "planar": plan["planar"],
            "angle_deg": plan["angle_deg"],
            "rmsd": plan["rmsd"],
        })
        # md5 de la geometrie finale -> critere de determinisme byte-pour-byte
        out["md5_final"] = hashlib.md5(final.read_bytes()).hexdigest()
        # md5 de la perturbation (input de l'opt) -> verifie que la
        # perturbation elle-meme est deterministe
        md_geom = final.parent / "md_geom.xyz"
        if md_geom.exists():
            out["md5_perturbed"] = hashlib.md5(md_geom.read_bytes()).hexdigest()
    else:
        out["planar"] = False
        out["angle_deg"] = None
    return out


def summarize_case(case: dict, runs: list) -> str:
    """Resume textuel d'un cas : determinisme + verdicts + retries."""
    n = len(runs)
    n_ok = sum(1 for r in runs if r["success"])
    n_fail = n - n_ok
    angles = [r["angle_deg"] for r in runs if r.get("angle_deg") is not None]
    n_planar = sum(1 for r in runs if r.get("planar") is True)
    n_nonplanar = sum(1 for r in runs if r.get("success") and r.get("planar") is False)

    # Determinisme byte-pour-byte : tous les runs reussis doivent avoir le
    # MEME md5(md_final_opt.xyz). Si c'est le cas -> protocole 100% reproductible.
    md5_set = {r["md5_final"] for r in runs if r.get("md5_final")}
    md5_perturb_set = {r["md5_perturbed"] for r in runs if r.get("md5_perturbed")}

    n_retry_dist = {}
    for r in runs:
        k = r.get("n_attempts") or 0
        n_retry_dist[k] = n_retry_dist.get(k, 0) + 1

    lines = []
    lines.append(f"  Pipeline OK     : {n_ok}/{n}    Echecs : {n_fail}/{n}")
    lines.append(f"  Verdict planar  : {n_planar}/{n}    non plan : {n_nonplanar}/{n}")
    lines.append(f"  Tentatives par run : {dict(sorted(n_retry_dist.items()))}")
    if angles:
        if len(angles) >= 2:
            mu, sd = mean(angles), stdev(angles)
            lines.append(f"  Angle final : mu={mu:.4f}deg  sigma={sd:.4f}deg  range=[{min(angles):.4f}, {max(angles):.4f}]")
        else:
            lines.append(f"  Angle final : {angles[0]:.4f}deg")
    # Verdict de determinisme
    if md5_set:
        if len(md5_set) == 1:
            lines.append(f"  DETERMINISME    : ✓ md5(md_final_opt.xyz) IDENTIQUE sur {len(md5_set)*0+n_ok} runs ({list(md5_set)[0][:10]})")
        else:
            lines.append(f"  DETERMINISME    : ✗ {len(md5_set)} md5 differents sur {n_ok} runs reussis")
            for h in md5_set:
                count = sum(1 for r in runs if r.get("md5_final") == h)
                lines.append(f"    {h[:16]}... ({count} fois)")
    if md5_perturb_set and len(md5_perturb_set) > 1:
        lines.append(f"  /!\\ La perturbation z (md_geom.xyz) elle-meme varie : {len(md5_perturb_set)} md5")
    return "\n".join(lines)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] != "--default":
        # Mode <h_dir> : prendre tous les .graph d'un dossier (debug)
        # NOTE : sans assignation specifique, on saute -- on n'a pas de moyen
        # de deviner les sizes interessants depuis un dossier seul.
        print("ERREUR : le mode <h_dir> n'est pas implemente (besoin de sizes "
              "specifiques par cas). Edite la liste DEFAULT_CASES dans "
              "test_md_cases.py pour ajouter des cas.")
        sys.exit(1)

    cases = DEFAULT_CASES
    print(f"=== Test MD borderline : {len(cases)} cas, {N_RUNS_PER_CASE} runs chacun ===")
    print()

    base_tmp = Path(tempfile.mkdtemp(prefix="md_test_"))
    summary = []
    try:
        for case_idx, case in enumerate(cases, 1):
            print(f"--- [{case_idx}/{len(cases)}] {case['h']}/{case['mol']}  {sizes_str(case['sizes'])} ---")
            runs = []
            for r in range(1, N_RUNS_PER_CASE + 1):
                res = run_one(case, r, base_tmp / f"case_{case_idx}")
                runs.append(res)
                # Print compact d'un run
                if "error" in res:
                    print(f"  run {r}: ERREUR {res['error']}")
                    continue
                vs = "PLAN" if res.get("planar") else ("NON PLAN" if res.get("success") else "FAIL")
                ang = res.get("angle_deg")
                ang_str = f"{ang:.4f}" if ang is not None else "?"
                nat = res.get("n_attempts", "?")
                md5 = res.get("md5_final")
                md5_short = md5[:10] if md5 else "-"
                print(f"  run {r}: {vs:9s}  angle={ang_str}deg  attempts={nat}  md5={md5_short}")
                if res.get("attempts"):
                    for a in res["attempts"]:
                        print(f"      {a}")
            print(summarize_case(case, runs))
            summary.append({"case": case, "runs": runs})
            print()

        # Resume global
        print("=" * 70)
        print("=== Resume global ===")
        print("=" * 70)
        all_runs = [r for s in summary for r in s["runs"]]
        n = len(all_runs)
        n_ok = sum(1 for r in all_runs if r.get("success"))
        n_first_try = sum(1 for r in all_runs if r.get("n_attempts") == 1)
        n_retried = sum(1 for r in all_runs
                        if r.get("n_attempts") and r["n_attempts"] > 1)
        n_failed = n - n_ok
        print(f"Total runs                   : {n}")
        print(f"  Pipeline OK                : {n_ok}/{n}")
        print(f"  Reussite du premier coup   : {n_first_try}/{n}")
        print(f"  Reussite apres retry       : {n_retried}/{n}")
        print(f"  Echec total (apres 3 tries): {n_failed}/{n}")

        # Determinisme + stabilite par cas
        print()
        print(f"{'Molecule':<25s}  {'Determinisme':<13s}  {'Verdict':<10s}  Notes")
        print("-" * 80)
        n_deterministic = 0
        for s in summary:
            ok_runs = [r for r in s["runs"] if r.get("success")]
            md5_set = {r["md5_final"] for r in ok_runs if r.get("md5_final")}
            verdicts = {r.get("planar") for r in ok_runs}
            if len(md5_set) == 1:
                det_str = "OK"
                n_deterministic += 1
            elif len(md5_set) == 0:
                det_str = "(no run)"
            else:
                det_str = f"FAIL ({len(md5_set)})"
            if len(verdicts) <= 1:
                ver_str = "STABLE"
            else:
                ver_str = f"INSTABLE"
            note = ""
            if len(ok_runs) < len(s["runs"]):
                note = f"{len(s['runs']) - len(ok_runs)} echec(s)"
            print(f"{s['case']['mol']:<25s}  {det_str:<13s}  {ver_str:<10s}  {note}")
        print()
        print(f"DETERMINISME global : {n_deterministic}/{len(summary)} cas avec md5 identique sur tous les runs reussis")

        # Sauvegarde JSON pour analyse ulterieure
        out_path = _HERE / "test_md_cases_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nResultats detailles sauvegardes : {out_path}")
    finally:
        # Nettoyage tmpdir final (on garde rien des intermediaires)
        import shutil
        shutil.rmtree(base_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
