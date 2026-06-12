"""Materialise les configs virtuelles C4/C5/C8/C48 dans la DB du viewer.

Pour chaque sol C1 done qui satisfait le predicat Cn :
  - INSERT INTO solutions avec config=Cn (nouveau id AUTOINCREMENT)
    Garde sol_dir pointant vers C1 (XYZ original via xyz_files VIEW).
  - Agregations stockees dans molecules + configs.

Configs virtuelles :
  C4   : adj_77 == 0
  C5   : adj_55 + adj_77 == 0  (= adj_55 == 0 AND adj_77 == 0)
  C8   : n_sum <= 4
  C48  : adj_77 == 0 AND n_sum <= 4

Idempotent : DROP les rows config IN ('C4','C5','C8','C48') avant re-INSERT.
"""

import sqlite3
import time


VIRTUAL_CONFIGS = {
    'C4':  "sf.adj_77 = 0",
    'C5':  "sf.adj_77 = 0 AND sf.adj_55 = 0",
    'C8':  "sf.n_sum <= 4",
    'C48': "sf.adj_77 = 0 AND sf.n_sum <= 4",
}


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")

    print("=== Materialize virtual configs ===")
    n_features = conn.execute("SELECT COUNT(*) FROM sol_features").fetchone()[0]
    print(f"  sol_features: {n_features} rows")

    # 1. Cleanup : DROP rows existantes des configs virtuelles
    cfg_names = list(VIRTUAL_CONFIGS.keys())
    placeholders = ",".join(f"'{c}'" for c in cfg_names)
    n_sol_before = conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0]
    n_mol_before = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
    print(f"  Before: solutions={n_sol_before}, molecules={n_mol_before}")

    print(f"\n  DROP existing rows for configs {cfg_names}...")
    conn.execute(f"DELETE FROM solutions WHERE config IN ({placeholders})")
    conn.execute(f"DELETE FROM molecules WHERE config IN ({placeholders})")
    conn.execute(f"DELETE FROM configs WHERE name IN ({placeholders})")
    conn.commit()

    # 2. INSERT solutions pour chaque config virtuelle
    for cfg_name, predicate in VIRTUAL_CONFIGS.items():
        print(f"\n  === {cfg_name} ({predicate}) ===")
        t0 = time.perf_counter()
        # INSERT depuis solutions WHERE config='C1' AND predicate satisfied
        # via JOIN avec sol_features. NB : sol_features.sol_id = solutions.id (cf migrate_final_to_viewer)
        conn.execute(f"""
            INSERT INTO solutions
                (h, config, mol, sol_idx, sizes, verdict, planar, angle_deg,
                 rmsd, height, n_attempts, deterministic, sol_dir)
            SELECT
                s.h, '{cfg_name}', s.mol, s.sol_idx, s.sizes, s.verdict, s.planar,
                s.angle_deg, s.rmsd, s.height, s.n_attempts, s.deterministic,
                s.sol_dir
            FROM solutions s
            JOIN sol_features sf ON sf.sol_id = s.id
            WHERE s.config = 'C1' AND {predicate}
        """)
        conn.commit()
        n_inserted = conn.execute(f"SELECT COUNT(*) FROM solutions WHERE config=?", (cfg_name,)).fetchone()[0]
        print(f"    INSERT solutions : {n_inserted} rows en {time.perf_counter()-t0:.1f}s")

    # 3. Reconstruire molecules pour ces configs (agregats)
    print("\n  Reconstruire molecules pour configs virtuelles...")
    for cfg_name in cfg_names:
        t0 = time.perf_counter()
        conn.execute(f"""
            INSERT INTO molecules
                (h, config, mol, n_solutions_csp, n_md_completed, n_geom_infeasible,
                 n_xtb_failed, n_plans, n_non_plans, min_angle, max_angle,
                 original_planar, original_angle_deg, job_status, job_duration_sec)
            SELECT
                h,
                '{cfg_name}' AS config,
                mol,
                COUNT(*) AS n_solutions_csp,
                COUNT(*) AS n_md_completed,
                0 AS n_geom_infeasible,
                SUM(CASE WHEN verdict='xtb_failed' THEN 1 ELSE 0 END) AS n_xtb_failed,
                SUM(CASE WHEN verdict='plan' THEN 1 ELSE 0 END) AS n_plans,
                SUM(CASE WHEN verdict='non_plan' THEN 1 ELSE 0 END) AS n_non_plans,
                MIN(angle_deg) AS min_angle,
                MAX(angle_deg) AS max_angle,
                NULL, NULL, 'ok', NULL
            FROM solutions
            WHERE config = '{cfg_name}'
            GROUP BY h, mol
        """)
        conn.commit()
        n_mol = conn.execute(f"SELECT COUNT(*) FROM molecules WHERE config=?", (cfg_name,)).fetchone()[0]
        print(f"    {cfg_name} molecules: {n_mol} en {time.perf_counter()-t0:.1f}s")

    # 4. Reconstruire configs (agregats globaux par h)
    print("\n  Reconstruire configs globaux...")
    for cfg_name in cfg_names:
        conn.execute(f"""
            INSERT INTO configs
                (h, name, n_molecules, n_solutions, n_geom_infeasible, n_plans, n_non_plans)
            SELECT
                h,
                '{cfg_name}',
                COUNT(DISTINCT mol),
                SUM(n_md_completed),
                0,
                SUM(n_plans),
                SUM(n_non_plans)
            FROM molecules
            WHERE config = '{cfg_name}'
            GROUP BY h
        """)
        conn.commit()

    # 5. Resume final
    print("\n=== Verification ===")
    n_sol_after = conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0]
    n_mol_after = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
    print(f"  After:  solutions={n_sol_after} (+{n_sol_after-n_sol_before})")
    print(f"          molecules={n_mol_after} (+{n_mol_after-n_mol_before})")

    print("\n  Stats par (h, config) :")
    print(f"  {'h':>4} {'config':<6} {'N_sols':>10} {'N_plans':>10} {'%PLAN':>8} {'N_mols':>8}")
    for cfg_name in ['C1','C2','C3'] + cfg_names:
        for r in conn.execute(f"""
            SELECT h, name, n_solutions, n_plans, n_molecules
            FROM configs
            WHERE name = ?
            ORDER BY h
        """, (cfg_name,)).fetchall():
            h, name, ns, np, nm = r
            pct = 100*np/ns if ns > 0 else 0
            print(f"  {h:>4} {name:<6} {ns:>10} {np:>10} {pct:>7.2f}% {nm:>8}")
    conn.close()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
