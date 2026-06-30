"""Execution remote (SSH) d'un job designer sur le cluster.

Pendant cluster de runner.run_job. Le subprocess csp_solver/main.py tourne
sur la frontale (192.168.200.49) au lieu du PC local. Les XYZ sont ensuite
rapatries via scp, la planarite calculee localement, et tout est ingere
en DB (table xyz_files + designer_solutions).

Pre-requis :
  - SSH sans password vers CLUSTER_HOST (cf. tmp/test_cluster_xtb.py)
  - Code csp_solver synchronise sur CLUSTER_PROJECT_PATH
  - conda env 'nonbenz' avec PyCSP3 + ACE + xTB

Strategie de robustesse :
  - Test de vie cluster en pre-flight (timeout 30s).
  - Si echec a n'importe quelle etape : state='failed' avec message explicite,
    cleanup du workdir distant. Pas de corruption silencieuse.
  - Pas de ControlMaster (volontaire, MVP) : on ouvre 3 connexions SSH par
    job (mkdir, run, cleanup) + 2 scp. Overhead ~10s par job, negligeable
    face a un MD+opt qui dure plusieurs minutes.
"""

import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from . import jobs, solutions_db
from .runner import (
    PLANARITY_THRESHOLD_DEG,
    _STAGE_MARKERS,
    _compute_solutions_planarity,
    _count_outputs,
    _resolve_preset_flags,
    _test_original_benzenoid,
)


CLUSTER_HOST = "192.168.200.49"
# Path racine du code csp_solver sur le cluster. Doit etre synchronise
# manuellement avec rsync ou git pull avant les jobs. Le user docu sa
# procedure de sync dans cluster/README ou CLUSTER_USAGE.md.
CLUSTER_PROJECT_PATH = "~/projet"
CLUSTER_CONDA_INIT = (
    'eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" '
    '&& conda activate nonbenz'
)


def _ssh(cmd_str, timeout=60):
    """Wrapper ssh CLUSTER_HOST 'cmd'. Retourne CompletedProcess."""
    return subprocess.run(
        ["ssh", CLUSTER_HOST, cmd_str],
        capture_output=True, text=True, timeout=timeout,
    )


def _scp(src, dst, recursive=False, timeout=600):
    """Wrapper scp. src et dst sont des strings (peuvent etre host:path)."""
    cmd = ["scp"]
    if recursive:
        cmd.append("-r")
    cmd.extend([src, dst])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def check_cluster_alive():
    """Test de vie : ssh ok + conda env nonbenz + xtb dispo + recupere $HOME.

    Retourne (ok, msg_or_home). En cas de succes, le 2eme element est le
    home distant absolu (ex: '/home/COALA/ramaherisoa'). En cas d'echec,
    c'est un message d'erreur lisible.

    Pourquoi recuperer $HOME : on ne peut pas mettre '~/...' dans les
    arguments quotes avec shlex (bash n'etend pas ~ entre single quotes).
    On construit donc des paths ABSOLUS pour la commande remote, ce qui
    permet de garder shlex.quote() pour la defense en profondeur.
    """
    try:
        r = _ssh(
            f"{CLUSTER_CONDA_INIT} && which xtb >/dev/null && which python >/dev/null "
            f"&& test -d {CLUSTER_PROJECT_PATH}/csp_solver "
            f"&& echo HOME=$HOME",
            timeout=30,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:300]
            # Diagnostic plus precis : on chaine plusieurs sous-checks pour
            # localiser l'echec quand le check combine echoue.
            for check, msg in (
                ('which xtb', f"xtb manquant dans l'env conda nonbenz"),
                ('which python', f"python manquant dans l'env conda nonbenz"),
                (f'test -d {CLUSTER_PROJECT_PATH}/csp_solver',
                 f"CLUSTER_PROJECT_PATH={CLUSTER_PROJECT_PATH}/csp_solver "
                 f"introuvable (sync le code avec scp/rsync)"),
            ):
                try:
                    sub = _ssh(f"{CLUSTER_CONDA_INIT} && {check}", timeout=15)
                    if sub.returncode != 0:
                        return False, msg
                except Exception:
                    break
            return False, f"SSH/conda check echec : {err}"
        for line in (r.stdout or "").splitlines():
            if line.startswith("HOME="):
                home = line[5:].strip()
                if home:
                    return True, home
        return False, "Impossible de recuperer $HOME du cluster"
    except subprocess.TimeoutExpired:
        return False, "Timeout >30s : cluster injoignable ou SSH bloque"
    except FileNotFoundError:
        return False, "ssh.exe introuvable dans le PATH"
    except Exception as e:
        return False, f"SSH exception : {e}"


def _build_remote_command(config, remote_graph, remote_output):
    """Construit la commande shell distante.

    Pendant cluster de runner._build_command. Differences :
      - paths Linux (remote_graph, remote_output)
      - 'python -m csp_solver.main' (depend de CLUSTER_PROJECT_PATH dans sys.path)
      - prefixe CLUSTER_CONDA_INIT + cd vers le projet
    """
    config = _resolve_preset_flags(config)
    parts = [
        CLUSTER_CONDA_INIT,
        f"&& cd {CLUSTER_PROJECT_PATH}",
        "&& python -m csp_solver.main",
        shlex.quote(remote_graph),
    ]
    method = (config.get("method") or "skip").lower()
    if method != "skip" and config.get("validate", True):
        parts.append("--validate")
    # Gel b(v) >= 2 desactive par defaut : --no-freeze sauf si "freeze_bv2" coche.
    if not config.get("freeze_bv2") or config.get("no_freeze"):
        parts.append("--no-freeze")
    if config.get("no_table"):
        parts.append("--no-table")
    if config.get("adj_57"):
        parts.append("--adj-57")
    if config.get("count_hexagon"):
        parts.append("--count-hexagon")
    if config.get("K_sym") is not None:
        parts.extend(["--sym", str(int(config["K_sym"]))])
    if config.get("K_pb") is not None:
        parts.extend(["--pb", str(int(config["K_pb"]))])
    if config.get("K_hb") is not None:
        parts.extend(["--hb", str(int(config["K_hb"]))])
    if config.get("K_tot") is not None:
        parts.extend(["--tot", str(int(config["K_tot"]))])
    parts.extend(["--output-dir", shlex.quote(remote_output)])
    if method != "skip":
        parts.extend(["--method", str(method)])
    return " ".join(parts)


def _merge_scp_output(scp_parent_dir, output_dir_local):
    """scp -r host:remote_output/ local_parent/ cree local_parent/output/.

    On veut son contenu directement dans output_dir_local. Cette helper
    deplace les enfants de scp_parent/output/ vers output_dir_local/ et
    nettoie le 'output/' intermediaire.
    """
    intermediate = scp_parent_dir / "output"
    if not intermediate.is_dir() or intermediate == output_dir_local:
        return
    for child in intermediate.iterdir():
        dest = output_dir_local / child.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(child), str(dest))
    try:
        intermediate.rmdir()
    except OSError:
        pass


def run_job_cluster(db_path, job_id, project_root):
    """Execute un job designer sur le cluster. Bloquant : a lancer dans un thread.

    Memes contrats que runner.run_job :
      - Lit le job dans designer_jobs.
      - Met a jour state/progress/current_stage en temps reel.
      - A la fin : state='success'/'failed' + summary + duration_s.
      - En cas de succes, ingere les XYZ + metriques en DB.

    Args:
        db_path      : chemin de la DB sqlite
        job_id       : UUID du job
        project_root : racine locale du projet (pour resoudre output_dir_local)
    """
    job = jobs.get_job(db_path, job_id)
    if job is None:
        return  # ne devrait pas arriver

    config = job.get("config", {})
    output_dir_local = project_root / job["output_dir"]
    output_dir_local.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    remote_root: Optional[str] = None  # set apres recup de $HOME ; lu dans le finally

    try:
        _run_job_cluster_inner(db_path, job_id, project_root, job, config,
                               output_dir_local, t_start,
                               on_remote_root=lambda rr: _remote_root_holder.__setitem__("v", rr))
    finally:
        # Cleanup workdir distant best-effort dans TOUS les chemins (succes,
        # echec, exception inattendue). Evite les workdirs orphelins qui
        # remplissent le quota cluster (cf. audit phase 2).
        rr = _remote_root_holder.get("v")
        if rr:
            try:
                _ssh(f"rm -rf {rr}", timeout=30)
            except Exception:
                pass


# Holder mutable au scope module : permet a la fonction inner de communiquer
# remote_root vers le finally du wrapper sans avoir a refactorer toute la
# signature. Reset a chaque appel via _remote_root_holder.clear().
_remote_root_holder: Dict[str, str] = {}


def _run_job_cluster_inner(db_path, job_id, project_root, job, config,
                           output_dir_local, t_start, on_remote_root):
    """Logique principale du job cluster. Le wrapper run_job_cluster gere
    le cleanup remote en finally. Toute exception ici remonte au wrapper
    qui marque le job failed et nettoie."""
    _remote_root_holder.clear()
    # ---------- 0. Test de vie cluster + recuperation de $HOME ----------
    jobs.update_job(db_path, job_id, state="running",
                    current_stage="cluster_check", progress=0.01)
    alive, msg_or_home = check_cluster_alive()
    if not alive:
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"Cluster indisponible : {msg_or_home}",
                        duration_s=time.time() - t_start)
        return
    remote_home = msg_or_home

    # ---------- 1. Workdir distant + upload graph ----------
    # Paths absolus (pas de ~) pour que shlex.quote() fonctionne :
    # bash n'etend pas ~ dans des single quotes.
    remote_root = f"{remote_home}/_designer_cluster_jobs/{job_id}"
    on_remote_root(remote_root)  # signale au finally
    remote_output = f"{remote_root}/output"
    remote_graph = f"{remote_root}/input.graph"

    jobs.update_job(db_path, job_id, current_stage="cluster_upload", progress=0.03)

    graph_local = output_dir_local / "input.graph"
    graph_local.write_text(job.get("graph_content", ""), encoding="utf-8")

    # Test du benzenoide d'entree LOCALEMENT, comme en mode local.
    # ingest_local_job lira ensuite output_dir_local/original/ et stockera
    # le bloc dans summary['original']. ~5-15s, best-effort.
    # Skip si test_original=False dans la config.
    if job.get("config", {}).get("test_original", False):
        jobs.update_job(db_path, job_id, current_stage="original", progress=0.04)
        try:
            _test_original_benzenoid(graph_local, output_dir_local, project_root)
        except Exception:
            pass

    try:
        r = _ssh(f"mkdir -p {remote_output}", timeout=30)
    except subprocess.TimeoutExpired:
        jobs.update_job(db_path, job_id, state="failed",
                        error="Timeout mkdir distant",
                        duration_s=time.time() - t_start)
        return
    if r.returncode != 0:
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"Echec mkdir distant : {r.stderr[:200]}",
                        duration_s=time.time() - t_start)
        return

    try:
        r = _scp(str(graph_local), f"{CLUSTER_HOST}:{remote_graph}", timeout=60)
    except subprocess.TimeoutExpired:
        jobs.update_job(db_path, job_id, state="failed",
                        error="Timeout scp upload",
                        duration_s=time.time() - t_start)
        return
    if r.returncode != 0:
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"Echec scp upload : {r.stderr[:200]}",
                        duration_s=time.time() - t_start)
        return

    # ---------- 2. Subprocess SSH avec stream stdout ----------
    jobs.update_job(db_path, job_id, current_stage="cluster_running", progress=0.05)

    remote_cmd = _build_remote_command(config, remote_graph, remote_output)
    try:
        proc = subprocess.Popen(
            ["ssh", CLUSTER_HOST, remote_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"Echec lancement ssh : {e}",
                        duration_s=time.time() - t_start)
        return
    jobs.update_job(db_path, job_id, pid=proc.pid)

    stdout_lines = []
    last_progress = 0.05
    try:
        for line in proc.stdout:
            stdout_lines.append(line.rstrip())
            if len(stdout_lines) > 500:
                stdout_lines = stdout_lines[-500:]
            for stage, pattern, prog in _STAGE_MARKERS:
                if pattern.match(line) and prog > last_progress:
                    last_progress = prog
                    jobs.update_job(db_path, job_id,
                                    current_stage=f"cluster_{stage}",
                                    progress=prog)
                    break
        rc = proc.wait()
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"Erreur stream stdout ssh : {e}",
                        duration_s=time.time() - t_start, pid=None)
        return

    duration_now = time.time() - t_start

    # Verifier que le job n'a pas ete annule entre-temps.
    # Cleanup remote gere par le finally du wrapper, plus besoin ici.
    current = jobs.get_job(db_path, job_id)
    if current and current.get("state") == "cancelled":
        jobs.update_job(db_path, job_id, duration_s=duration_now, pid=None)
        return

    if rc != 0:
        error_tail = "\n".join(stdout_lines[-30:])
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"main.py cluster exit {rc}\n\n{error_tail}",
                        duration_s=duration_now, pid=None,
                        summary={"return_code": rc,
                                 "stdout_tail": stdout_lines[-50:]})
        return

    # ---------- 3. Rapatriement scp ----------
    jobs.update_job(db_path, job_id, current_stage="cluster_download", progress=0.90)

    try:
        r = _scp(f"{CLUSTER_HOST}:{remote_output}/",
                 str(output_dir_local.parent),
                 recursive=True, timeout=600)
    except subprocess.TimeoutExpired:
        jobs.update_job(db_path, job_id, state="failed",
                        error="Timeout scp download (>10 min)",
                        duration_s=time.time() - t_start, pid=None)
        return
    if r.returncode != 0:
        jobs.update_job(db_path, job_id, state="failed",
                        error=f"Echec scp download : {r.stderr[:200]}",
                        duration_s=time.time() - t_start, pid=None)
        return
    _merge_scp_output(output_dir_local.parent, output_dir_local)

    # ---------- 4. Planarite locale + ingestion DB ----------
    jobs.update_job(db_path, job_id, current_stage="aggregate", progress=0.95)
    try:
        n_planarity = _compute_solutions_planarity(output_dir_local, project_root)
    except Exception:
        n_planarity = 0
    # Capture les counts fs AVANT ingest_local_job (qui supprime le workdir).
    outputs = _count_outputs(output_dir_local)
    try:
        ingest_stats = solutions_db.ingest_local_job(
            db_path, job_id, output_dir_local, project_root,
            threshold_deg=PLANARITY_THRESHOLD_DEG)
        ingest_complete = ingest_stats["n_failed"] == 0
    except Exception:
        ingest_stats = {"n_ingested": 0, "n_failed": -1, "total": 0,
                        "original": None, "workdir_deleted": False}
        ingest_complete = False

    # ---------- 5. Cleanup workdir distant : gere par le finally du wrapper ----------

    duration = time.time() - t_start
    summary = {
        "return_code": 0,
        "stdout_tail": stdout_lines[-50:],
        "n_planarity_computed": n_planarity,
        "n_ingested_db": ingest_stats["n_ingested"],
        "n_failed_db": ingest_stats["n_failed"],
        "ingest_complete": ingest_complete,
        "workdir_deleted": ingest_stats.get("workdir_deleted", False),
        "original": ingest_stats.get("original"),
        "cluster": True,
        "cluster_host": CLUSTER_HOST,
        **outputs,
    }
    jobs.update_job(db_path, job_id, state="success",
                    current_stage="done", progress=1.0,
                    duration_s=duration, pid=None, summary=summary)
