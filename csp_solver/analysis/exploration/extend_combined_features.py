"""Etend sol_combined_features aux sols h3-h6 (h7-h9 deja calcules).

Lance apres csp_solver/analysis/compute_combined_features.py.
"""

import sqlite3
import sys

from csp_solver.analysis.compute_combined_features import compute_features_for_h


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    sys.stdout.reconfigure(encoding="utf-8")

    for h in [3, 4, 5, 6]:
        compute_features_for_h(h, conn)

    total = conn.execute("SELECT COUNT(*) FROM sol_combined_features").fetchone()[0]
    print(f"\nTotal sol_combined_features apres extension : {total}")
    conn.close()


if __name__ == "__main__":
    main()
