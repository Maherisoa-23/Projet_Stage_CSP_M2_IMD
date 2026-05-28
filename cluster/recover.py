"""
Relance ciblee : produit un sous-manifest des jobs a refaire selon des
filtres applicables aux job_status.json deja produits.

Cas d'usage typique apres un run cluster :
  - 5 jobs sont sortis en 'failed' -> on veut les retenter
  - 12 jobs sont sortis en 'timeout' -> on les retente avec un timeout plus long
  - on veut juste relancer une molecule precise
  - on veut tout reprendre depuis zero pour une config donnee

Le script :
  1. Charge le manifest d'origine (la verite des jobs a faire)
  2. Pour chaque job du manifest, lit job_status.json (s'il existe)
  3. Applique les filtres demandes
  4. Optionnellement supprime les job_status.json + claims correspondants
     (sinon le worker les sauterait comme 'deja faits')
  5. Ecrit un sous-manifest (--out-manifest) que dispatcher.py peut consommer

Usage :
    python recover.py --manifest M --output-root DIR \\
        [--claims-dir DIR] [--out-manifest FILE] \\
        [--status STATUS[,STATUS...]] [--mol NAME] [--config NAME] \\
        [--reset]

Exemples :
    # Generer un sous-manifest des jobs failed/timeout (sans toucher au disque)
    python recover.py --manifest manifest_h6.jsonl \\
        --output-root output \\
        --status failed,timeout \\
        --out-manifest manifest_h6_retry.jsonl

    # Idem + reset (supprime job_status.json + locks pour forcer la relance)
    python recover.py --manifest manifest_h6.jsonl \\
        --output-root output --claims-dir cluster_state/claims \\
        --status failed,timeout \\
        --out-manifest manifest_h6_retry.jsonl \\
        --reset

    # Relancer une molecule specifique sur toutes les configs
    python recover.py --manifest manifest_h6.jsonl --output-root output \\
        --mol 0-5-6-11-12 \\
        --out-manifest manifest_redo_0-5-6-11-12.jsonl --reset
"""

import argparse
import json
import sys
from pathlib import Path


def load_manifest(path):
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def write_manifest(entries, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def load_job_status(entry, output_root):
    """Retourne le dict job_status.json ou None si absent."""
    status_path = (Path(output_root) / entry["h"] / entry["config"]
                   / entry["mol"] / "job_status.json")
    if not status_path.exists():
        return None
    try:
        with open(status_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def matches_filters(entry, status_dict, status_set, mol, config):
    """Decide si un job du manifest correspond aux filtres demandes.

    Args:
        entry        : dict du manifest (job_id, h, config, mol, graph)
        status_dict  : dict job_status.json (peut etre None si jamais lance)
        status_set   : set des statuts a retenir (ex. {'failed', 'timeout'}).
                       Cas particulier : 'never_run' pour les jobs jamais lances.
                       None -> pas de filtre status.
        mol          : nom de molecule a retenir (str ou None)
        config       : nom de config a retenir (str ou None)

    Le job est retenu si TOUS les filtres specifies matchent (ET logique).
    """
    if mol and entry["mol"] != mol:
        return False
    if config and entry["config"] != config:
        return False
    if status_set is not None:
        if status_dict is None:
            current_status = "never_run"
        else:
            current_status = status_dict.get("status", "unknown")
        if current_status not in status_set:
            return False
    return True


def reset_job_artifacts(entry, output_root, claims_dir):
    """Supprime job_status.json + claim/<job_id>.lock pour permettre la relance.

    Le reste du dossier (sol_*, md_validation/...) est conserve : seul
    job_status.json sert de signal "deja tente". Sans lui, un worker
    revisitera le job et ecrasera ses anciens fichiers.
    """
    n = 0
    status_path = (Path(output_root) / entry["h"] / entry["config"]
                   / entry["mol"] / "job_status.json")
    if status_path.exists():
        try:
            status_path.unlink()
            n += 1
        except OSError:
            pass

    if claims_dir:
        lock_path = Path(claims_dir) / f"{entry['job_id']}.lock"
        if lock_path.exists():
            try:
                lock_path.unlink()
                n += 1
            except OSError:
                pass
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--manifest", required=True,
                        help="Manifest d'origine (input)")
    parser.add_argument("--output-root", required=True,
                        help="Racine des resultats (pour lire job_status.json)")
    parser.add_argument("--claims-dir", default=None,
                        help="Dossier des claims (pour --reset)")
    parser.add_argument("--out-manifest", default=None,
                        help="Sous-manifest a ecrire. Defaut : "
                             "<manifest_stem>_retry.jsonl")
    parser.add_argument("--status", default=None,
                        help="Statuts a retenir, separes par virgule "
                             "(ex. 'failed,timeout' ou 'never_run'). Sans ce "
                             "filtre, tous les jobs du manifest sont candidats.")
    parser.add_argument("--mol", default=None,
                        help="Filtre sur le nom de molecule")
    parser.add_argument("--config", default=None,
                        help="Filtre sur le nom de config")
    parser.add_argument("--reset", action="store_true",
                        help="Supprime les job_status.json + claims pour "
                             "permettre la relance par les workers")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"ERREUR: manifest introuvable : {manifest_path}", file=sys.stderr)
        sys.exit(2)

    out_path = Path(args.out_manifest) if args.out_manifest \
        else manifest_path.with_name(manifest_path.stem + "_retry.jsonl")

    status_set = None
    if args.status:
        status_set = {s.strip() for s in args.status.split(",") if s.strip()}

    print(f"=== recover ===", flush=True)
    print(f"  manifest    : {manifest_path}", flush=True)
    print(f"  output_root : {args.output_root}", flush=True)
    if status_set:
        print(f"  filtre status : {sorted(status_set)}", flush=True)
    if args.mol:
        print(f"  filtre mol    : {args.mol}", flush=True)
    if args.config:
        print(f"  filtre config : {args.config}", flush=True)
    print(f"  out_manifest : {out_path}", flush=True)
    print(f"  reset       : {args.reset}", flush=True)

    entries = load_manifest(manifest_path)
    print(f"\n  {len(entries)} jobs dans le manifest d'origine", flush=True)

    # Filtrer
    selected = []
    by_status = {"ok": 0, "failed": 0, "timeout": 0, "never_run": 0, "other": 0}
    for entry in entries:
        status_dict = load_job_status(entry, args.output_root)
        st = status_dict.get("status") if status_dict else "never_run"
        if st in by_status:
            by_status[st] += 1
        else:
            by_status["other"] += 1

        if matches_filters(entry, status_dict, status_set, args.mol, args.config):
            selected.append(entry)

    print(f"\n  Distribution actuelle :", flush=True)
    for k, v in by_status.items():
        if v:
            print(f"    {k:<10} : {v}", flush=True)

    print(f"\n  {len(selected)} jobs selectionnes pour relance", flush=True)

    if not selected:
        print("  Rien a relancer.", flush=True)
        return

    # Reset si demande
    if args.reset:
        n_files_removed = 0
        for entry in selected:
            n_files_removed += reset_job_artifacts(entry, args.output_root,
                                                    args.claims_dir)
        print(f"\n  reset : {n_files_removed} fichier(s) supprime(s) "
              f"(job_status.json + locks)", flush=True)

    # Ecrire le sous-manifest
    write_manifest(selected, out_path)
    print(f"\n  -> {out_path} ({len(selected)} jobs)", flush=True)
    print(f"\n  Pour relancer :", flush=True)
    print(f"    python cluster/dispatcher.py start --mode <local|ssh> ... \\", flush=True)
    print(f"      --manifest {out_path}", flush=True)


if __name__ == "__main__":
    main()
