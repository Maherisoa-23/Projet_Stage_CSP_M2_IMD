"""
Execute UN seul (graph, config) en isolation : c'est l'unite atomique de
calcul appelee par les workers cluster. En local, peut aussi etre invoque
directement pour tester un job individuel.

Pipeline :
  1. Cree un dossier scratch local (par defaut /tmp ou %TEMP%)
  2. Copie le .graph depuis l'arbre source vers le scratch local
  3. Lance test.py (original tout-6 via --opt) dans le scratch
  4. Lance main.py --validate --method md (CSP + reconstruction + MD)
     dans le scratch, avec les flags de la config demandee
  5. Copie le dossier resultat scratch -> output_root (NFS sur cluster)
  6. Ecrit job_status.json a cote du resultat
  7. Nettoie le scratch (try/finally, garanti meme en cas d'echec)

Avantage cluster : pendant les ~5 min du job, ZERO octet n'est ecrit sur
le NFS partage. xTB tape sur le scratch local (souvent /tmp = tmpfs ou
disque local rapide). Une seule grosse copie groupee a la fin remonte
les resultats.

Avantage idempotence : si le job crashe a mi-parcours, le scratch est
jete et le NFS n'a rien recu. A la relance, l'absence de
job_status.json indique que ce job doit etre refait.

Usage :
    python run_one_job.py --graph PATH --config NAME \\
        --output-root DIR [--scratch-root DIR] [--timeout SEC] \\
        [--no-cleanup]

Exemple en local :
    python run_one_job.py \\
        --graph plane/benzdb/h3/1-3-4.graph \\
        --config default \\
        --output-root /tmp/test_output

Exemple sur cluster (worker, depuis csp_solver/experiments/) :
    python run_one_job.py \\
        --graph /home/.../plane/benzdb/h6/0-5-6-11-12.graph \\
        --config no-freeze \\
        --output-root /home/.../output \\
        --scratch-root /tmp/coala_scratch
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Force le single-thread pour toutes les libs scientifiques (xTB, BLAS, MKL...).
# Indispensable en cluster ou chaque coeur execute un job xTB independant.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

# Flags CSP valides (sans le prefixe --). Doit rester synchronise avec
# CSP_FLAGS de batch_main.py / batch_all.py.
VALID_CSP_FLAGS = {"no-freeze", "no-table", "adj-57"}


def config_name_to_flags(config_name):
    """Convertit un nom de config (ex. 'no-freeze_adj-57') en liste de flags
    CLI (ex. ['--no-freeze', '--adj-57']).

    'default' -> [] (aucun flag).
    """
    if config_name == "default":
        return []
    flags = []
    for part in config_name.split("_"):
        if part not in VALID_CSP_FLAGS:
            raise ValueError(
                f"Flag inconnu dans config '{config_name}': '{part}'. "
                f"Valides : {sorted(VALID_CSP_FLAGS)}"
            )
        flags.append(f"--{part}")
    return flags


def make_job_id(graph_path, config_name):
    """Identifiant unique pour ce job. Inclut PID + microsecondes pour
    eviter toute collision si plusieurs jobs sur la meme machine demarrent
    a la meme seconde sur le meme (graph, config).
    """
    h_name = graph_path.parent.name           # ex. "h6"
    mol_name = graph_path.stem                 # ex. "0-5-6-11-12"
    ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return f"{h_name}_{config_name}_{mol_name}_{os.getpid()}_{ts}"


def count_results(mol_dir):
    """Compte les solutions produites dans mol_dir/solutions/.

    Returns:
        (n_sol_dirs, n_md_outputs) :
            n_sol_dirs    : nombre de sous-dossiers sol_*/
            n_md_outputs  : nombre de md_validation/md_final_opt.xyz produits
    """
    sol_root = mol_dir / "solutions"
    if not sol_root.is_dir():
        return 0, 0
    sol_dirs = [d for d in sol_root.iterdir()
                if d.is_dir() and d.name.startswith("sol_")]
    n_md = sum(1 for d in sol_dirs
               if (d / "md_validation" / "md_final_opt.xyz").exists())
    return len(sol_dirs), n_md


def write_job_status(mol_dir, status):
    """Ecrit job_status.json (signal de fin sur le NFS).

    L'existence de ce fichier = job termine (succes ou echec).
    Son absence = job a refaire (jamais lance, ou crashe avant la fin).
    """
    mol_dir.mkdir(parents=True, exist_ok=True)
    status_path = mol_dir / "job_status.json"
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)


def run_subprocess(cmd, timeout, log_prefix=""):
    """Lance une commande, propage stdout/stderr en streaming, retourne
    (returncode, duration_sec). Leve TimeoutExpired si la commande depasse.
    """
    print(f"{log_prefix}$ {' '.join(str(c) for c in cmd)}", flush=True)
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        print(f"{log_prefix}TIMEOUT apres {timeout}s", flush=True)
        raise
    return result.returncode, round(time.time() - t0, 1)


def run_one_job(graph_path, config_name, output_root, scratch_root,
                timeout_sec=3600, cleanup=True):
    """Execute le pipeline complet pour UN (graph, config).

    Args:
        graph_path    : Path vers le .graph d'entree (sera copie dans le scratch)
        config_name   : str, nom de config CSP (ex. 'default', 'no-freeze')
        output_root   : Path racine ou copier les resultats finals
                        (ex. <NFS>/csp_solver/experiments/output)
        scratch_root  : Path racine du scratch local (typ. /tmp)
        timeout_sec   : timeout en secondes pour CHAQUE sous-process
                        (test.py ET main.py separement)
        cleanup       : si False, garde le scratch local pour debug

    Returns:
        dict status (egalement ecrit dans output/.../job_status.json)
    """
    graph_path = Path(graph_path).resolve()
    output_root = Path(output_root).resolve()
    scratch_root = Path(scratch_root).resolve()

    if not graph_path.is_file():
        raise FileNotFoundError(f"Graph introuvable : {graph_path}")

    # Resolution des flags CSP a partir du nom de config
    flags = config_name_to_flags(config_name)

    h_name = graph_path.parent.name           # ex. "h6"
    mol_name = graph_path.stem                 # ex. "0-5-6-11-12"
    job_id = make_job_id(graph_path, config_name)

    # Localisation des scripts source (relativement a ce fichier)
    here = Path(__file__).resolve().parent     # csp_solver/experiments/
    main_py = here.parent / "main.py"
    test_py = here.parent / "test.py"
    if not main_py.is_file():
        raise FileNotFoundError(f"main.py introuvable : {main_py}")

    # Scratch local : sera detruit a la fin (succes OU echec)
    scratch = scratch_root / job_id
    scratch.mkdir(parents=True, exist_ok=True)

    # Status accumule au fur et a mesure
    t_start = time.time()
    status = {
        "job_id": job_id,
        "graph": str(graph_path),
        "config": config_name,
        "h": h_name,
        "mol": mol_name,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "scratch": str(scratch),
    }

    final_mol_dir = output_root / h_name / config_name / mol_name

    print(f"=== Job {job_id} ===", flush=True)
    print(f"  graph    : {graph_path}", flush=True)
    print(f"  config   : {config_name}  (flags={flags or '(aucun)'})", flush=True)
    print(f"  scratch  : {scratch}", flush=True)
    print(f"  output   : {final_mol_dir}", flush=True)

    try:
        # 1. Copier le .graph en local
        graph_local = scratch / graph_path.name
        shutil.copy2(graph_path, graph_local)

        # 2. Preparer le dossier de sortie local (dans le scratch)
        local_mol_dir = scratch / "output" / h_name / config_name / mol_name
        local_mol_dir.mkdir(parents=True, exist_ok=True)

        # 3. test.py (original tout-6 via --opt, comme convenu)
        rc_test, dur_test = run_subprocess(
            [sys.executable, str(test_py), str(graph_local),
             "--output-dir", str(local_mol_dir)],
            timeout=timeout_sec, log_prefix="  [test] ",
        )
        status["test_returncode"] = rc_test
        status["test_duration_sec"] = dur_test
        # rc != 0 sur test.py n'est pas bloquant (l'original peut echouer mais
        # les solutions CSP peuvent quand meme etre valides). On continue.

        # 4. main.py --validate --method md
        sol_dir = local_mol_dir / "solutions"
        sol_dir.mkdir(parents=True, exist_ok=True)
        cmd_main = [sys.executable, str(main_py), str(graph_local),
                    "--validate", "--output-dir", str(sol_dir)] + flags
        rc_main, dur_main = run_subprocess(
            cmd_main, timeout=timeout_sec, log_prefix="  [main] ",
        )
        status["main_returncode"] = rc_main
        status["main_duration_sec"] = dur_main

        if rc_main != 0:
            status["status"] = "failed"
            status["error"] = f"main.py exit code {rc_main}"
            return _finalize(status, t_start, None, mol_dir_for_status=None,
                             output_root=output_root, h_name=h_name,
                             config_name=config_name, mol_name=mol_name)

        # 5. Comptage des resultats locaux (avant la copie vers NFS)
        n_sols, n_md = count_results(local_mol_dir)
        status["n_solutions"] = n_sols
        status["n_md_outputs"] = n_md

        # 6. Copier vers output_root (NFS) en bloc
        # On rmtree d'abord pour eviter le piege Windows ou copytree refuse
        # un dossier existant. C'est OK : si on relance ce job, c'est qu'on
        # veut son resultat frais.
        if final_mol_dir.exists():
            shutil.rmtree(final_mol_dir)
        final_mol_dir.parent.mkdir(parents=True, exist_ok=True)
        t_copy = time.time()
        shutil.copytree(local_mol_dir, final_mol_dir)
        status["copy_duration_sec"] = round(time.time() - t_copy, 1)

        status["status"] = "ok"
        return _finalize(status, t_start, final_mol_dir,
                         mol_dir_for_status=final_mol_dir,
                         output_root=output_root, h_name=h_name,
                         config_name=config_name, mol_name=mol_name)

    except subprocess.TimeoutExpired as e:
        status["status"] = "timeout"
        status["error"] = f"Timeout apres {e.timeout}s sur {' '.join(str(c) for c in (e.cmd or []))[:200]}"
        return _finalize(status, t_start, None,
                         mol_dir_for_status=final_mol_dir,
                         output_root=output_root, h_name=h_name,
                         config_name=config_name, mol_name=mol_name)
    except Exception as e:
        status["status"] = "failed"
        status["error"] = f"{type(e).__name__}: {e}"
        return _finalize(status, t_start, None,
                         mol_dir_for_status=final_mol_dir,
                         output_root=output_root, h_name=h_name,
                         config_name=config_name, mol_name=mol_name)
    finally:
        # 7. Nettoyer le scratch (TOUJOURS, meme en cas d'echec)
        if cleanup:
            shutil.rmtree(scratch, ignore_errors=True)
        else:
            print(f"  [debug] scratch conserve : {scratch}", flush=True)


def _finalize(status, t_start, success_mol_dir, mol_dir_for_status,
              output_root, h_name, config_name, mol_name):
    """Helper : remplit duration_sec, ended_at, ecrit job_status.json,
    affiche le resume."""
    status["duration_sec"] = round(time.time() - t_start, 1)
    status["ended_at"] = datetime.now().isoformat(timespec="seconds")

    # Si on n'a pas de mol_dir cible (echec avant la copie), on ecrit le
    # status quand meme dans output_root/h/config/mol/ pour signaler
    # l'echec au worker. mkdir crée le dossier au besoin.
    if mol_dir_for_status is None:
        mol_dir_for_status = output_root / h_name / config_name / mol_name
    try:
        write_job_status(mol_dir_for_status, status)
    except OSError as e:
        # Si meme l'ecriture du status echoue (NFS down, droits...), on
        # log mais on n'oublie pas le code de retour.
        print(f"  ATTENTION: ecriture job_status.json echouee : {e}", flush=True)

    print(f"=== Fin {status['status'].upper()} ({status['duration_sec']}s) ===",
          flush=True)
    if status['status'] == 'ok':
        print(f"  {status.get('n_solutions', '?')} solutions, "
              f"{status.get('n_md_outputs', '?')} avec md_validation",
              flush=True)
    elif 'error' in status:
        print(f"  ERREUR: {status['error']}", flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(
        description="Execute un seul (graph, config) en isolation scratch local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--graph", required=True,
                        help="Chemin du fichier .graph d'entree")
    parser.add_argument("--config", required=True,
                        help="Nom de config CSP (ex. 'default', 'no-freeze', "
                             "'adj-57_no-freeze_no-table')")
    parser.add_argument("--output-root", required=True,
                        help="Racine de l'arborescence de sortie (NFS sur cluster)")
    parser.add_argument("--scratch-root", default=None,
                        help="Racine du scratch local. Defaut : tempfile.gettempdir() "
                             "(/tmp sur Linux, %%TEMP%% sur Windows)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout en secondes pour test.py et main.py (chacun). "
                             "Defaut : 3600 (1h)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Garde le scratch local apres execution (debug)")
    args = parser.parse_args()

    scratch_root = Path(args.scratch_root) if args.scratch_root else Path(tempfile.gettempdir())

    try:
        status = run_one_job(
            graph_path=Path(args.graph),
            config_name=args.config,
            output_root=Path(args.output_root),
            scratch_root=scratch_root,
            timeout_sec=args.timeout,
            cleanup=not args.no_cleanup,
        )
    except (ValueError, FileNotFoundError) as e:
        # Erreurs de validation des arguments (config invalide, graph
        # introuvable). Message clair, exit non-zero, pas de trace Python.
        print(f"ERREUR: {e}", file=sys.stderr, flush=True)
        sys.exit(2)
    # Code de sortie : 0 si OK, 1 sinon. Permet aux workers de detecter
    # un echec via le returncode sans avoir a parser job_status.json.
    sys.exit(0 if status["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
