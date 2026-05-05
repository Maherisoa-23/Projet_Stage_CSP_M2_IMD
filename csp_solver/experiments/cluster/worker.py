"""
Worker cluster : pull-based consumer du manifest JSONL.

Tourne sur UNE machine du cluster (ou en local pour test). Lance jusqu'a
--concurrency jobs en parallele via subprocess vers run_one_job.py.
Coordination avec les autres workers via creation atomique de fichiers
sur le NFS partage (pattern O_CREAT|O_EXCL).

Algorithme :
    pour chaque entree du manifest (ordre randomise pour minimiser les
    collisions de claim entre workers qui demarrent simultanement) :
        si <output>/<h>/<config>/<mol>/job_status.json existe :
            -> deja tente (succes ou echec) -> SKIP
        sinon :
            tenter de creer claims/<job_id>.lock atomiquement
            si reussi  : submit run_one_job au pool
            si echoue  : un autre worker l'a pris -> SKIP

    quand le manifest est entierement parcouru et le pool vide -> exit.

Pas de boucle de retry interne : si un job sort en 'failed', il restera
'failed' jusqu'a ce que recover.py (etape 4) le selectionne pour relance.

Pas de heartbeat dans ce worker : c'est recover_stale.py qui detecte
les locks orphelins (mtime trop vieux + pas de job_status.json).

Usage :
    python worker.py --manifest FILE --output-root DIR --claims-dir DIR \\
        [--scratch-root DIR] [--concurrency N] [--timeout SEC]

Exemple cluster :
    python worker.py \\
        --manifest /home/.../manifest_h6.jsonl \\
        --output-root /home/.../output \\
        --claims-dir /home/.../claims \\
        --scratch-root /tmp \\
        --concurrency 20

Exemple test local (en parallele dans 2 terminaux differents) :
    python worker.py --manifest test.jsonl --output-root out --claims-dir claims --concurrency 2
"""

import argparse
import errno
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime
from pathlib import Path

# Prefixe utilise par run_one_job.py pour nommer ses scratch dirs.
# Sert ici pour le menage des scratch orphelins.
SCRATCH_PREFIX = "coala_"

# Force le single-thread (heritera dans tous les sous-processus xTB).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


# Localisation de run_one_job.py (1 niveau au-dessus de cluster/)
_HERE = Path(__file__).resolve().parent
RUN_ONE_JOB = _HERE.parent / "run_one_job.py"


def load_manifest(manifest_path):
    """Lit un manifest JSONL et retourne la liste de dicts."""
    entries = []
    with open(manifest_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"ATTENTION: ligne {line_no} ignoree (JSON invalide): {e}",
                      file=sys.stderr)
    return entries


def try_claim(lock_path):
    """Tente de creer lock_path en exclusion mutuelle.

    Utilise O_CREAT|O_EXCL : atomique sur NFS v3+, garanti un seul appel
    reussit en cas de concurrence.

    Returns:
        True si le claim est reussi (ce worker a la responsabilite du job),
        False si le fichier existe deja (un autre worker l'a pris).
    """
    try:
        fd = os.open(str(lock_path),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     0o644)
        info = f"{socket.gethostname()}:{os.getpid()}:{datetime.now().isoformat(timespec='seconds')}\n"
        os.write(fd, info.encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError as e:
        # Cas typique sur NFS si concurrence intense : EEXIST en alias
        if e.errno == errno.EEXIST:
            return False
        # Autre erreur (permission, disque plein...) : on signale
        print(f"ATTENTION: erreur OS sur claim {lock_path}: {e}", file=sys.stderr)
        return False


def cleanup_orphan_scratch(scratch_root, max_age_min=60):
    """Supprime les scratch dirs orphelins (worker precedent crashe).

    Cible : <scratch_root>/<SCRATCH_PREFIX>* dont le mtime est > max_age_min.
    Ne touche pas aux scratch recents (peuvent etre des jobs en cours d'un
    autre worker tournant en parallele sur la meme machine).

    Best-effort : log les erreurs mais ne plante jamais le worker.

    Args:
        scratch_root  : Path racine du scratch (typ. /tmp)
        max_age_min   : age minimum pour qu'un scratch soit considere orphelin
    """
    scratch_root = Path(scratch_root)
    if not scratch_root.is_dir():
        return
    now = time.time()
    cutoff = now - max_age_min * 60
    n_freed = 0
    for d in scratch_root.glob(f"{SCRATCH_PREFIX}*"):
        if not d.is_dir():
            continue
        try:
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                n_freed += 1
        except OSError as e:
            print(f"  ATTENTION: cleanup orphan {d.name}: {e}", file=sys.stderr)
    if n_freed:
        print(f"  cleanup_orphan_scratch : {n_freed} dossier(s) supprime(s)",
              flush=True)


def is_done(entry, output_root):
    """Verifie si ce job a deja ete tente (succes OU echec).

    Critere : presence de job_status.json dans le dossier mol attendu.
    """
    status_path = (Path(output_root) / entry["h"] / entry["config"]
                   / entry["mol"] / "job_status.json")
    return status_path.exists()


def execute_job(entry, output_root, scratch_root, timeout_sec):
    """Lance run_one_job.py en subprocess pour UN job.

    Cette fonction tourne dans un process worker du pool. Elle ne fait
    QUE le subprocess + un peu de logging local. La logique metier
    (scratch, copie, status) est entierement dans run_one_job.py.

    Returns:
        dict {job_id, returncode, duration_sec}
    """
    t0 = time.time()
    cmd = [
        sys.executable, str(RUN_ONE_JOB),
        "--graph", entry["graph"],
        "--config", entry["config"],
        "--output-root", str(output_root),
        "--scratch-root", str(scratch_root),
        "--timeout", str(timeout_sec),
    ]
    try:
        # Timeout englobant : timeout xTB est applique par run_one_job
        # sur chaque sous-process (test.py, main.py). On donne 2x marge ici.
        result = subprocess.run(cmd, timeout=2 * timeout_sec + 60)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        rc = -1  # killed by us
    return {
        "job_id": entry["job_id"],
        "returncode": rc,
        "duration_sec": round(time.time() - t0, 1),
    }


def worker_main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--manifest", required=True,
                        help="Chemin du manifest JSONL")
    parser.add_argument("--output-root", required=True,
                        help="Racine de l'arborescence de sortie (sur NFS)")
    parser.add_argument("--claims-dir", required=True,
                        help="Dossier des fichiers de lock (sur NFS partage)")
    parser.add_argument("--scratch-root", default="/tmp",
                        help="Racine du scratch local (defaut /tmp)")
    parser.add_argument("--concurrency", type=int, default=20,
                        help="Nb de jobs en parallele sur cette machine "
                             "(defaut 20 = nb coeurs Precision 7920)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout par sous-process (test.py, main.py) en secondes")
    parser.add_argument("--shuffle-seed", type=int, default=None,
                        help="Seed pour shuffle du manifest (defaut : aleatoire). "
                             "Le shuffle reduit les collisions de claim entre workers.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    output_root = Path(args.output_root).resolve()
    claims_dir = Path(args.claims_dir).resolve()
    scratch_root = Path(args.scratch_root).resolve()

    if not manifest_path.is_file():
        print(f"ERREUR: manifest introuvable : {manifest_path}", file=sys.stderr)
        sys.exit(2)
    if not RUN_ONE_JOB.is_file():
        print(f"ERREUR: run_one_job.py introuvable : {RUN_ONE_JOB}", file=sys.stderr)
        sys.exit(2)

    claims_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)

    # Menage des scratch orphelins d'un worker precedent qui aurait crashe.
    # Important sur COALA : /tmp = NVMe local 9 Go partage entre utilisateurs.
    cleanup_orphan_scratch(scratch_root, max_age_min=60)

    host = socket.gethostname()
    pid = os.getpid()
    print(f"=== Worker {host}:{pid} demarre ===", flush=True)
    print(f"  manifest    : {manifest_path}", flush=True)
    print(f"  output_root : {output_root}", flush=True)
    print(f"  claims_dir  : {claims_dir}", flush=True)
    print(f"  scratch     : {scratch_root}", flush=True)
    print(f"  concurrency : {args.concurrency}", flush=True)

    entries = load_manifest(manifest_path)
    print(f"  manifest    : {len(entries)} jobs au total", flush=True)

    # Shuffle pour minimiser les collisions entre workers qui demarrent
    # en meme temps. Chaque worker pioche dans un ordre different.
    rng = random.Random(args.shuffle_seed)
    rng.shuffle(entries)

    n_skip_done = 0
    n_skip_locked = 0
    n_submitted = 0
    n_ok = 0
    n_failed = 0

    pending = set()
    iter_entries = iter(entries)
    no_more = False
    t_start = time.time()

    pool = ProcessPoolExecutor(max_workers=args.concurrency)
    try:
        while True:
            # Remplir le pool tant qu'il y a de la place ET des jobs a claim
            while not no_more and len(pending) < args.concurrency:
                try:
                    entry = next(iter_entries)
                except StopIteration:
                    no_more = True
                    break

                if is_done(entry, output_root):
                    n_skip_done += 1
                    continue

                lock_path = claims_dir / f"{entry['job_id']}.lock"
                if not try_claim(lock_path):
                    n_skip_locked += 1
                    continue

                future = pool.submit(execute_job, entry,
                                     output_root, scratch_root, args.timeout)
                pending.add(future)
                n_submitted += 1
                print(f"  [submit] {entry['job_id']} "
                      f"(en cours: {len(pending)}, soumis total: {n_submitted})",
                      flush=True)

            if not pending:
                # Pool vide ET plus rien a claim -> termine
                break

            # Attendre qu'au moins 1 job termine
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    res = fut.result()
                    if res["returncode"] == 0:
                        n_ok += 1
                        marker = "[ok]"
                    else:
                        n_failed += 1
                        marker = f"[FAIL rc={res['returncode']}]"
                    print(f"  {marker} {res['job_id']} ({res['duration_sec']}s)",
                          flush=True)
                except Exception as e:
                    n_failed += 1
                    print(f"  [CRASH] worker exception: {e}", flush=True)

    finally:
        pool.shutdown(wait=True)

    duration = round(time.time() - t_start, 1)
    print(f"\n=== Worker {host}:{pid} termine ({duration}s) ===", flush=True)
    print(f"  Jobs soumis    : {n_submitted}", flush=True)
    print(f"  Reussis        : {n_ok}", flush=True)
    print(f"  Echecs         : {n_failed}", flush=True)
    print(f"  Skip (deja faits) : {n_skip_done}", flush=True)
    print(f"  Skip (claimes)    : {n_skip_locked}", flush=True)


if __name__ == "__main__":
    worker_main()
