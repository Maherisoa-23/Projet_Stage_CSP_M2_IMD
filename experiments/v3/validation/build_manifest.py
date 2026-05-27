"""Construit un manifest JSONL pour la validation par sampling.

Pour chaque (h, config) dans db_v4, on prend N sols aleatoires parmi celles
qui ont decision_path='mmff_sure_plan'. Pour chaque sol, on note le
source.xyz key (chemin logique du source.xyz dans xyz_files) qu'on extraira
dans run_one.py.

Usage :
    python -m experiments.v3.validation.build_manifest \\
        --db /home/.../csp_viewer/db_v4.db \\
        --n-per-bucket 500 \\
        --output /home/.../validation_run/manifest.jsonl \\
        [--seed 42]
"""

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[3]))
    __package__ = "experiments.v3.validation"


def sample_manifest(db_path: str, n_per_bucket: int, seed: int = 42,
                     embed_db_path: str | None = None) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Buckets = (h, config) ou il y a des mmff_sure_plan
    buckets = list(cur.execute(
        "SELECT h, config, COUNT(*) AS n FROM solutions "
        "WHERE decision_path='mmff_sure_plan' "
        "GROUP BY h, config ORDER BY h, config"
    ))

    rng = random.Random(seed)
    entries = []
    for h, config, total in buckets:
        # Recupere TOUS les ids et sample en Python (ORDER BY RANDOM est trop
        # cher sur sqlite). Sur ~M lignes, fetchall est rapide en RAM.
        ids = [r[0] for r in cur.execute(
            "SELECT id FROM solutions "
            "WHERE h=? AND config=? AND decision_path='mmff_sure_plan'",
            (h, config)
        )]
        rng.shuffle(ids)
        sampled_ids = ids[:n_per_bucket]
        # Recharge les infos completes
        for sol_id in sampled_ids:
            r = cur.execute(
                "SELECT id, h, config, mol, sol_idx, sol_dir, mmff_angle_deg "
                "FROM solutions WHERE id=?", (sol_id,)
            ).fetchone()
            if r is None:
                continue
            entries.append({
                "job_id": f"val_{r['h']}_{r['config']}_{r['mol']}_{r['sol_idx']}",
                "sol_db_id": r["id"],
                "h": r["h"],
                "config": r["config"],
                "mol": r["mol"],
                "sol_idx": r["sol_idx"],
                "source_xyz_key": f"{r['sol_dir']}/source.xyz",
                "mmff_angle_deg": r["mmff_angle_deg"],
                "db_path": embed_db_path or db_path,
            })
        print(f"  [{h}, {config}] {len(sampled_ids)}/{total} sampled", flush=True)

    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="db_v4.db path (lecture du sampling)")
    ap.add_argument("--n-per-bucket", type=int, default=500)
    ap.add_argument("--output", required=True, help="output manifest.jsonl")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--embed-db-path", default=None,
                     help="chemin db_v4 a embarquer dans le manifest "
                          "(par defaut = --db ; utile si le worker tourne "
                          "depuis un dossier different)")
    args = ap.parse_args()

    print(f"[db] {args.db}", flush=True)
    print(f"[n_per_bucket] {args.n_per_bucket}  seed={args.seed}", flush=True)
    entries = sample_manifest(args.db, args.n_per_bucket, args.seed,
                                embed_db_path=args.embed_db_path)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"\n[output] {out}  ({len(entries)} entries)", flush=True)


if __name__ == "__main__":
    main()
