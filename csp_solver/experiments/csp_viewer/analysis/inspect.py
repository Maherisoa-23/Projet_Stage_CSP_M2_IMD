"""
Script d'inspection rapide de topology_metrics.

Usage :
    python -m csp_solver.experiments.csp_viewer.analysis.inspect --h h6
"""

import argparse
import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "csp_solver.experiments.csp_viewer.analysis"

from .queries import (  # noqa: E402
    summary_by_h,
    top_aromatic_planar,
    top_radical_planar,
    correlation_angle_radicals,
    distribution_clar,
    distribution_radicals,
)


_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = _HERE.parent / "db_v2.db"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    parser.add_argument("--h", default=None,
                        help="filtre par h (ex h6). Default = tous")
    parser.add_argument("--k", type=int, default=10,
                        help="taille des Top-K. Default 10")
    parser.add_argument("--max-angle", type=float, default=5.0)
    parser.add_argument("--min-clar", type=int, default=2)
    parser.add_argument("--min-radicals", type=int, default=2)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    n_metrics = conn.execute(
        "SELECT COUNT(*) FROM topology_metrics" +
        (" WHERE h = ?" if args.h else ""),
        ([args.h] if args.h else [])
    ).fetchone()[0]
    print(f"=== topology_metrics : {n_metrics} entrees "
          f"{('(h='+args.h+')') if args.h else '(tous h)'}")
    print()

    # Sommaire par h
    print("=== Sommaire par h")
    rows = summary_by_h(conn, h=args.h)
    if rows:
        print(f"{'h':>4} | {'n_eval':>7} | {'plans':>6} | {'non_p':>6} |"
              f" {'mean_clar':>9} | {'mean_rad':>8} | {'mean_K':>8} | {'mean_cbo_hex':>12}")
        print("-" * 88)
        for r in rows:
            mean_cbo = f"{r['mean_cbo_hex']:.2f}" if r['mean_cbo_hex'] is not None else "  -"
            print(f"{r['h']:>4} | {r['n_evaluees']:>7} | {r['n_plans']:>6} |"
                  f" {r['n_non_plans']:>6} | {r['mean_clar']:>9.2f} |"
                  f" {r['mean_radicals']:>8.2f} | {r['mean_n_kekule']:>8.1f} |"
                  f" {mean_cbo:>12}")
    else:
        print("  (aucune entree)")
    print()

    # Distribution clar_number
    print("=== Distribution clar_number")
    rows = distribution_clar(conn, h=args.h)
    total = sum(r["n"] for r in rows) or 1
    for r in rows:
        pct = 100 * r["n"] / total
        bar = "#" * int(pct / 2)  # 50 chars max
        print(f"  Clar={r['clar_number']:<2}  {r['n']:>5} ({pct:5.1f}%)  {bar}")
    print()

    # Distribution n_radicals
    print("=== Distribution n_radicals")
    rows = distribution_radicals(conn, h=args.h)
    total = sum(r["n"] for r in rows) or 1
    for r in rows:
        pct = 100 * r["n"] / total
        bar = "#" * int(pct / 2)
        print(f"  rad={r['n_radicals']:<2}  {r['n']:>5} ({pct:5.1f}%)  {bar}")
    print()

    # Correlation angle vs radicaux
    print("=== Correlation Pearson angle_deg vs n_radicals")
    rho = correlation_angle_radicals(conn, h=args.h)
    if rho is not None:
        sign = "POSITIVE" if rho > 0.1 else ("NEGATIVE" if rho < -0.1 else "FAIBLE")
        print(f"  rho = {rho:.4f}  ({sign})")
        print("  (positive = molecules plus tordues ont plus de radicaux)")
    else:
        print("  pas assez de donnees")
    print()

    # Top aromatiques planes
    print(f"=== Top {args.k} structures planes+aromatiques "
          f"(angle <= {args.max_angle}, clar >= {args.min_clar})")
    rows = top_aromatic_planar(conn, h=args.h, k=args.k,
                                max_angle=args.max_angle,
                                min_clar=args.min_clar)
    if rows:
        for r in rows:
            cbo = f"{r['cbo_mean_hex']:.2f}" if r['cbo_mean_hex'] is not None else "-"
            print(f"  {r['h']:>3} {r['config']:>20} {r['mol']:>30} sol_{r['sol_idx']:<3} "
                  f"angle={r['angle_deg']:.2f} Clar={r['clar_number']} "
                  f"covers={r['n_clar_covers']} cbo_hex_mean={cbo} "
                  f"rad={r['n_radicals']}")
    else:
        print("  (aucune)")
    print()

    # Top radicaux planes
    print(f"=== Top {args.k} structures planes+radicalaires "
          f"(angle <= {args.max_angle}, radicaux >= {args.min_radicals})")
    rows = top_radical_planar(conn, h=args.h, k=args.k,
                                max_angle=args.max_angle,
                                min_radicals=args.min_radicals)
    if rows:
        for r in rows:
            print(f"  {r['h']:>3} {r['config']:>20} {r['mol']:>30} sol_{r['sol_idx']:<3} "
                  f"angle={r['angle_deg']:.2f} radicaux={r['n_radicals']} "
                  f"clar={r['clar_number']} n_kekule={r['n_kekule']}")
    else:
        print("  (aucune)")
    print()
    conn.close()


if __name__ == "__main__":
    main()
