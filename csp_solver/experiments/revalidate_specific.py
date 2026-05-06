"""
Revalidation cible des 4 cas h6 borderline avec le nouveau protocole det-opt.

But : ne pas relancer un batch h6 entier (~3-4h) juste pour mettre a jour
ces 4 cas. On cible chirurgicalement les sol_X dans les configs concernees,
on regenere source.xyz + md_validation/ avec le code actuel (deterministe),
puis on re-agrege data.json.

Cas cibles (h6, configs no-freeze_no-table et adj-57_no-freeze_no-table) :
  - 0-7-8-14-15-16  v0=7 v1=5 v2=5 v3=7 v4=5 v5=7
  - 2-7-8-9-10-16   v0=6 v1=6 v2=7 v3=5 v4=5 v5=7
  - 2-7-8-9-15-16   v0=7 v1=5 v2=5 v3=7 v4=7 v5=5
  - 2-8-9-14-15-16  v0=5 v1=7 v2=6 v3=6 v4=6 v5=6

Pour chaque cas, on cherche le sol_dir dans :
  output/h6/<config>/<mol>/solutions/sol_*_<sizes_str>/
  cluster_results/h6/<config>/<mol>/solutions/sol_*_<sizes_str>/

On ecrase :
  source.xyz                (reconstruction deterministe nouvelle)
  md_validation/...         (det-opt nouveau)

Puis on relance aggregate_md.py sur les configs touchees pour mettre a jour
data.json (qui propage la planarite, l'angle, n_attempts, etc.).
"""

import json
import shutil
import sys
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CSP_ROOT = _HERE.parent
_GEN_ROOT = _CSP_ROOT.parent / "non_benzenoid_generator"
sys.path.insert(0, str(_CSP_ROOT))
from utils.parser import parse                                  # noqa: E402
from reconstruction.pipeline import reconstruct_molecule        # noqa: E402
from reconstruction.assembler import export_xyz                 # noqa: E402
from utils.validate import test_planarity_from_xyz              # noqa: E402
sys.path.append(str(_GEN_ROOT))
from core.optimizer_md import md_then_optimize                  # noqa: E402


CASES = [
    {"mol": "0-7-8-14-15-16",  "sizes": {0: 7, 1: 5, 2: 5, 3: 7, 4: 5, 5: 7}},
    {"mol": "2-7-8-9-10-16",   "sizes": {0: 6, 1: 6, 2: 7, 3: 5, 4: 5, 5: 7}},
    {"mol": "2-7-8-9-15-16",   "sizes": {0: 7, 1: 5, 2: 5, 3: 7, 4: 7, 5: 5}},
    {"mol": "2-8-9-14-15-16",  "sizes": {0: 5, 1: 7, 2: 6, 3: 6, 4: 6, 5: 6}},
]
CONFIGS = ["no-freeze_no-table", "adj-57_no-freeze_no-table"]
ROOTS = [
    _CSP_ROOT / "experiments" / "output" / "h6",
    _CSP_ROOT.parent / "cluster_results" / "h6",
]


def sizes_underscore(sizes: dict) -> str:
    """ Sizes au format dossier sol : '7_5_5_7_5_7' """
    return "_".join(str(sizes[v]) for v in sorted(sizes.keys()))


def sizes_str(sizes: dict) -> str:
    """ Format commentaire xyz : 'v0=7 v1=5 v2=5 ...' """
    return " ".join(f"v{v}={sizes[v]}" for v in sorted(sizes.keys()))


def find_sol_dir(root: Path, config: str, mol: str, sizes: dict) -> Path | None:
    """Trouve le dossier sol_*_<sizes_str> matchant ce cas."""
    needle = sizes_underscore(sizes)
    sol_root = root / config / mol / "solutions"
    if not sol_root.is_dir():
        return None
    for d in sorted(sol_root.iterdir()):
        if d.is_dir() and d.name.endswith(f"_{needle}"):
            return d
    return None


def revalidate(graph_path: Path, sol_dir: Path, sizes: dict, label: str):
    """Pour un sol_dir donne :
       1. Regenere source.xyz (reconstruction deterministe avec sorted())
       2. Wipe md_validation/, relance det-opt
       3. Test planarite
       4. Retourne dict avec resultats
    """
    graph = parse(str(graph_path))
    mol_obj = reconstruct_molecule(graph, sizes)

    # 1. Regenere source.xyz (deterministe avec le fix assembler.py:46)
    src = sol_dir / "source.xyz"
    sol_idx = sol_dir.name.split("_")[1]   # sol_<idx>_<sizes>
    export_xyz(mol_obj, str(src),
               comment=f"Solution {sol_idx}: {sizes_str(sizes)}")

    # 2. Wipe md_validation/, relance det-opt (= md_then_optimize aujourd'hui)
    md_dir = sol_dir / "md_validation"
    if md_dir.exists():
        shutil.rmtree(md_dir)

    success, final_xyz, info = md_then_optimize(
        str(src), str(md_dir),
        opt_level="tight", deterministic=True
    )

    # Persistance md_meta.json (comme _run_md le fait normalement)
    if md_dir.exists():
        meta = {
            "success": bool(success),
            "n_attempts": info.get("n_attempts"),
            "attempts": info.get("attempts", []),
            "n_frames": info.get("n_frames"),
            "expected_frames": info.get("expected_frames"),
            "ejection_threshold": info.get("ejection_threshold"),
            "converged": info.get("converged"),
            "deterministic": info.get("deterministic"),
            "method": info.get("method"),
            "message": info.get("message", ""),
        }
        (md_dir / "md_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # 3. Test planarite
    plan = None
    if success and final_xyz and final_xyz.exists():
        plan = test_planarity_from_xyz(str(final_xyz), 10.0)

    print(f"  [{label}] {sol_dir.relative_to(sol_dir.parents[3])}")
    if plan:
        verdict = "PLAN" if plan["planar"] else "NON PLAN"
        print(f"      {verdict}  angle={plan['angle_deg']:.4f}deg  attempts={info.get('n_attempts')}  msg={info.get('message','')[:50]}")
    else:
        print(f"      ECHEC  attempts={info.get('n_attempts')}  msg={info.get('message','')[:80]}")

    return {"success": success, "plan": plan, "info": info}


def main():
    print(f"=== Revalidation ciblee : {len(CASES)} cas, {len(CONFIGS)} configs, {len(ROOTS)} dossiers racine ===\n")

    affected_config_dirs = set()
    n_total = 0
    n_ok = 0

    for case in CASES:
        print(f"--- {case['mol']}  {sizes_str(case['sizes'])} ---")
        graph_path = _CSP_ROOT / "experiments" / "plane" / "benzdb" / "h6" / f"{case['mol']}.graph"
        if not graph_path.exists():
            print(f"  ERREUR : .graph absent : {graph_path}")
            continue

        for root in ROOTS:
            for config in CONFIGS:
                sol_dir = find_sol_dir(root, config, case["mol"], case["sizes"])
                if sol_dir is None:
                    continue
                n_total += 1
                # Label court : 'output/...' ou 'cluster_results/...'
                label = root.name + "/" + config
                try:
                    res = revalidate(graph_path, sol_dir, case["sizes"], label)
                    if res["success"]:
                        n_ok += 1
                        affected_config_dirs.add(root / config)
                except Exception as e:
                    print(f"  [{label}] EXCEPTION : {e}")
        print()

    print(f"=== {n_ok}/{n_total} sol_dir mis a jour ===\n")

    # Re-agreger data.json pour chaque config touchee
    aggregate_md = _HERE / "aggregate_md.py"
    print(f"=== Re-aggregation data.json sur {len(affected_config_dirs)} configs ===")
    for cfg_dir in sorted(affected_config_dirs):
        print(f"  -> {cfg_dir}")
        result = subprocess.run(
            [sys.executable, str(aggregate_md), str(cfg_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        # Affiche les 3 dernieres lignes (compact)
        for ln in (result.stdout or "").strip().split("\n")[-3:]:
            print(f"     {ln}")
    print()
    print("Termine. Pour visualiser, regenere les viewers :")
    for root in ROOTS:
        if any(d.parent.parent == root for d in affected_config_dirs):
            print(f"  python view.py {root.relative_to(_CSP_ROOT.parent)} --aggregate")


if __name__ == "__main__":
    main()
