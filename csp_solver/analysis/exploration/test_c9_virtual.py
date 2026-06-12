"""Teste C9 virtuelle et des variantes proches contre C3 reel.

C9 = Pb1 + adj_77=0 + n_sum<=4 + triple_jct_defect=0
   = filtrage sur sols C1 done

On compare aussi des variantes pour isoler la contribution de chaque
contrainte (en particulier triple_jct_defect).

Sortie : tableau h x variante avec N, %PLAN, mediane, max.
"""

import sqlite3
import sys


VARIANTS = {
    "C1_baseline":             "1=1",
    "Pb1 only":                "sfc.n_pent <= 1",
    "adj_77=0":                "sf.adj_77 = 0",
    "n_sum<=4":                "sf.n_sum <= 4",
    "triple_jct_def=0":        "sfc.triple_jct_defect = 0",
    "Pb1 + adj_77=0":          "sfc.n_pent <= 1 AND sf.adj_77 = 0",
    "Pb1 + tjd=0":             "sfc.n_pent <= 1 AND sfc.triple_jct_defect = 0",
    "adj_77=0 + tjd=0":        "sf.adj_77 = 0 AND sfc.triple_jct_defect = 0",
    "C9 (Pb1+adj_77+tjd)":     "sfc.n_pent <= 1 AND sf.adj_77 = 0 AND sfc.triple_jct_defect = 0",
    "C9_full (+n_sum<=4)":     "sfc.n_pent <= 1 AND sf.adj_77 = 0 AND sfc.triple_jct_defect = 0 AND sf.n_sum <= 4",
}


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    sys.stdout.reconfigure(encoding="utf-8")

    print("=== Test C9 virtuelle et variantes ===\n")
    print("Reference : C3 reel par h\n")

    # Reference C3 reel
    for h in ["h6", "h7", "h8", "h9"]:
        r = conn.execute("""
            SELECT COUNT(*), SUM(verdict='plan'), MIN(angle_deg), MAX(angle_deg)
            FROM solutions WHERE h=? AND config='C3' AND angle_deg IS NOT NULL
        """, (h,)).fetchone()
        n, np, mn, mx = r
        if not n:
            print(f"  {h} C3 reel : aucune sol"); continue
        # mediane via OFFSET
        med = conn.execute("""
            SELECT angle_deg FROM solutions WHERE h=? AND config='C3' AND angle_deg IS NOT NULL
            ORDER BY angle_deg LIMIT 1 OFFSET ?
        """, (h, n//2)).fetchone()[0]
        print(f"  {h} C3 reel : N={n:>6}  %PLAN={100*np/n:>5.1f}%  median={med:>6.2f}  max={mx:>6.2f}")

    print("\n=== Variantes virtuelles (filtre sur C1 done) ===\n")

    for h in ["h6", "h7", "h8", "h9"]:
        print(f"\n--- {h} ---")
        print(f"  {'variante':<28} {'N':>8} {'%PLAN':>7} {'median':>8} {'max':>8}")
        for name, pred in VARIANTS.items():
            # Construit la requete : on filtre sur C1 done sols
            # On joint sol_features (sf) et sol_features_c9 (sfc) sur sol_id
            q = f"""
                SELECT angle_deg
                FROM solutions s
                JOIN sol_features sf  ON sf.sol_id  = s.id
                JOIN sol_features_c9 sfc ON sfc.sol_id = s.id
                WHERE s.h=? AND s.config='C1' AND s.angle_deg IS NOT NULL
                  AND ({pred})
                ORDER BY s.angle_deg
            """
            rows = conn.execute(q, (h,)).fetchall()
            n = len(rows)
            if n == 0:
                print(f"  {name:<28} {'-':>8}"); continue
            vals = [r[0] for r in rows]
            n_plan = sum(1 for v in vals if v <= 10.0)
            med = vals[n//2]
            mx = vals[-1]
            print(f"  {name:<28} {n:>8} {100*n_plan/n:>6.1f}% {med:>7.2f}° {mx:>7.2f}°")

    conn.close()


if __name__ == "__main__":
    main()
