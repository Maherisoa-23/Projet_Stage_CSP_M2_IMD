"""
Libere les locks orphelins du dossier claims/.

Un lock est considere orphelin si :
  - mtime > --max-age-min minutes (defaut 30 min)
  - ET le job_status.json correspondant n'existe pas
    (= le worker qui le tenait est mort sans terminer)

Les locks recents sont preserves : un job xTB long et legitime peut
prendre 20-30 min, on ne veut pas le reattribuer abusivement.

A executer :
  - au demarrage du dispatcher (avant de relancer les workers)
  - periodiquement (cron ?) si les runs sont longs

Usage :
    python recover_stale.py --claims-dir DIR --output-root DIR \\
        [--max-age-min MIN] [--dry-run]

Exemple :
    python recover_stale.py \\
        --claims-dir /home/.../claims \\
        --output-root /home/.../output \\
        --max-age-min 30
"""

import argparse
import sys
import time
from pathlib import Path


def find_stale_locks(claims_dir, output_root, max_age_sec):
    """Identifie les locks orphelins.

    Returns:
        list of (lock_path, age_sec, reason) pour les locks a supprimer
    """
    claims_dir = Path(claims_dir)
    output_root = Path(output_root)
    if not claims_dir.is_dir():
        return []

    now = time.time()
    stale = []

    for lock_path in claims_dir.glob("*.lock"):
        # Le job_id du lock est <h>_<config>_<mol>
        job_id = lock_path.stem
        # On reconstruit le path du status. Note : le job_id est compose
        # de h_config_mol mais config peut contenir des '_' (multi-flags).
        # Le split est ambigu en general, donc on cherche en glob.
        # On accepte le cout : peu de locks a verifier en pratique.
        h = job_id.split("_", 1)[0]   # premiere partie = h
        # Suite : on cherche un job_status.json dans output_root/h/*/<mol>/
        # ou mol = derniere partie. Pour eviter les ambiguites on glob.
        mol_candidates = list((output_root / h).glob("*/" + _extract_mol(job_id, h) + "/job_status.json"))
        has_status = bool(mol_candidates)

        age = now - lock_path.stat().st_mtime
        if has_status:
            # Lock obsolete : le job a abouti (ok ou failed). On peut
            # supprimer le lock pour faire le menage.
            stale.append((lock_path, age, "completed"))
        elif age > max_age_sec:
            stale.append((lock_path, age, "orphan"))

    return stale


def _extract_mol(job_id, h):
    """Extrait la partie 'mol' du job_id.

    job_id = h_config_mol. On enleve le prefixe h_ puis tout ce qui
    matche les flags CSP connus. Le reste est mol.
    """
    s = job_id[len(h) + 1:]   # enleve "h_"
    # Les configs possibles (suffixes a supprimer du debut de s)
    valid_flags = {"adj-57", "no-freeze", "no-table"}
    # Essayer chaque longueur de prefixe possible (de 'default' a la concat de 3 flags)
    candidates = ["default"] + [
        "_".join(c) for r in range(1, 4)
        for c in __import__("itertools").combinations(sorted(valid_flags), r)
    ]
    # Tester par ordre de longueur decroissante (matching maximal)
    for cfg in sorted(candidates, key=len, reverse=True):
        prefix = cfg + "_"
        if s.startswith(prefix):
            return s[len(prefix):]
    # Fallback : tout ce qui suit le premier "_"
    return s.split("_", 1)[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--claims-dir", required=True,
                        help="Dossier des fichiers de lock")
    parser.add_argument("--output-root", required=True,
                        help="Racine de l'arborescence de sortie (pour verifier "
                             "l'existence des job_status.json)")
    parser.add_argument("--max-age-min", type=int, default=30,
                        help="Age max d'un lock sans status (defaut 30 min)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Liste les locks a supprimer sans les supprimer")
    args = parser.parse_args()

    max_age_sec = args.max_age_min * 60
    stale = find_stale_locks(args.claims_dir, args.output_root, max_age_sec)

    if not stale:
        print(f"Aucun lock orphelin (max_age={args.max_age_min} min).")
        return

    print(f"Trouves : {len(stale)} lock(s) a liberer")
    n_orphan = sum(1 for _, _, r in stale if r == "orphan")
    n_completed = sum(1 for _, _, r in stale if r == "completed")
    print(f"  - {n_orphan} orphelins (worker mort)")
    print(f"  - {n_completed} completes (job termine, lock obsolete)")

    for lock_path, age, reason in stale:
        age_min = age / 60
        action = "[DRY-RUN]" if args.dry_run else "[DELETE]"
        print(f"  {action} {lock_path.name} (age={age_min:.1f} min, {reason})")
        if not args.dry_run:
            try:
                lock_path.unlink()
            except OSError as e:
                print(f"    ATTENTION: suppression echouee : {e}", file=sys.stderr)

    if args.dry_run:
        print(f"\n(dry-run : aucun fichier supprime, relance sans --dry-run)")


if __name__ == "__main__":
    main()
