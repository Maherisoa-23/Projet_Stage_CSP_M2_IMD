"""Idem test_config_motifs.py mais affiche aussi le NOMBRE de sols plans
absolu (pas que les %)."""

import sqlite3
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db)

    VARIANTS = [
        ("C1 baseline",          "1=1"),
        ("C-mot w4 strict",       "smf.has_bl_strict_w4 = 0"),
        ("C-mot w5 strict",       "smf.has_bl_strict_w5 = 0"),
        ("C-mot w4+w5 strict",    "smf.has_bl_strict_w4 = 0 AND smf.has_bl_strict_w5 = 0"),
        ("C-mot w4 loose",        "smf.has_bl_loose_w4 = 0"),
        ("C-mot w5 loose",        "smf.has_bl_loose_w5 = 0"),
        ("C-mot loose w4+w5",     "smf.has_bl_loose_w4 = 0 AND smf.has_bl_loose_w5 = 0"),
        ("C-mot + fav w5",        "smf.has_bl_strict_w4 = 0 AND smf.has_bl_strict_w5 = 0 AND smf.has_fav_w5 = 1"),
        ("Pb1",                   "sfc.n_pent <= 1"),
        ("Pb1 + C-mot strict",    "sfc.n_pent <= 1 AND smf.has_bl_strict_w4 = 0 AND smf.has_bl_strict_w5 = 0"),
        ("Pb1 + C-mot loose",     "sfc.n_pent <= 1 AND smf.has_bl_loose_w4 = 0 AND smf.has_bl_loose_w5 = 0"),
    ]

    print("="*92)
    print("COMPARATIF AVEC NOMBRES ABSOLUS")
    print("="*92)

    # Reference C1/C2/C3 reels
    print("\n--- Reference : C1/C2/C3 reelles (compte de PLAN absolu) ---")
    print(f"  {'h':<4} {'cfg':<6} {'N_total':>10} {'N_plan':>10} {'%PLAN':>7} {'median':>8} {'max':>7}")
    for h in ['h7','h8','h9']:
        for cfg in ['C1','C2','C3']:
            r = conn.execute(
                "SELECT COUNT(*), SUM(verdict='plan') FROM solutions "
                "WHERE h=? AND config=? AND angle_deg IS NOT NULL",
                (h, cfg)).fetchone()
            n, np_ = r
            if not n: continue
            med = conn.execute(
                "SELECT angle_deg FROM solutions WHERE h=? AND config=? AND angle_deg IS NOT NULL "
                "ORDER BY angle_deg LIMIT 1 OFFSET ?", (h, cfg, n//2)).fetchone()[0]
            mx = conn.execute(
                "SELECT MAX(angle_deg) FROM solutions WHERE h=? AND config=? AND angle_deg IS NOT NULL",
                (h, cfg)).fetchone()[0]
            print(f"  {h:<4} {cfg:<6} {n:>10d} {np_:>10d} {100*np_/n:>6.1f}% {med:>7.2f}° {mx:>6.2f}°")

    # Variantes virtuelles
    for h in ['h7', 'h8', 'h9']:
        print(f"\n--- {h} : variantes virtuelles (filtre sols C1) ---")
        print(f"  {'variante':<26} {'N_total':>10} {'N_plan':>10} {'%PLAN':>7} {'median':>8} {'max':>7}")
        for name, pred in VARIANTS:
            q = f"""
                SELECT angle_deg FROM solutions s
                JOIN sol_motif_features smf ON smf.sol_id = s.id
                JOIN sol_features sf  ON sf.sol_id  = s.id
                JOIN sol_features_c9 sfc ON sfc.sol_id = s.id
                WHERE s.h=? AND s.config='C1' AND s.angle_deg IS NOT NULL AND ({pred})
                ORDER BY s.angle_deg
            """
            vals = [r[0] for r in conn.execute(q, (h,)).fetchall()]
            n = len(vals)
            if n == 0:
                print(f"  {name:<26} {'-':>10}"); continue
            n_plan = sum(1 for v in vals if v <= 10.0)
            med = vals[n//2]
            mx = vals[-1]
            print(f"  {name:<26} {n:>10d} {n_plan:>10d} {100*n_plan/n:>6.1f}% {med:>7.2f}° {mx:>6.2f}°")

    conn.close()


if __name__ == "__main__":
    main()
