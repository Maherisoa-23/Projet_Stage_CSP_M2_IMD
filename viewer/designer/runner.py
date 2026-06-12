"""
Execution d'un job designer : lance csp_solver/main.py en subprocess avec
les bons arguments, suit les stages via le stdout, et met a jour la DB.

Le runner s'execute dans un threading.Thread daemon depuis l'API Flask
(et non en multiprocessing) : ca permet de partager la connexion sqlite et
d'avoir un overhead minimal. Le subprocess de main.py reste un vrai
processus separe (pour ne pas bloquer le Flask).

Cycle :
    1. Cree un fichier temporaire .graph avec le contenu soumis.
    2. Construit la ligne de commande pour csp_solver/main.py.
    3. Lance le subprocess, met state='running' et PID en DB.
    4. Lit le stdout ligne par ligne ; chaque ligne contient des marqueurs
       qui permettent d'inferer le stage courant et la progression.
    5. A la fin : state='success' / 'failed' / 'cancelled', remplit
       duration_s et summary.

Note : la progression precise est best-effort. Si on n'arrive pas a
matcher de marqueur dans le stdout, on reste sur le dernier stage connu.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from . import jobs, solutions_db


# Seuil de planarite (deg) pour decider plan/non_plan. Aligne sur le
# pipeline principal (csp_solver/main.py, utils/validate.py).
PLANARITY_THRESHOLD_DEG = 10.0


def _setup_imports(project_root: Path) -> Dict:
    """Resout les modules csp_solver utilises par les helpers du runner.

    Depuis le refactor Option C (mai 2026), tout le code de reconstruction,
    optimisation xTB et planarite vit dans csp_solver/. Plus de collision
    avec non_benzenoid_generator/ (archive dans divers/_old_nbg/).

    On ajoute :
      - csp_solver/ au path pour 'utils.X' / 'reconstruction.X'
      - le parent du projet pour 'csp_solver.X' (utilise par les
        sous-modules : reconstruction/pipeline.py importe
        csp_solver.xtb.md, etc.)

    Cache idempotent via attribut de fonction.
    """
    if getattr(_setup_imports, "_done", False):
        return _setup_imports._cache

    csp_parent = str(project_root)
    csp_root = str(project_root / "csp_solver")
    for p in (csp_parent, csp_root):
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, csp_root)
    sys.path.insert(0, csp_parent)

    import importlib
    mod_parser = importlib.import_module("utils.parser")
    mod_pipeline = importlib.import_module("reconstruction.pipeline")
    mod_assembler = importlib.import_module("reconstruction.assembler")
    mod_xtb_opt = importlib.import_module("csp_solver.xtb.optimizer")
    mod_planarity = importlib.import_module("csp_solver.planarity.pca")

    cache = {
        "plan_mod": mod_planarity,
        "parse": mod_parser.parse,
        "reconstruct_molecule": mod_pipeline.reconstruct_molecule,
        "export_xyz": mod_assembler.export_xyz,
        "optimize_xtb": mod_xtb_opt.optimize_xtb,
        "read_optimized_coords": mod_xtb_opt.read_optimized_coords,
    }
    _setup_imports._done = True
    _setup_imports._cache = cache
    return cache


def _test_original_benzenoid(graph_path: Path, output_dir: Path,
                              project_root: Path) -> Dict:
    """Reconstruit + opt xTB + planarite du benzenoide d'entree (tout-hexagones).

    Ecrit :
        <output_dir>/original/original.xyz        : reconstruction (avant opt)
        <output_dir>/original/original_opt.xyz    : geometrie optimisee xTB
        <output_dir>/original/planarity.json      : metriques + verdict

    Returns le dict ecrit dans planarity.json. En cas d'echec, retourne
    {"success": False, "message": "..."}.
    """
    mods = _setup_imports(project_root)
    parse = mods["parse"]
    reconstruct_molecule = mods["reconstruct_molecule"]
    export_xyz = mods["export_xyz"]
    optimize_xtb = mods["optimize_xtb"]
    read_optimized_coords = mods["read_optimized_coords"]
    plan_mod = mods["plan_mod"]

    orig_dir = output_dir / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    plan_json = orig_dir / "planarity.json"

    try:
        graph = parse(str(graph_path))
        solution_all_6 = {v: 6 for v in range(graph.h)}
        mol = reconstruct_molecule(graph, solution_all_6)
        source_xyz = orig_dir / "original.xyz"
        opt_xyz = orig_dir / "original_opt.xyz"
        export_xyz(mol, str(source_xyz),
                    comment="Benzenoide d'entree (tout hexagonal)")
        ok, msg = optimize_xtb(str(source_xyz), str(opt_xyz), opt_level="tight")
        if not ok:
            result = {"success": False, "message": f"xTB opt echec : {msg}"}
            plan_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result

        coords = read_optimized_coords(str(opt_xyz))
        metrics = plan_mod.compute_planarity(coords)
        planar = plan_mod.is_planar(metrics, PLANARITY_THRESHOLD_DEG)
        result = {
            "success": True,
            "planar": bool(planar),
            "angle_deg": float(metrics["max_angle_deg"]),
            "rmsd": float(metrics["rmsd_plane"]),
            "height": float(metrics["height"]),
            "threshold_deg": PLANARITY_THRESHOLD_DEG,
            "xyz_path": str(opt_xyz.relative_to(project_root).as_posix()),
        }
        plan_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    except Exception as e:
        result = {"success": False, "message": f"Exception : {e}"}
        try:
            plan_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except OSError:
            pass
        return result


def _compute_solutions_planarity(output_dir: Path, project_root: Path) -> int:
    """Pour chaque sol_dir, calcule la planarite et persiste dans
    sol_dir/planarity.json.

    Strategie de lecture du XYZ :
      1. md_validation/md_final_opt.xyz (xtb --opt finalise, cas normal)
      2. source.xyz (reconstruction 3D plate, cas method=skip)
      3. Placeholder success=False si aucun des deux

    Cas method=skip : la reconstruction est plate par construction (z=0
    a la perturbation pres), donc angle_deg sera ~0 et planar=True. On
    annote alors verdict="skipped" dans le JSON pour que le frontend
    sache que ce n'est pas une vraie validation xtb.

    Returns le nombre de sol traites.
    """
    if not output_dir.is_dir():
        return 0
    mods = _setup_imports(project_root)
    plan_mod = mods["plan_mod"]
    read_optimized_coords = mods["read_optimized_coords"]

    n_done = 0
    for sol_dir in sorted(output_dir.glob("sol_*")):
        if not sol_dir.is_dir():
            continue
        md_final = sol_dir / "md_validation" / "md_final_opt.xyz"
        source_xyz = sol_dir / "source.xyz"
        plan_json = sol_dir / "planarity.json"

        # Determine le fichier a lire et le verdict associe
        xyz_to_read = None
        verdict_mode = None
        if md_final.is_file():
            xyz_to_read = md_final
            verdict_mode = "validated"
        elif source_xyz.is_file():
            # Pas d'optim xtb : on lit la reconstruction plate (mode skip)
            xyz_to_read = source_xyz
            verdict_mode = "skipped"

        if xyz_to_read is None:
            # Ni md_final ni source : sol non materialisee
            if not plan_json.exists():
                plan_json.write_text(json.dumps({
                    "success": False,
                    "message": "Aucun XYZ trouve (ni md_final_opt.xyz ni source.xyz)",
                }, indent=2), encoding="utf-8")
            continue
        try:
            coords = read_optimized_coords(str(xyz_to_read))
            metrics = plan_mod.compute_planarity(coords)
            planar = plan_mod.is_planar(metrics, PLANARITY_THRESHOLD_DEG)
            result = {
                "success": True,
                "planar": bool(planar),
                "angle_deg": float(metrics["max_angle_deg"]),
                "rmsd": float(metrics["rmsd_plane"]),
                "height": float(metrics["height"]),
                "threshold_deg": PLANARITY_THRESHOLD_DEG,
                "verdict_mode": verdict_mode,  # "validated" | "skipped"
            }
            plan_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
            n_done += 1
        except Exception as e:
            try:
                plan_json.write_text(json.dumps({
                    "success": False, "message": str(e),
                }, indent=2), encoding="utf-8")
            except OSError:
                pass
    return n_done


# Markers a chercher dans le stdout de main.py pour deduire l'avancement.
# Ces patterns sont base sur le code actuel de csp_solver/main.py (mai 2026).
# Si main.py change, mettre a jour ici.
_STAGE_MARKERS = [
    # Step name, regex pattern, progress fraction
    ("parse",        re.compile(r"^=== Lecture de "),                0.05),
    ("preprocess",   re.compile(r"^=== Pre-traitement ==="),         0.15),
    ("csp",          re.compile(r"^=== Resolution ==="),             0.25),
    ("csp_done",     re.compile(r"^=== \d+ solutions? trouve"),      0.40),
    ("reconstruct",  re.compile(r"^=== Reconstruction "),            0.45),
    ("md",           re.compile(r"^=== Validation "),                0.60),
]


def _resolve_preset_flags(config: Dict) -> Dict:
    """Transforme un preset (config['preset']) en flags concrets.

    Cherche le preset_key dans :
      - CSP_PRESETS_CANONICAL : C1, C2, C3, Ctopo (UI radios)
      - CSP_PRESETS_LEGACY    : baseline, pb1, pb1_adj57, ... (compat)

    Si preset == 'custom' (ou absent), garde les toggles individuels du
    tableau de bord. Sinon, REMPLACE les flags CSP par ceux du preset.

    Returns:
        Un nouveau dict de config avec les flags resolus. Les options
        orthogonales (validate, no_freeze, no_table, method, n_runs,
        count_hexagon, cluster) sont preservees.
    """
    try:
        from .csp_presets import resolve_preset_flags as _resolve
    except ImportError:
        from viewer.designer.csp_presets import resolve_preset_flags as _resolve

    preset_key = (config.get("preset") or "custom")
    resolved = dict(config)  # copie

    if preset_key == "custom":
        return resolved

    # Mode preset : on efface les overrides CSP individuels, puis on injecte
    for csp_flag in ("adj_57", "K_sym", "K_pb", "K_hb", "K_tot",
                     "tau_gb", "radius_gb",
                     "ctopo_filter", "ctopo_min_n_peri"):
        resolved.pop(csp_flag, None)
    resolved.update(_resolve(preset_key))
    return resolved


def _build_command(python_exe: str, main_py: Path, graph_path: Path,
                   output_dir: Path, config: Dict) -> list:
    """Construit la commande subprocess depuis le dict de config."""
    config = _resolve_preset_flags(config)
    cmd = [python_exe, str(main_py), str(graph_path)]

    # --- Validation xTB ---
    # method=skip : pas d'opt xTB, juste reconstruction plate (z=0)
    # Pour le solveur CSP en ligne de commande, on traduit ca par
    # 'pas de --validate' + flag dedie --method skip que main.py interprete.
    method = (config.get("method") or "det-opt").lower()
    if method == "skip":
        # Pas de --validate : on ne lance pas xtb, on garde juste la
        # reconstruction 3D plate
        pass
    else:
        if config.get("validate", True):
            cmd.append("--validate")

    # --- Contraintes CSP ---
    if config.get("no_freeze"):
        cmd.append("--no-freeze")
    if config.get("no_table"):
        cmd.append("--no-table")
    if config.get("adj_57"):
        cmd.append("--adj-57")
    if config.get("count_hexagon"):
        cmd.append("--count-hexagon")
    if config.get("K_sym") is not None:
        cmd.extend(["--sym", str(int(config["K_sym"]))])
    if config.get("K_pb") is not None:
        cmd.extend(["--pb", str(int(config["K_pb"]))])
    if config.get("K_hb") is not None:
        cmd.extend(["--hb", str(int(config["K_hb"]))])
    if config.get("K_tot") is not None:
        cmd.extend(["--tot", str(int(config["K_tot"]))])
    if config.get("tau_gb") is not None:
        cmd.extend(["--tau-gb", str(int(config["tau_gb"]))])
    if config.get("radius_gb") is not None and config.get("radius_gb") != 2:
        cmd.extend(["--radius-gb", str(int(config["radius_gb"]))])
    if config.get("ctopo_filter"):
        cmd.append("--ctopo")
        if config.get("ctopo_min_n_peri") is not None and int(config["ctopo_min_n_peri"]) != 4:
            cmd.extend(["--ctopo-min-n-peri", str(int(config["ctopo_min_n_peri"]))])

    # --- Output et validation ---
    cmd.extend(["--output-dir", str(output_dir)])
    n_runs = config.get("n_runs")
    if n_runs and int(n_runs) > 1 and method == "multi-runs":
        cmd.extend(["--n-runs", str(int(n_runs))])
    if method and method != "skip":
        cmd.extend(["--method", str(method)])
    return cmd


def _count_outputs(output_dir: Path) -> Dict[str, int]:
    """Compte les outputs presents dans le dossier de sortie.

    n_with_xyz : sols avec source.xyz (reconstruction 3D plate)
    n_with_md  : sols avec md_validation/md_final_opt.xyz (xtb finalise)

    En mode skip xTB : n_with_xyz > 0 mais n_with_md = 0.
    """
    if not output_dir.is_dir():
        return {"n_sol_dirs": 0, "n_with_xyz": 0, "n_with_md": 0}
    sol_dirs = list(output_dir.glob("sol_*"))
    n_with_xyz = sum(1 for d in sol_dirs if (d / "source.xyz").is_file())
    n_with_md = sum(1 for d in sol_dirs
                    if (d / "md_validation" / "md_final_opt.xyz").is_file())
    return {
        "n_sol_dirs": len(sol_dirs),
        "n_with_xyz": n_with_xyz,
        "n_with_md": n_with_md,
    }


def run_job(db_path: str, job_id: str, project_root: Path,
            python_exe: Optional[str] = None) -> None:
    """Execute un job de bout en bout. Bloquant : a lancer dans un thread.

    Args:
        db_path      : chemin de db_all.db
        job_id       : UUID du job
        project_root : racine du projet (pour resoudre csp_solver/main.py)
        python_exe   : interpreteur python a utiliser. Par defaut, le venv
                       du projet si present, sinon sys.executable.
    """
    import os
    import sys

    job = jobs.get_job(db_path, job_id)
    if job is None:
        return  # Devrait pas arriver

    # --- Aiguillage cluster ---
    # Si la config du job demande l'execution sur cluster ET que la feature
    # est globalement activee (env DESIGNER_CLUSTER_ENABLED=1), on delegue
    # a cluster_runner. Sinon, on log un echec explicite ou on continue en
    # local selon le cas.
    config = job.get("config", {})
    if config.get("cluster"):
        if os.getenv("DESIGNER_CLUSTER_ENABLED", "0") == "1":
            from . import cluster_runner
            return cluster_runner.run_job_cluster(db_path, job_id, project_root)
        # La case "cluster" a ete cochee mais la feature globale est off :
        # mode strict, on echoue plutot que de tourner en local par surprise.
        jobs.update_job(db_path, job_id, state="failed",
                        error="Mode cluster demande mais DESIGNER_CLUSTER_ENABLED "
                              "n'est pas '1'. Definis cette env var pour activer.")
        return

    if python_exe is None:
        # Cherche d'abord le venv du projet
        venv_python = project_root / "venv" / "Scripts" / "python.exe"
        if venv_python.is_file():
            python_exe = str(venv_python)
        else:
            python_exe = sys.executable

    main_py = project_root / "csp_solver" / "main.py"
    output_dir = project_root / job["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    # Ecrire le .graph dans le dossier de sortie pour reference / re-lancement
    graph_path = output_dir / "input.graph"
    graph_path.write_text(job["graph_content"], encoding="utf-8")

    cmd = _build_command(python_exe, main_py, graph_path, output_dir,
                          job.get("config", {}))

    t_start = time.time()

    # Etape 0 : test xTB sur le benzenoide d'entree (tout-hexagones).
    # Permet d'afficher dans la vue job la planarite de la molecule
    # d'origine, en plus des solutions substituees. Rapide (~5-15s).
    # Skip si test_original=False dans la config (gain ~5-15s).
    if job.get("config", {}).get("test_original", True):
        jobs.update_job(db_path, job_id, state="running",
                         current_stage="original", progress=0.03)
        try:
            _test_original_benzenoid(graph_path, output_dir, project_root)
        except Exception:
            # On n'echoue pas le job si le test original plante : c'est un
            # indicateur, pas une etape critique. Le frontend affichera
            # success=False dans planarity.json.
            pass

    jobs.update_job(db_path, job_id, state="running",
                     current_stage="parse", progress=0.08)

    # Lancement du subprocess. On capture stdout pour parser les stages.
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )
        jobs.update_job(db_path, job_id, pid=proc.pid)
    except Exception as e:
        jobs.update_job(db_path, job_id, state="failed",
                         error=f"Echec du lancement subprocess : {e}",
                         duration_s=time.time() - t_start)
        return

    stdout_lines = []
    last_stage = "parse"
    last_progress = 0.05
    try:
        for line in proc.stdout:
            stdout_lines.append(line.rstrip())
            # Garde-fou : on log les 500 dernieres lignes max pour le summary
            if len(stdout_lines) > 500:
                stdout_lines = stdout_lines[-500:]
            for stage, pattern, prog in _STAGE_MARKERS:
                if pattern.match(line):
                    if prog > last_progress:
                        last_stage = stage
                        last_progress = prog
                        jobs.update_job(db_path, job_id,
                                         current_stage=stage, progress=prog)
                    break
        rc = proc.wait()
    except Exception as e:
        # Erreur pendant la lecture du stdout
        try:
            proc.kill()
        except Exception:
            pass
        jobs.update_job(db_path, job_id, state="failed",
                         error=f"Erreur lecture stdout : {e}",
                         duration_s=time.time() - t_start,
                         pid=None)
        return

    duration = time.time() - t_start

    # Verifier l'etat final (a pu etre passe a 'cancelled' entre temps)
    current = jobs.get_job(db_path, job_id)
    if current and current.get("state") == "cancelled":
        # Le job a ete annule entre temps
        jobs.update_job(db_path, job_id, duration_s=duration, pid=None)
        return

    if rc == 0:
        # Etape finale : calcule la planarite de chaque solution materialisee
        # et persiste dans sol_dir/planarity.json (lu par l'endpoint /solutions).
        jobs.update_job(db_path, job_id, current_stage="aggregate", progress=0.95)
        try:
            n_planarity = _compute_solutions_planarity(output_dir, project_root)
        except Exception:
            n_planarity = 0
        # Capture les counts fs AVANT ingest_local_job : si l'ingestion
        # reussit, elle supprime output_dir et _count_outputs renverrait 0.
        outputs = _count_outputs(output_dir)
        # Ingestion en DB : XYZ -> table xyz_files (gzippe), metriques ->
        # table designer_solutions. Le flag ingest_complete=True signale
        # a l'API qu'elle peut lire depuis la DB ; sinon fallback FS pour
        # eviter de masquer une ingestion partielle (cf. audit phase 2).
        try:
            ingest_stats = solutions_db.ingest_local_job(
                db_path, job_id, output_dir, project_root,
                threshold_deg=PLANARITY_THRESHOLD_DEG)
            ingest_complete = ingest_stats["n_failed"] == 0
        except Exception:
            ingest_stats = {"n_ingested": 0, "n_failed": -1, "total": 0,
                            "original": None, "workdir_deleted": False}
            ingest_complete = False
        summary = {
            "return_code": 0,
            "stdout_tail": stdout_lines[-50:],
            "n_planarity_computed": n_planarity,
            "n_ingested_db": ingest_stats["n_ingested"],
            "n_failed_db": ingest_stats["n_failed"],
            "ingest_complete": ingest_complete,
            "workdir_deleted": ingest_stats.get("workdir_deleted", False),
            "original": ingest_stats.get("original"),
            **outputs,
        }
        jobs.update_job(db_path, job_id, state="success",
                         current_stage="done", progress=1.0,
                         duration_s=duration, pid=None,
                         summary=summary)
    else:
        error_tail = "\n".join(stdout_lines[-30:])
        jobs.update_job(db_path, job_id, state="failed",
                         error=f"Subprocess exit code {rc}\n\n{error_tail}",
                         duration_s=duration, pid=None,
                         summary={"return_code": rc,
                                  "stdout_tail": stdout_lines[-50:]})


def cancel_job(db_path: str, job_id: str) -> bool:
    """Tente d'annuler un job en cours d'execution.

    Returns:
        True si on a envoye un signal, False si le job n'est pas en
        etat 'running' ou si le pid est inconnu.
    """
    job = jobs.get_job(db_path, job_id)
    if job is None or job.get("state") != "running":
        return False
    pid = job.get("pid")
    if not pid:
        return False
    # Marquer comme cancelled tout de suite pour eviter une race
    jobs.update_job(db_path, job_id, state="cancelled",
                     error="Annule par l'utilisateur")
    try:
        if os.name == "nt":
            # Windows : taskkill /T pour killer aussi les enfants
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                            check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception:
        # Pas grave : le job a deja ete marque cancelled.
        return True
    return True


def start_job_thread(db_path: str, job_id: str, project_root: Path) -> threading.Thread:
    """Lance run_job dans un thread daemon. Retourne le Thread."""
    t = threading.Thread(target=run_job, args=(db_path, job_id, project_root),
                          daemon=True, name=f"designer-job-{job_id}")
    t.start()
    return t
