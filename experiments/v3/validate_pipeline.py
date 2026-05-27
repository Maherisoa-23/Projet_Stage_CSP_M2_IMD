"""Validation du pipeline v3 COMPLET : Gauss-Bonnet local + MMFF 3-tier.

Pipeline :
   candidate CSP
     -> [filtre Gauss-Bonnet]  reject si max_local_r2 > tau_gb
     -> [MMFF 3-tier]          mmff_angle :
           < tau_sure_plan         => kept_sure_plan (accept sans xTB)
           in [tau_sp, tau_snp]    => kept_gray      (envoyer a xTB)
           > tau_sure_non_plan     => rejected_sure_non_plan

On evalue 4 scenarios sur le meme echantillon, en utilisant le verdict xTB
deja stocke dans db_v2.db :

  S0 baseline      : aucun filtre, tout passe a xTB
  S1 gauss-bonnet  : juste le filtre de courbure
  S2 mmff-3tier    : juste MMFF 3-tier (skip Gauss-Bonnet)
  S3 combined      : Gauss-Bonnet puis MMFF 3-tier

Pour chaque scenario on rapporte :
  - kept    = nb de candidats acceptes (incl. sure_plan, donc generes au final)
  - n_xtb   = nb d'invocations xTB necessaires
  - precision = parmi les acceptes, % reellement plan
  - recall    = % des vrais plans qu'on retient
  - speedup_xtb = baseline_xtb / scenario_xtb

Usage:
  venv/Scripts/python.exe -m experiments.v3.validate_pipeline \\
      --h h7 --n-per-class 200 --tau-gb 1 --threshold-sure-plan 5 \\
      --threshold-sure-non-plan 25
"""

from __future__ import annotations

import argparse
import gzip
import multiprocessing as mp
import random
import sqlite3
import sys
import time
from pathlib import Path

# Permet l'execution directe (python -m) ou comme script
if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[2]))

from csp_solver.utils.parser import parse as parse_graph
from experiments.v3.curvature_helper import max_local_curvature
from experiments.v3.mmff_oracle import mmff_planarity


# =========================== Worker state (multiprocessing) ===========================
# Globales propres a chaque processus worker.

_worker_conn: sqlite3.Connection | None = None
_worker_graph_cache: dict = {}
_worker_graph_dir: str = ""
_worker_h_filter: str = ""
_worker_radius_gb: int = 2


def _init_worker(db_path: str, graph_dir: str, h_filter: str, radius_gb: int) -> None:
    """Initialise l'etat du worker (1x par worker)."""
    global _worker_conn, _worker_graph_cache
    global _worker_graph_dir, _worker_h_filter, _worker_radius_gb
    _worker_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    _worker_graph_cache = {}
    _worker_graph_dir = graph_dir
    _worker_h_filter = h_filter
    _worker_radius_gb = radius_gb


def _process_record(s: dict) -> dict | None:
    """Traite un record (sample dict). Renvoie dict de stats ou None si skip."""
    mol = s["mol"]
    sd_name = Path(s["sol_dir"]).name
    sizes = parse_sol_sizes(sd_name)
    if sizes is None:
        return None
    if mol not in _worker_graph_cache:
        gp = Path(_worker_graph_dir) / _worker_h_filter / f"{mol}.graph"
        if not gp.exists():
            return None
        _worker_graph_cache[mol] = parse_graph(str(gp))
    graph = _worker_graph_cache[mol]
    if len(sizes) != graph.h:
        return None
    labeling = {i: sizes[i] for i in range(graph.h)}
    max_r, _ = max_local_curvature(graph, labeling, radius=_worker_radius_gb)
    xyz = load_xyz(_worker_conn, s["sol_dir"])
    if xyz is None:
        mmff_angle = None
    else:
        r = mmff_planarity(xyz)
        mmff_angle = r["angle_deg"] if r is not None else None
    return {
        "verdict": s["verdict"],
        "xtb_angle": s["angle_deg"],
        "max_r": max_r,
        "mmff_angle": mmff_angle,
    }


DB_DEFAULT = "csp_solver/experiments/csp_viewer/db_v2.db"
GRAPH_DIR_DEFAULT = "csp_solver/experiments/plane/benzdb"


def parse_sol_sizes(sol_dir_basename: str) -> list[int] | None:
    """sol_42_5_7_6_6_5_6 -> [5,7,6,6,5,6]."""
    parts = sol_dir_basename.split("_")
    if len(parts) < 2 or parts[0] != "sol":
        return None
    try:
        return [int(p) for p in parts[2:]]
    except ValueError:
        return None


def fetch_samples(db_path: str, h_filter: str, n_per_class: int | None,
                   all_mode: bool = False, seed: int = 42) -> list[dict]:
    """Recupere les samples a evaluer.

    Args:
        n_per_class : si fourni et all_mode=False, echantillonne N plan + N non_plan
        all_mode    : si True, prend TOUT (distribution reelle, non-equilibree)
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if all_mode:
        rows = list(cur.execute(
            "SELECT h, mol, sol_dir, verdict, angle_deg FROM solutions "
            "WHERE h=? AND verdict IN ('plan','non_plan')",
            (h_filter,)
        ))
        return [dict(r) for r in rows]

    rng = random.Random(seed)
    out = []
    pool_size = max((n_per_class or 0) * 5, 100)
    for verdict in ("plan", "non_plan"):
        rows = list(cur.execute(
            "SELECT h, mol, sol_dir, verdict, angle_deg FROM solutions "
            "WHERE verdict=? AND h=? LIMIT ?",
            (verdict, h_filter, pool_size)
        ))
        if n_per_class and len(rows) > n_per_class:
            rng.shuffle(rows)
            rows = rows[:n_per_class]
        out.extend(dict(r) for r in rows)
    return out


def load_xyz(conn: sqlite3.Connection, sol_dir: str) -> str | None:
    key = sol_dir + "/md_validation/md_final_opt.xyz"
    row = conn.execute("SELECT content_gz FROM xyz_files WHERE rel_path = ?",
                       (key,)).fetchone()
    if row is None:
        return None
    return gzip.decompress(row[0]).decode("utf-8")


def run_pipeline(db_path: str, graph_dir: str, h_filter: str,
                  n_per_class: int | None, all_mode: bool,
                  tau_gb: int, radius_gb: int,
                  th_sure_plan: float, th_sure_non_plan: float,
                  th_xtb: float, seed: int, workers: int = 1) -> dict:
    """Boucle principale : pour chaque sample, compute Gauss-Bonnet + MMFF."""

    samples = fetch_samples(db_path, h_filter, n_per_class, all_mode, seed)
    mode_str = "all" if all_mode else f"sample n_per_class={n_per_class}"
    print(f"[sample] {len(samples)} mols ({h_filter}, {mode_str})  | "
           f"tau_gb={tau_gb}(r={radius_gb}), "
           f"th_sp={th_sure_plan}, th_snp={th_sure_non_plan}  workers={workers}", flush=True)

    records: list[dict] = []
    n_skipped = 0

    t0 = time.perf_counter()
    progress_every = max(len(samples) // 20, 100)

    if workers <= 1:
        # Mode mono-thread (pour debug / petits volumes)
        _init_worker(db_path, graph_dir, h_filter, radius_gb)
        for i, s in enumerate(samples):
            res = _process_record(s)
            if res is None:
                n_skipped += 1
            else:
                records.append(res)
            if (i + 1) % progress_every == 0:
                rate = (i + 1) / max(time.perf_counter() - t0, 1e-3)
                print(f"  [{i+1}/{len(samples)}] @ {rate:.1f}/s", flush=True)
    else:
        with mp.Pool(workers,
                      initializer=_init_worker,
                      initargs=(db_path, graph_dir, h_filter, radius_gb)) as pool:
            chunksize = max(50, len(samples) // (workers * 20))
            for i, res in enumerate(pool.imap_unordered(_process_record, samples, chunksize=chunksize)):
                if res is None:
                    n_skipped += 1
                else:
                    records.append(res)
                if (i + 1) % progress_every == 0:
                    rate = (i + 1) / max(time.perf_counter() - t0, 1e-3)
                    print(f"  [{i+1}/{len(samples)}] @ {rate:.1f}/s", flush=True)

    elapsed = time.perf_counter() - t0
    n_total = len(records)
    n_true_plan = sum(1 for r in records if r["verdict"] == "plan")
    print(f"[time] {elapsed:.1f} s  | mols={n_total} (true_plan={n_true_plan})  skipped={n_skipped}", flush=True)

    if n_total == 0:
        print("Aucune mol evaluee.", flush=True)
        return {}

    # ---------------- 4 scenarios ----------------

    def evaluate_scenario(use_gb: bool, use_mmff: bool, name: str) -> dict:
        """Compte les decisions, calcule kept/n_xtb/precision/recall."""
        # categories : sure_plan, gray, rejected_curv, rejected_mmff_snp, mmff_failed
        n_kept_sp = 0       # accepte direct, sans xTB
        n_kept_gray = 0     # nécessite xTB
        n_rejected_curv = 0
        n_rejected_snp = 0
        n_mmff_failed = 0

        # Outcomes parmi les "kept" (sp + gray) -> est-ce vraiment plan ?
        TP_sp = FP_sp = 0
        TP_gray = FP_gray = 0
        FN_curv = TN_curv = 0
        FN_snp = TN_snp = 0
        FN_mmff_failed = TN_mmff_failed = 0

        for r in records:
            true_plan = (r["verdict"] == "plan")

            # Etage 1 : Gauss-Bonnet
            if use_gb and r["max_r"] > tau_gb:
                n_rejected_curv += 1
                if true_plan: FN_curv += 1
                else:         TN_curv += 1
                continue

            # Etage 2 : MMFF 3-tier
            if use_mmff:
                if r["mmff_angle"] is None:
                    n_mmff_failed += 1
                    # On garde par defaut (passe a xTB) -> compte comme gray
                    n_kept_gray += 1
                    if true_plan: TP_gray += 1
                    else:         FP_gray += 1
                    continue
                if r["mmff_angle"] < th_sure_plan:
                    n_kept_sp += 1
                    if true_plan: TP_sp += 1
                    else:         FP_sp += 1
                elif r["mmff_angle"] > th_sure_non_plan:
                    n_rejected_snp += 1
                    if true_plan: FN_snp += 1
                    else:         TN_snp += 1
                else:
                    n_kept_gray += 1
                    if true_plan: TP_gray += 1
                    else:         FP_gray += 1
            else:
                n_kept_gray += 1
                if true_plan: TP_gray += 1
                else:         FP_gray += 1

        n_kept = n_kept_sp + n_kept_gray
        n_xtb_calls = n_kept_gray  # sure_plan accepte sans xTB

        TP = TP_sp + TP_gray
        FP = FP_sp + FP_gray
        FN = FN_curv + FN_snp
        # Note : "TN" complet = n_rejected_curv + n_rejected_snp - FN_*
        TN = (n_rejected_curv - FN_curv) + (n_rejected_snp - FN_snp)

        precision = TP / max(TP + FP, 1)
        recall = TP / max(n_true_plan, 1)
        ratio_xtb_to_baseline = n_xtb_calls / max(n_total, 1)

        return {
            "name": name,
            "kept": n_kept,
            "kept_sure_plan": n_kept_sp,
            "kept_gray": n_kept_gray,
            "rejected_curv": n_rejected_curv,
            "rejected_snp": n_rejected_snp,
            "mmff_failed": n_mmff_failed,
            "n_xtb_calls": n_xtb_calls,
            "TP": TP, "FP": FP, "FN": FN, "TN": TN,
            "precision_kept_plan": precision,
            "recall_capture_plan": recall,
            "ratio_xtb": ratio_xtb_to_baseline,
        }

    s0 = evaluate_scenario(use_gb=False, use_mmff=False, name="S0 baseline")
    s1 = evaluate_scenario(use_gb=True,  use_mmff=False, name="S1 gauss-bonnet only")
    s2 = evaluate_scenario(use_gb=False, use_mmff=True,  name="S2 mmff 3-tier only")
    s3 = evaluate_scenario(use_gb=True,  use_mmff=True,  name="S3 combined GB+MMFF")

    # ---------------- Rendu ----------------
    print(f"\n{'='*80}", flush=True)
    print(f"{'scenario':<28} {'kept':>5} {'sp':>4} {'gray':>5} {'rej_c':>5} {'rej_s':>5} "
           f"{'xTB':>5} {'prec':>6} {'recall':>7} {'plans_gen':>10}", flush=True)
    print(f"{'-'*80}", flush=True)
    for sc in (s0, s1, s2, s3):
        # plans generes = TP (parmi kept, ceux vraiment plans)
        plans_gen = sc["TP"]
        # Si on suppose qu'on fait xTB sur les gray, on n'accepte parmi gray
        # que ceux que xTB declare plan -> donc plans_gen = TP_sp + TP_gray (deja)
        print(f"{sc['name']:<28} {sc['kept']:>5} {sc['kept_sure_plan']:>4} "
               f"{sc['kept_gray']:>5} {sc['rejected_curv']:>5} "
               f"{sc['rejected_snp']:>5} {sc['n_xtb_calls']:>5} "
               f"{sc['precision_kept_plan']*100:>5.1f}% "
               f"{sc['recall_capture_plan']*100:>5.1f}% "
               f"{plans_gen:>10}", flush=True)

    print(f"\n{'='*80}", flush=True)
    print("Lecture :", flush=True)
    print("  kept    = nb candidats acceptes (sure_plan + gray, soit ce qu'on garde au final)", flush=True)
    print("  sp      = parmi kept, ceux declares 'sure plan' par MMFF (acceptes sans xTB)", flush=True)
    print("  gray    = parmi kept, ceux qui doivent passer a xTB pour decider", flush=True)
    print("  rej_c   = rejetes par Gauss-Bonnet (sans MMFF ni xTB)", flush=True)
    print("  rej_s   = rejetes par MMFF (sure_non_plan, sans xTB)", flush=True)
    print("  xTB     = nb appels xTB necessaires (= gray)", flush=True)
    print("  prec    = parmi kept, % reellement plan", flush=True)
    print("  recall  = % des vrais plans capture par le pipeline", flush=True)
    print("  plans_gen = nb plans reellement produits (TP)", flush=True)

    # Speedup
    if s3["n_xtb_calls"] > 0:
        speedup = s0["n_xtb_calls"] / s3["n_xtb_calls"]
        print(f"\n>>> Speedup xTB combined / baseline = {speedup:.2f}x", flush=True)
    if s3["TP"] > 0 and s0["TP"] > 0:
        plans_ratio = s3["TP"] / s0["TP"]
        print(f">>> Plans recus combined / baseline    = {plans_ratio*100:.1f}%", flush=True)
        if s3["n_xtb_calls"] > 0:
            plans_per_xtb_s0 = s0["TP"] / max(s0["n_xtb_calls"], 1)
            plans_per_xtb_s3 = s3["TP"] / s3["n_xtb_calls"]
            print(f">>> Plans/xTB-call baseline = {plans_per_xtb_s0:.3f} ; "
                   f"combined = {plans_per_xtb_s3:.3f} ; gain efficacite = {plans_per_xtb_s3/plans_per_xtb_s0:.2f}x", flush=True)

    return {"S0": s0, "S1": s1, "S2": s2, "S3": s3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--graph-dir", default=GRAPH_DIR_DEFAULT)
    ap.add_argument("--h", required=True)
    ap.add_argument("--n-per-class", type=int, default=100,
                     help="ignore si --all est utilise")
    ap.add_argument("--all", action="store_true",
                     help="evaluer toutes les sols pour ce h (distribution naturelle)")
    ap.add_argument("--tau-gb", type=int, default=1,
                     help="Seuil Gauss-Bonnet : reject si max_local_r > tau_gb")
    ap.add_argument("--radius-gb", type=int, default=2)
    ap.add_argument("--threshold-sure-plan", type=float, default=5.0)
    ap.add_argument("--threshold-sure-non-plan", type=float, default=25.0)
    ap.add_argument("--threshold-xtb", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=1,
                     help="nb de processus parallels (default=1, mono-thread)")
    args = ap.parse_args()

    print(f"[db] {args.db}", flush=True)
    print(f"[h] {args.h}", flush=True)
    run_pipeline(args.db, args.graph_dir, args.h,
                  args.n_per_class, args.all,
                  args.tau_gb, args.radius_gb,
                  args.threshold_sure_plan, args.threshold_sure_non_plan,
                  args.threshold_xtb, args.seed,
                  workers=args.workers)


if __name__ == "__main__":
    main()
