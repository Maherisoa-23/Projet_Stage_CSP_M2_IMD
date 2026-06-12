"""Plafonne h9 C1 à N sols max par graph via selection stratifiee.

Strategie :
  - Conserve les sols deja avancees (done/running/failed) telles quelles
  - Sur les pending, stratifie par (n_pent, n_hept) = "signature topologique"
  - Echantillonne uniformement seed=42 pour atteindre TARGET sols/graph
  - Les pending non-selectionnees passent en status='skipped'

Dry-run par defaut. --apply pour appliquer les changements.
Reproductible : seed fixee.
"""

import argparse
import json
import random
import sqlite3
from collections import defaultdict


def stratified_sample(strata: dict, target: int, rng: random.Random) -> set:
    """Selectionne target items au total, repartis sur les strata.

    strata : {key: [sol_ids]}
    Strategy :
      - quota_per_strata = floor(target * |strata| / total)
      - reste distribue par fraction decroissante
      - sample aleatoire dans chaque strata
    """
    total = sum(len(v) for v in strata.values())
    if target >= total:
        return set(it for v in strata.values() for it in v)

    keys = sorted(strata.keys())
    quotas = {}
    for k in keys:
        n = len(strata[k])
        quotas[k] = min((target * n) // total, n)

    rest = target - sum(quotas.values())
    if rest > 0:
        # Distribuer le reste aux strata par fraction decroissante
        candidates = []
        for k in keys:
            n = len(strata[k])
            exact = target * n / total
            frac = exact - quotas[k]
            if quotas[k] < n:
                candidates.append((frac, k))
        candidates.sort(reverse=True)
        for _, k in candidates[:rest]:
            quotas[k] += 1

    selected = set()
    for k in keys:
        items = list(strata[k])
        q = quotas[k]
        if q >= len(items):
            selected.update(items)
        else:
            selected.update(rng.sample(items, q))
    return selected


def signature(csp_solution_json: str) -> tuple:
    """(n_pent, n_hept) depuis JSON sol."""
    sol = json.loads(csp_solution_json)
    n_pent = sum(1 for v in sol.values() if v == 5)
    n_hept = sum(1 for v in sol.values() if v == 7)
    return (n_pent, n_hept)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-id", type=int, default=1)
    ap.add_argument("--size-h", type=int, default=9)
    ap.add_argument("--config", default="C1")
    ap.add_argument("--target", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)

    conn = sqlite3.connect(args.db, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")

    graphs = [r[0] for r in conn.execute(
        "SELECT DISTINCT graph_name FROM final_solutions "
        "WHERE run_id=? AND size_h=? AND config=?",
        (args.run_id, args.size_h, args.config),
    ).fetchall()]

    print(f"=== Plafond h{args.size_h} {args.config} (target={args.target}/graph) ===")
    print(f"Total graphs   : {len(graphs)}")
    print(f"Seed           : {args.seed}")
    print(f"Mode           : {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    tot_done = tot_run = tot_fail = tot_keep_pend = tot_skip = 0
    tot_strata = 0
    n_with_strata = 0
    sols_to_skip = []

    for i, gname in enumerate(graphs):
        rows = conn.execute(
            "SELECT sol_id, status, csp_solution_json FROM final_solutions "
            "WHERE run_id=? AND size_h=? AND config=? AND graph_name=?",
            (args.run_id, args.size_h, args.config, gname),
        ).fetchall()
        by_status = defaultdict(list)
        for r in rows:
            by_status[r["status"]].append(r)
        n_done = len(by_status["done"])
        n_run = len(by_status["running"])
        n_fail = len(by_status["failed"])
        n_pend = len(by_status["pending"])

        n_already = n_done + n_run + n_fail
        target_rem = max(0, args.target - n_already)
        n_strata_local = 0

        if n_pend == 0 or target_rem >= n_pend:
            kept = n_pend
            skipped = 0
        elif target_rem == 0:
            sols_to_skip.extend(r["sol_id"] for r in by_status["pending"])
            kept = 0
            skipped = n_pend
        else:
            strata = defaultdict(list)
            for r in by_status["pending"]:
                try:
                    sig = signature(r["csp_solution_json"])
                except Exception:
                    sig = (-1, -1)
                strata[sig].append(r["sol_id"])
            selected = stratified_sample(strata, target_rem, rng)
            kept = len(selected)
            skipped = n_pend - kept
            n_strata_local = len(strata)
            for r in by_status["pending"]:
                if r["sol_id"] not in selected:
                    sols_to_skip.append(r["sol_id"])

        tot_done += n_done
        tot_run += n_run
        tot_fail += n_fail
        tot_keep_pend += kept
        tot_skip += skipped
        if n_strata_local > 0:
            tot_strata += n_strata_local
            n_with_strata += 1

        if i < 5 or (i + 1) % 500 == 0:
            print(f"  [{i+1:>4}/{len(graphs)}] {gname}: done={n_done} run={n_run} "
                  f"fail={n_fail} pend={n_pend} -> keep={kept} skip={skipped} "
                  f"strata={n_strata_local}")

    print()
    print("=== RESUME ===")
    print(f"  done preserves              : {tot_done}")
    print(f"  running preserves           : {tot_run}")
    print(f"  failed preserves            : {tot_fail}")
    print(f"  pending gardes (a traiter)  : {tot_keep_pend}")
    print(f"  pending -> skipped          : {tot_skip}")
    if n_with_strata > 0:
        print(f"  strata moyennes par graph   : {tot_strata/n_with_strata:.1f}")
    print()
    before = tot_keep_pend + tot_skip
    if before > 0:
        print(f"Pending avant : {before}")
        print(f"Pending apres : {tot_keep_pend}")
        print(f"Reduction     : {100*tot_skip/before:.1f}%")

    if args.apply and sols_to_skip:
        print()
        print(f"Application : {len(sols_to_skip)} sols -> 'skipped'...")
        BATCH = 500
        n_done_update = 0
        for j in range(0, len(sols_to_skip), BATCH):
            chunk = sols_to_skip[j:j + BATCH]
            qmarks = ",".join("?" * len(chunk))
            conn.execute(
                f"UPDATE final_solutions SET status='skipped' WHERE sol_id IN ({qmarks})",
                chunk,
            )
            n_done_update += len(chunk)
            if n_done_update % 5000 == 0:
                conn.commit()
                print(f"  ... {n_done_update}/{len(sols_to_skip)}")
        conn.commit()
        print("  Done.")
    elif sols_to_skip:
        print()
        print(f"(dry-run, {len(sols_to_skip)} sols seraient marquees 'skipped' avec --apply)")

    conn.close()


if __name__ == "__main__":
    main()
