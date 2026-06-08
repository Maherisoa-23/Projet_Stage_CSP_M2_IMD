"""Worker xTB batch — lance via SSH par le dispatcher.

Lit un JSON sur stdin contenant un batch de sols a traiter. Pour chacune :
  1. Reconstruit la geometrie 3D depuis (graph + solution CSP)
  2. Lance xTB --opt deterministe (OMP_NUM_THREADS=1, perturbation z structuree)
  3. Parse metriques (energie, HOMO-LUMO, temps CPU/wall)
  4. Calcule la planarite ACP (angle deg)
  5. Categorise verdict : PLAN / LIMITE / NON_PLAN

Traite les sols EN PARALLELE LOCAL via threading, jusqu'a max_parallel
threads concurrents (defaut 40 = nb cores / 1). Chaque xtb subprocess
herite OMP_NUM_THREADS=1 -> garantit le determinisme byte-pour-byte.

Sortie JSON sur stdout :
  { "results": [ {sol_id, status, verdict, angle_deg, energy_eh, ...}, ... ] }

Erreurs par sol -> result.status = "failed" + result.error_message,
sans tuer le batch entier.

Erreurs globales (JSON malforme, etc) -> exit 1 + message sur stderr.

Lance via SSH :
  ssh host 'cd ~/projet && python -m csp_solver._worker_batch' < batch.json > result.json
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path


def _ensure_imports():
    here = Path(__file__).resolve().parent
    parent = here.parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))


_ensure_imports()


# === Constantes verdict ===

ANGLE_THRESHOLD_PLAN = 10.0
ANGLE_THRESHOLD_LIMITE = 15.0


def _angle_to_verdict(angle_deg):
    if angle_deg is None:
        return "ERROR"
    if angle_deg < ANGLE_THRESHOLD_PLAN:
        return "PLAN"
    if angle_deg < ANGLE_THRESHOLD_LIMITE:
        return "LIMITE"
    return "NON_PLAN"


# === Traitement d'une seule sol ===

def _process_one_sol(sol_dict, timeout_xtb, host, perturb_params=None):
    """Traite une sol et retourne un dict result.

    sol_dict attendu :
      sol_id        (int)
      graph_content (str)
      csp_solution  (dict {v_idx: taille}, cles peuvent etre str)
      sol_index     (int)
    """
    sol_id = sol_dict["sol_id"]
    t_start = time.perf_counter()

    result = {
        "sol_id": sol_id,
        "hostname": host,
        "status": "failed",
        "verdict": None,
        "angle_deg": None,
        "energy_eh": None,
        "homo_lumo_ev": None,
        "cpu_time_s": None,
        "wall_time_s": None,
        "xyz_optimized": None,
        "error_message": None,
    }

    workdir = None
    try:
        # Imports differes pour eviter le cout au demarrage du worker
        from utils.parser import parse as parse_graph
        from reconstruction import reconstruct_molecule, export_xyz
        from xtb.md import md_then_optimize
        from planarity.pca import compute_planarity
        from _xtb_metrics import parse_xtb_logfile

        # Reconstruire la sol avec cles int (JSON les sauve en str)
        sol_raw = sol_dict["csp_solution"]
        sol_int = {int(k): int(v) for k, v in sol_raw.items()}

        workdir = Path(tempfile.mkdtemp(prefix=f"worker_{sol_id}_"))

        # Ecrire le graph dans le workdir
        graph_path = workdir / "input.graph"
        graph_path.write_text(sol_dict["graph_content"], encoding="utf-8")

        # Parse + reconstruction
        graph = parse_graph(str(graph_path))
        mol = reconstruct_molecule(graph, sol_int)

        # XYZ d'entree (geometrie plate)
        input_xyz = workdir / "source.xyz"
        export_xyz(mol, str(input_xyz),
                   comment=f"sol_id={sol_id} sol_index={sol_dict.get('sol_index')}")

        # xTB det-opt (deterministe : OMP=1)
        ok, final_xyz, info = md_then_optimize(
            str(input_xyz), str(workdir),
            params=perturb_params,  # peut etre None (defaults) ou {"mode":"random","amplitude":1.0,"seed":42}
            opt_level="tight",
            timeout_opt=timeout_xtb,
            deterministic=True,
            max_retries=3,
        )

        if not ok or final_xyz is None or not Path(final_xyz).exists():
            result["error_message"] = f"xTB failed : {info.get('message', '?')}"
            return result

        # Parser stdout xtb (sauve par md.py dans workdir + un .log eventuel)
        # md.py ne sauve PAS le stdout xtb dans un fichier. On le re-derive
        # via le fichier xtbopt qui contient l'energie en commentaire.
        # Pour avoir stdout xtb il faudrait modifier md.py. Pour l'instant
        # on extrait l'energie depuis le header XYZ optimise (xtb l'y ecrit).
        metrics = _parse_xtb_metrics_from_artifacts(workdir, final_xyz)

        # Lecture du XYZ optimise (pour le commit DB)
        xyz_content = Path(final_xyz).read_text(encoding="utf-8")

        # Planarite
        coords = _extract_coords(xyz_content)
        planar_metrics = compute_planarity(coords)
        angle_deg = float(planar_metrics.get("max_angle_deg", 999.0))

        result.update({
            "status": "done",
            "verdict": _angle_to_verdict(angle_deg),
            "angle_deg": angle_deg,
            "energy_eh": metrics.get("energy_eh"),
            "homo_lumo_ev": metrics.get("homo_lumo_ev"),
            "cpu_time_s": metrics.get("cpu_time_s"),
            "xyz_optimized": xyz_content,
        })
    except Exception as e:
        result["error_message"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1000:]}"
    finally:
        # Cleanup workdir
        if workdir is not None and workdir.exists():
            try:
                import shutil
                shutil.rmtree(str(workdir), ignore_errors=True)
            except Exception:
                pass

    result["wall_time_s"] = time.perf_counter() - t_start
    return result


def _parse_xtb_metrics_from_artifacts(workdir: Path, final_xyz: Path) -> dict:
    """Extrait energy_eh + homo_lumo_ev + cpu_time_s.

    Strategie :
      1. Si workdir/xtb.log existe (cree par md.py future patch), parser ca
      2. Sinon, parser le commentaire (ligne 2) du XYZ final qui contient
         souvent "energy: -X.XXXX gnorm: ..." cree par xTB
    """
    from _xtb_metrics import parse_xtb_stdout

    # Strategie 1 : log xtb dans le workdir (si md.py patche pour le sauver)
    for cand in (workdir / "xtb.log", workdir / "opt.log"):
        if cand.exists():
            try:
                return parse_xtb_stdout(cand.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass

    # Strategie 2 : commentaire XYZ final
    out = {"energy_eh": None, "homo_lumo_ev": None, "cpu_time_s": None,
           "wall_time_s": None, "converged": False}
    try:
        lines = Path(final_xyz).read_text(encoding="utf-8").splitlines()
        if len(lines) >= 2:
            comment = lines[1]
            # Format xTB : "  energy:    -10.12345  gnorm:  0.0001 ..."
            import re
            m = re.search(r"energy:\s*(-?\d+\.\d+)", comment)
            if m:
                out["energy_eh"] = float(m.group(1))
    except Exception:
        pass
    return out


def _extract_coords(xyz_content: str):
    """Extrait la liste de coords [(x,y,z), ...] d'un XYZ."""
    lines = xyz_content.splitlines()
    if not lines:
        return []
    try:
        n = int(lines[0].strip())
    except (ValueError, IndexError):
        return []
    coords = []
    for i in range(2, min(2 + n, len(lines))):
        parts = lines[i].split()
        if len(parts) >= 4:
            try:
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                pass
    return coords


# === Worker main ===

def main():
    # Force OMP=1 / MKL=1 pour determinisme + permet plus de xtb en parallel
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

    try:
        raw = sys.stdin.read()
        batch = json.loads(raw)
    except Exception as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}"}), flush=True)
        sys.exit(1)

    sols = batch.get("sols") or []
    max_parallel = int(batch.get("max_parallel", 40))
    timeout_xtb = int(batch.get("timeout_xtb", 50000))
    perturb_params = batch.get("perturb_params")  # None ou {"mode":"random","amplitude":1.0,"seed":42}
    host = socket.gethostname()

    if not sols:
        print(json.dumps({"results": []}), flush=True)
        return

    sem = threading.Semaphore(max_parallel)
    results = [None] * len(sols)

    def runner(idx, sol):
        with sem:
            results[idx] = _process_one_sol(sol, timeout_xtb, host, perturb_params)

    threads = []
    for i, sol in enumerate(sols):
        t = threading.Thread(target=runner, args=(i, sol), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    # Filter Nones (shouldn't happen) et serialise
    out = {"results": [r for r in results if r is not None]}
    print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
