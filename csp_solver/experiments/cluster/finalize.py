"""
Finalisation post-cluster : agrege les resultats de tous les workers en
data.json par config + view.html + cluster_meta.json (stats globales).

Pre-requis : tous les jobs sont termines (ou on accepte les manquants).
La presence de job_status.json par molecule indique qu'un job a ete tente.

Pipeline :
  1. Scanne output/<hX>/<config>/<mol>/job_status.json -> stats par job
  2. Pour chaque <config>/ : appelle aggregate_md.py (deja additif et resilient)
  3. Genere view.html agrege au niveau hX (via view.py --aggregate)
  4. Ecrit cluster_meta.json (stats globales + per-host + manquants)

Comparaison avec batch_all.py : meme final, mais sans avoir lance les batchs
sequentiellement. Le data.json produit a le meme format et est compatible
avec le viewer existant.

Usage :
    python finalize.py <hX_dir> [--manifest FILE] [--no-aggregate] [--no-view]

Exemples :
    python finalize.py output/h6
    python finalize.py output/h6 --manifest manifest_h6.jsonl
    python finalize.py output/h6 --no-view   # skip view.html (utile en debug)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Local import : meme dossier
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_io import write_atomic_json


# Localisation des scripts existants (1 niveau au-dessus de cluster/)
_HERE = Path(__file__).resolve().parent
AGGREGATE_MD = _HERE.parent / "aggregate_md.py"
VIEW_PY = _HERE.parent / "view.py"


def collect_job_statuses(h_dir):
    """Scanne <h_dir>/<config>/<mol>/job_status.json et retourne la liste
    des dicts. Tolere les fichiers absents ou corrompus.

    Returns:
        list[dict] : un par job_status.json trouve
    """
    statuses = []
    h_dir = Path(h_dir)
    for status_path in h_dir.glob("*/*/job_status.json"):
        try:
            with open(status_path, encoding="utf-8") as f:
                statuses.append(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ATTENTION: impossible de lire {status_path}: {e}",
                  file=sys.stderr)
    return statuses


def compute_stats(statuses, expected_jobs=None):
    """Calcule les stats globales et per-host depuis la liste des statuses.

    Args:
        statuses     : list[dict] retourne par collect_job_statuses
        expected_jobs : list[dict] du manifest (pour identifier les missing).
                        Format : [{job_id, h, config, mol}, ...]

    Returns:
        dict avec : n_total_done, n_ok, n_failed, n_timeout, n_missing,
                    duration_total_sec, per_host, missing_job_ids,
                    failed_job_ids, n_solutions_total, n_md_outputs_total
    """
    n_ok = sum(1 for s in statuses if s.get("status") == "ok")
    n_failed = sum(1 for s in statuses if s.get("status") == "failed")
    n_timeout = sum(1 for s in statuses if s.get("status") == "timeout")
    n_other = len(statuses) - n_ok - n_failed - n_timeout

    # Durees par host
    per_host = defaultdict(lambda: {"n_jobs": 0, "duration_sum": 0.0,
                                     "n_ok": 0, "n_failed": 0})
    for s in statuses:
        host = s.get("host", "unknown")
        per_host[host]["n_jobs"] += 1
        per_host[host]["duration_sum"] += s.get("duration_sec", 0)
        if s.get("status") == "ok":
            per_host[host]["n_ok"] += 1
        else:
            per_host[host]["n_failed"] += 1

    # Convertir en dict et ajouter avg
    per_host_out = {}
    for host, st in per_host.items():
        n = st["n_jobs"]
        per_host_out[host] = {
            "n_jobs": n,
            "n_ok": st["n_ok"],
            "n_failed": st["n_failed"],
            "duration_avg_sec": round(st["duration_sum"] / n, 1) if n else 0,
            "duration_total_sec": round(st["duration_sum"], 1),
        }

    # Wall-clock global : max(ended_at) - min(started_at)
    started_ats = [s.get("started_at") for s in statuses if s.get("started_at")]
    ended_ats = [s.get("ended_at") for s in statuses if s.get("ended_at")]
    wall_clock_sec = None
    if started_ats and ended_ats:
        try:
            t_start = min(datetime.fromisoformat(t) for t in started_ats)
            t_end = max(datetime.fromisoformat(t) for t in ended_ats)
            wall_clock_sec = round((t_end - t_start).total_seconds(), 1)
        except ValueError:
            pass

    # Solutions et MD outputs cumules
    n_solutions_total = sum(s.get("n_solutions", 0) for s in statuses
                            if s.get("status") == "ok")
    n_md_outputs_total = sum(s.get("n_md_outputs", 0) for s in statuses
                             if s.get("status") == "ok")

    # Identification des manquants (si manifest fourni)
    missing = []
    if expected_jobs is not None:
        done_keys = {(s.get("h"), s.get("config"), s.get("mol"))
                     for s in statuses}
        for job in expected_jobs:
            key = (job["h"], job["config"], job["mol"])
            if key not in done_keys:
                missing.append(job["job_id"])

    failed_ids = [s["job_id"] for s in statuses
                  if s.get("status") in ("failed", "timeout")]

    return {
        "n_total_done": len(statuses),
        "n_ok": n_ok,
        "n_failed": n_failed,
        "n_timeout": n_timeout,
        "n_other": n_other,
        "n_missing": len(missing),
        "n_solutions_total": n_solutions_total,
        "n_md_outputs_total": n_md_outputs_total,
        "wall_clock_sec": wall_clock_sec,
        "per_host": per_host_out,
        "missing_job_ids": missing,
        "failed_job_ids": failed_ids,
    }


def format_duration(sec):
    if sec is None:
        return "?"
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def run_aggregate_md(config_dir):
    """Appelle aggregate_md.py sur un dossier de config. Tolerant aux
    erreurs : log et continue (ne bloque pas la finalisation globale)."""
    print(f"  aggregate_md {config_dir.name}/ ...", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, str(AGGREGATE_MD), str(config_dir)],
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"    ECHEC (rc={result.returncode}) : "
                  f"{result.stderr[:300]}", flush=True)
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT apres 600s", flush=True)
        return False


def run_view_aggregate(h_dir):
    """Appelle view.py --aggregate au niveau hX."""
    print(f"  view --aggregate {h_dir.name}/ ...", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, str(VIEW_PY), str(h_dir), "--aggregate"],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"    ECHEC view.py : {result.stderr[:300]}", flush=True)
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT apres 300s", flush=True)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Finalisation post-cluster : aggregate_md + view + cluster_meta",
    )
    parser.add_argument("h_dir",
                        help="Dossier hX a finaliser (ex. output/h6)")
    parser.add_argument("--manifest", default=None,
                        help="Manifest JSONL pour identifier les jobs manquants "
                             "(optionnel mais recommande)")
    parser.add_argument("--no-aggregate", action="store_true",
                        help="Skip l'appel a aggregate_md.py par config")
    parser.add_argument("--no-view", action="store_true",
                        help="Skip la generation de view.html")
    args = parser.parse_args()

    h_dir = Path(args.h_dir).resolve()
    if not h_dir.is_dir():
        print(f"ERREUR: dossier introuvable : {h_dir}", file=sys.stderr)
        sys.exit(2)

    print(f"=== finalize {h_dir.name} ===", flush=True)
    t0 = time.time()

    # 1. Charger le manifest si fourni
    expected = None
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_file():
            print(f"ATTENTION: manifest introuvable, skip : {manifest_path}",
                  file=sys.stderr)
        else:
            expected = []
            with open(manifest_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        expected.append(json.loads(line))
            print(f"  manifest    : {len(expected)} jobs attendus", flush=True)

    # 2. Collecter les statuses
    statuses = collect_job_statuses(h_dir)
    print(f"  job_status  : {len(statuses)} jobs trouves", flush=True)

    if not statuses:
        print("  Aucun resultat -- rien a finaliser.", flush=True)
        sys.exit(0)

    # 3. Stats globales
    stats = compute_stats(statuses, expected_jobs=expected)
    print(f"\n  Resultats globaux :", flush=True)
    print(f"    OK         : {stats['n_ok']}", flush=True)
    print(f"    Failed     : {stats['n_failed']}", flush=True)
    print(f"    Timeout    : {stats['n_timeout']}", flush=True)
    if stats['n_missing']:
        print(f"    Manquants  : {stats['n_missing']}", flush=True)
    print(f"    Solutions  : {stats['n_solutions_total']} "
          f"({stats['n_md_outputs_total']} avec md_validation)", flush=True)
    if stats['wall_clock_sec'] is not None:
        print(f"    Wall-clock : {format_duration(stats['wall_clock_sec'])} "
              f"({stats['wall_clock_sec']}s)", flush=True)
    print(f"    Hosts      : {len(stats['per_host'])}", flush=True)
    for host, st in sorted(stats['per_host'].items()):
        print(f"      {host:<25} {st['n_jobs']:>4} jobs, "
              f"avg {st['duration_avg_sec']:>6.1f}s, "
              f"ok {st['n_ok']}, fail {st['n_failed']}", flush=True)

    # 4. aggregate_md.py par config
    if not args.no_aggregate:
        print(f"\n  Aggregation MD par config :", flush=True)
        config_dirs = sorted([d for d in h_dir.iterdir()
                              if d.is_dir() and not d.name.startswith(".")])
        n_aggregated = 0
        for config_dir in config_dirs:
            if run_aggregate_md(config_dir):
                n_aggregated += 1
        print(f"  -> {n_aggregated}/{len(config_dirs)} configs aggregees",
              flush=True)

    # 5. view.html agrege au niveau hX
    if not args.no_view:
        print(f"\n  Viewer agrege :", flush=True)
        run_view_aggregate(h_dir)

    # 6. cluster_meta.json (jumeau de batch_meta.json)
    cluster_meta = {
        "type": "cluster_run",
        "h": h_dir.name,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "n_total_done": stats['n_total_done'],
        "n_ok": stats['n_ok'],
        "n_failed": stats['n_failed'],
        "n_timeout": stats['n_timeout'],
        "n_missing": stats['n_missing'],
        "n_solutions_total": stats['n_solutions_total'],
        "n_md_outputs_total": stats['n_md_outputs_total'],
        "wall_clock_sec": stats['wall_clock_sec'],
        "wall_clock_str": format_duration(stats['wall_clock_sec']),
        "finalize_duration_sec": round(time.time() - t0, 1),
        "per_host": stats['per_host'],
        "missing_job_ids": stats['missing_job_ids'],
        "failed_job_ids": stats['failed_job_ids'],
    }
    meta_path = h_dir / "cluster_meta.json"
    write_atomic_json(meta_path, cluster_meta)
    print(f"\n  cluster_meta.json -> {meta_path}", flush=True)

    print(f"\n=== finalize termine ({round(time.time()-t0,1)}s) ===", flush=True)
    if stats['n_failed'] or stats['n_timeout'] or stats['n_missing']:
        print(f"  ATTENTION: {stats['n_failed']+stats['n_timeout']} echec(s) "
              f"+ {stats['n_missing']} manquant(s) - voir failed_job_ids "
              f"dans cluster_meta.json", flush=True)


if __name__ == "__main__":
    main()
