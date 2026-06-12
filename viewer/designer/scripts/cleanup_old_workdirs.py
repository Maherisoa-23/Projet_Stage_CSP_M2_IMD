"""Purge les workdirs designer dont les resultats sont deja en DB.

Itere les jobs designer en etat 'success' ET summary.ingest_complete=True
ET dont output_dir existe encore sur le filesystem. Supprime ces output_dirs
(leurs XYZ sont deja en xyz_files gzippes, leurs metriques en
designer_solutions).

Par defaut DRY-RUN : affiche ce qui SERAIT supprime, sans rien toucher.
Passer --apply pour effectivement supprimer.

Usage :
    python tmp/cleanup_old_designer_workdirs.py [--db PATH] [--apply]

Defaults :
    --db     experiments/v1/db_v2.db
    sans --apply : dry-run

Securite :
  - On ne touche QUE les jobs qui ont explicitement summary.ingest_complete=True
    -> les jobs pre-phase-2 (ingest_complete absent) sont epargnes
  - On ne touche QUE les dossiers contenant 'designer_jobs/' dans leur chemin
    -> garde-fou contre une erreur de path
  - On n'efface pas la row du job dans designer_jobs (l'historique reste)
"""

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="experiments/v1/db_v2.db",
                    help="Chemin de la DB sqlite (defaut: experiments/v1/db_v2.db)")
    ap.add_argument("--apply", action="store_true",
                    help="Effectivement supprimer (sinon dry-run)")
    ap.add_argument("--project-root", default=".",
                    help="Racine du projet (pour resoudre output_dir relatifs)")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERREUR : DB introuvable : {db_path}", file=sys.stderr)
        return 1

    project_root = Path(args.project_root).resolve()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Cleanup designer workdirs ({mode}) ===")
    print(f"DB           : {db_path}")
    print(f"Project root : {project_root}")
    print()

    n_eligible = 0
    n_already_gone = 0
    n_skipped_no_flag = 0
    n_deleted = 0
    total_bytes = 0

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT job_id, state, output_dir, summary_json "
            "FROM designer_jobs WHERE state = 'success'"
        ).fetchall()

    for r in rows:
        job_id = r["job_id"]
        output_dir_rel = r["output_dir"]
        if not output_dir_rel:
            continue
        try:
            summary = json.loads(r["summary_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            summary = {}

        if not summary.get("ingest_complete"):
            n_skipped_no_flag += 1
            continue

        output_dir = (project_root / output_dir_rel).resolve()
        # Garde-fou : doit etre sous project_root ET contenir 'designer_jobs'
        try:
            output_dir.relative_to(project_root)
        except ValueError:
            print(f"  ! skip {job_id} : output_dir hors project_root ({output_dir})")
            continue
        if "designer_jobs" not in output_dir.parts:
            print(f"  ! skip {job_id} : output_dir ne contient pas 'designer_jobs'")
            continue

        if not output_dir.is_dir():
            n_already_gone += 1
            continue

        n_eligible += 1
        size_bytes = sum(
            f.stat().st_size for f in output_dir.rglob("*") if f.is_file()
        )
        total_bytes += size_bytes
        size_mb = size_bytes / (1024 * 1024)
        print(f"  {job_id} : {output_dir_rel} ({size_mb:.2f} MB)")

        if args.apply:
            try:
                shutil.rmtree(output_dir)
                n_deleted += 1
            except OSError as e:
                print(f"    ECHEC : {e}")

    print()
    print(f"Eligible  : {n_eligible} workdir(s), {total_bytes / (1024*1024):.2f} MB cumules")
    print(f"Deja vide : {n_already_gone} (rien a faire)")
    print(f"Ignores   : {n_skipped_no_flag} (ingest_complete absent -> safe)")
    if args.apply:
        print(f"Supprimes : {n_deleted}")
    else:
        print(f"Mode DRY-RUN : aucun fichier touche.")
        if n_eligible > 0:
            print(f"  -> Pour appliquer : python tmp/cleanup_old_designer_workdirs.py "
                  f"--db {args.db} --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
