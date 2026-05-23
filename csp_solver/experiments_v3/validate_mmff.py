"""Validation MMFF comme oracle de planarite.

Echantillonne N solutions plan + N non_plan dans db_v2.db, applique MMFF, et
calcule la matrice de confusion contre le verdict xTB.

Sortie console :
                pred_plan   pred_non_plan
   true_plan    [TP]        [FN]
   true_non_pl  [FP]        [TN]

   accuracy, precision, recall, F1, MCC

Usage :
   venv/Scripts/python.exe -m csp_solver.experiments_v3.validate_mmff \\
       --n-per-class 100 --h h7 --threshold 10.0

Avec --threshold-mmff X, on utilise un seuil different pour MMFF (utile pour
calibrer : MMFF a tendance a etre plus severe que xTB).
"""

from __future__ import annotations

import argparse
import gzip
import math
import random
import sqlite3
import sys
import time
from pathlib import Path

# Permet l'execution directe (python -m) ou comme script
if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[2]))

from csp_solver.experiments_v3.mmff_oracle import mmff_planarity


DB_DEFAULT = "csp_solver/experiments/csp_viewer/db_v2.db"


def fetch_samples(db_path: str, h_filter: str | None, n_per_class: int,
                   seed: int = 42) -> tuple[list[dict], list[dict]]:
    """Echantillonne n_per_class solutions plan et non_plan.

    Strategie : ORDER BY RANDOM() est lent sur grosse table, mais on filtre
    par h et verdict (index existant idx_sol_verdict (h, config, mol, verdict)).
    On limite a 5*n pour avoir un pool, puis on sample en Python.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    pool_size = max(n_per_class * 5, 50)
    rng = random.Random(seed)

    def fetch(verdict: str) -> list[dict]:
        params = [verdict]
        sql = "SELECT h, config, mol, sol_dir, angle_deg, verdict FROM solutions WHERE verdict=?"
        if h_filter:
            sql += " AND h=?"
            params.append(h_filter)
        sql += f" LIMIT {pool_size}"
        rows = list(cur.execute(sql, params))
        if len(rows) > n_per_class:
            rng.shuffle(rows)
            rows = rows[:n_per_class]
        return [dict(r) for r in rows]

    return fetch("plan"), fetch("non_plan")


def load_xyz(conn: sqlite3.Connection, sol_dir: str) -> str | None:
    """Charge le xyz xTB-optimise pour ce sol_dir."""
    key = sol_dir + "/md_validation/md_final_opt.xyz"
    row = conn.execute("SELECT content_gz FROM xyz_files WHERE rel_path = ?",
                       (key,)).fetchone()
    if row is None:
        return None
    return gzip.decompress(row[0]).decode("utf-8")


def evaluate(db_path: str, h_filter: str | None, n_per_class: int,
              threshold_xtb: float, threshold_mmff: float,
              seed: int = 42, verbose: bool = False) -> dict:

    plan_samples, non_plan_samples = fetch_samples(db_path, h_filter, n_per_class, seed)
    print(f"[sample] {len(plan_samples)} plan + {len(non_plan_samples)} non_plan", flush=True)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    # 4 cellules : (true_label, mmff_label)
    counts = {("plan","plan"): 0, ("plan","non_plan"): 0,
              ("non_plan","plan"): 0, ("non_plan","non_plan"): 0}
    n_mmff_failed = 0
    angles_compare = []  # liste de (xtb_ang, mmff_ang, true_label)

    t0 = time.perf_counter()
    total = len(plan_samples) + len(non_plan_samples)
    done = 0
    for true_label, samples in [("plan", plan_samples), ("non_plan", non_plan_samples)]:
        for s in samples:
            done += 1
            xyz = load_xyz(conn, s["sol_dir"])
            if xyz is None:
                n_mmff_failed += 1
                continue
            r = mmff_planarity(xyz, threshold_deg=threshold_mmff)
            if r is None:
                n_mmff_failed += 1
                if verbose:
                    print(f"  [{done}/{total}] {s['sol_dir']} : MMFF failed", flush=True)
                continue
            pred = "plan" if r["planar"] else "non_plan"
            counts[(true_label, pred)] += 1
            angles_compare.append((s["angle_deg"], r["angle_deg"], true_label))
            if verbose and done % 20 == 0:
                rate = done / max(time.perf_counter() - t0, 0.001)
                print(f"  [{done}/{total}] @ {rate:.1f}/s", flush=True)

    elapsed = time.perf_counter() - t0

    # Matrice de confusion
    TP = counts[("plan", "plan")]
    FN = counts[("plan", "non_plan")]
    FP = counts[("non_plan", "plan")]
    TN = counts[("non_plan", "non_plan")]
    n_evaluated = TP + FN + FP + TN

    acc = (TP + TN) / max(n_evaluated, 1)
    prec = TP / max(TP + FP, 1)
    rec  = TP / max(TP + FN, 1)
    f1   = 2 * prec * rec / max(prec + rec, 1e-9)
    # MCC
    denom = math.sqrt(max((TP+FP)*(TP+FN)*(TN+FP)*(TN+FN), 1))
    mcc = (TP*TN - FP*FN) / denom

    print(f"\n[time] {elapsed:.1f} s pour {done} mols ({done/elapsed:.1f}/s)", flush=True)
    print(f"[mmff failed] {n_mmff_failed} sur {total}", flush=True)
    print(f"[evaluated] {n_evaluated}", flush=True)

    print(f"\n                pred_plan   pred_non_plan", flush=True)
    print(f" true_plan        {TP:5d}        {FN:5d}", flush=True)
    print(f" true_non_plan    {FP:5d}        {TN:5d}", flush=True)

    print(f"\n accuracy  = {acc*100:5.1f} %", flush=True)
    print(f" precision = {prec*100:5.1f} %  (parmi MMFF-plan, % vraiment plan)", flush=True)
    print(f" recall    = {rec*100:5.1f} %  (parmi vrais-plan, % capture par MMFF)", flush=True)
    print(f" F1        = {f1*100:5.1f} %", flush=True)
    print(f" MCC       = {mcc:+5.3f}", flush=True)

    # Decision pratique : MMFF est-il un bon oracle ?
    print()
    if acc >= 0.90:
        print(" -> ACCORD EXCELLENT (>=90%) : MMFF peut etre utilise comme pre-filtre", flush=True)
    elif acc >= 0.80:
        print(" -> ACCORD CORRECT (80-90%) : MMFF utilisable, mais calibration souhaitable", flush=True)
    else:
        print(" -> ACCORD INSUFFISANT (<80%) : il faut autre chose (Huckel ? GNN ?)", flush=True)

    # Histogramme des desaccords pour comprendre
    fp_cases = [(x, m) for (x, m, t) in angles_compare if t == "non_plan" and m <= threshold_mmff]
    fn_cases = [(x, m) for (x, m, t) in angles_compare if t == "plan" and m > threshold_mmff]
    if fp_cases:
        print(f"\n FAUX POSITIFS (MMFF-plan mais xTB-non_plan), n={len(fp_cases)} :", flush=True)
        for x, m in fp_cases[:5]:
            print(f"   xTB={x:6.2f}  MMFF={m:6.2f}", flush=True)
    if fn_cases:
        print(f"\n FAUX NEGATIFS (MMFF-non_plan mais xTB-plan), n={len(fn_cases)} :", flush=True)
        for x, m in fn_cases[:5]:
            print(f"   xTB={x:6.2f}  MMFF={m:6.2f}", flush=True)

    return {
        "accuracy": acc, "precision": prec, "recall": rec, "f1": f1, "mcc": mcc,
        "TP": TP, "FN": FN, "FP": FP, "TN": TN,
        "n_evaluated": n_evaluated, "n_failed": n_mmff_failed,
        "elapsed_sec": elapsed,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--h", default=None, help="filtrer par h6/h7/h8/h9 (defaut: tous)")
    ap.add_argument("--n-per-class", type=int, default=50)
    ap.add_argument("--threshold-xtb", type=float, default=10.0)
    ap.add_argument("--threshold-mmff", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print(f"[db] {args.db}", flush=True)
    print(f"[filter] h={args.h or 'all'}  n_per_class={args.n_per_class}", flush=True)
    print(f"[thresholds] xTB={args.threshold_xtb} deg  MMFF={args.threshold_mmff} deg", flush=True)

    evaluate(args.db, args.h, args.n_per_class, args.threshold_xtb,
             args.threshold_mmff, args.seed, args.verbose)


if __name__ == "__main__":
    main()
