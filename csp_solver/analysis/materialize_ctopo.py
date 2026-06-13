"""Materialise la configuration Ctopo (= recommandation finale) dans la DB
du viewer en post-traitement d'un run C1, et SUPPRIME les anciennes configs
exploratoires (C4, C5, C8, C48) qui ont ete remplacees.

Ctopo (Topologie complete) :
    - has_bl_r2_loose = 0  (aucun motif rayon-2 de la blacklist universelle
      observe dans la solution)
    - skel_n_peri >= 4     (squelette compact : au moins 4 atomes
      partages par >=3 cycles)

Note : depuis la Phase E (juin 2026), Ctopo existe aussi comme vraie
contrainte CSP solveur (cf. `csp_solver/utils/model.py`, flags
`ctopo_filter` + `ctopo_min_n_peri`). Ce script reste utile pour rejouer
le filtre sur une DB C1 existante sans relancer le solveur.

Sols sources : C1 done h3-h9. Aucun XYZ duplique (sol_dir pointe vers C1).
"""

import sqlite3
import sys


CONFIG_NAME = "Ctopo"
PREDICATE_SQL = "scf.has_bl_r2_loose = 0 AND scf.skel_n_peri >= 4"

OBSOLETE_CONFIGS = ['C4', 'C5', 'C8', 'C48']


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")

    print("=== Materialize Ctopo + cleanup configs obsoletes ===\n")

    # Snapshot avant
    n_sol_before = conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0]
    n_mol_before = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
    n_cfg_before = conn.execute("SELECT COUNT(*) FROM configs").fetchone()[0]
    print(f"Before  : solutions={n_sol_before}, molecules={n_mol_before}, configs={n_cfg_before}")

    # 1. Supprimer les configs obsoletes
    print(f"\n--- Suppression des configs obsoletes {OBSOLETE_CONFIGS} ---")
    placeholders = ",".join(f"'{c}'" for c in OBSOLETE_CONFIGS + [CONFIG_NAME])
    n_del_sol = conn.execute(f"DELETE FROM solutions WHERE config IN ({placeholders})").rowcount
    n_del_mol = conn.execute(f"DELETE FROM molecules WHERE config IN ({placeholders})").rowcount
    n_del_cfg = conn.execute(f"DELETE FROM configs WHERE name IN ({placeholders})").rowcount
    conn.commit()
    print(f"  supprime : solutions={n_del_sol}, molecules={n_del_mol}, configs={n_del_cfg}")

    # 2. INSERT solutions pour Ctopo depuis C1 done filtre
    print(f"\n--- Insertion {CONFIG_NAME} (predicat : {PREDICATE_SQL}) ---")
    conn.execute(f"""
        INSERT INTO solutions
            (h, config, mol, sol_idx, sizes, verdict, planar, angle_deg,
             rmsd, height, n_attempts, deterministic, sol_dir)
        SELECT
            s.h, '{CONFIG_NAME}', s.mol, s.sol_idx, s.sizes, s.verdict, s.planar,
            s.angle_deg, s.rmsd, s.height, s.n_attempts, s.deterministic,
            s.sol_dir
        FROM solutions s
        JOIN sol_combined_features scf ON scf.sol_id = s.id
        WHERE s.config = 'C1' AND ({PREDICATE_SQL})
    """)
    conn.commit()
    n_sol_inserted = conn.execute(
        "SELECT COUNT(*) FROM solutions WHERE config=?",
        (CONFIG_NAME,)
    ).fetchone()[0]
    print(f"  inseres : {n_sol_inserted} solutions")

    # 3. Reconstruire molecules
    print(f"\n--- Reconstruction molecules pour {CONFIG_NAME} ---")
    conn.execute(f"""
        INSERT INTO molecules
            (h, config, mol, n_solutions_csp, n_md_completed, n_geom_infeasible,
             n_xtb_failed, n_plans, n_non_plans, min_angle, max_angle,
             original_planar, original_angle_deg, job_status, job_duration_sec)
        SELECT
            h,
            '{CONFIG_NAME}' AS config,
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
        WHERE config = '{CONFIG_NAME}'
        GROUP BY h, mol
    """)
    conn.commit()
    n_mol_inserted = conn.execute(
        "SELECT COUNT(*) FROM molecules WHERE config=?",
        (CONFIG_NAME,)
    ).fetchone()[0]
    print(f"  {n_mol_inserted} molecules")

    # 4. Reconstruire configs
    print(f"\n--- Reconstruction agregats configs ---")
    conn.execute(f"""
        INSERT INTO configs
            (h, name, n_molecules, n_solutions, n_geom_infeasible, n_plans, n_non_plans)
        SELECT
            h,
            '{CONFIG_NAME}',
            COUNT(DISTINCT mol),
            SUM(n_md_completed),
            0,
            SUM(n_plans),
            SUM(n_non_plans)
        FROM molecules
        WHERE config = '{CONFIG_NAME}'
        GROUP BY h
    """)
    conn.commit()

    # 5. Resume
    print(f"\n=== Verification finale ===")
    n_sol_after = conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0]
    n_mol_after = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
    n_cfg_after = conn.execute("SELECT COUNT(*) FROM configs").fetchone()[0]
    print(f"After   : solutions={n_sol_after}, molecules={n_mol_after}, configs={n_cfg_after}")

    print(f"\n--- Stats par h (C1 / C2 / C3 / {CONFIG_NAME}) ---")
    print(f"  {'h':>4} {'cfg':<6} {'N_sols':>10} {'N_plans':>10} {'%PLAN':>8} {'N_mols':>8}")
    for h in ['h3','h4','h5','h6','h7','h8','h9']:
        for cfg in ['C1','C2','C3',CONFIG_NAME]:
            r = conn.execute(
                "SELECT n_solutions, n_plans, n_molecules FROM configs WHERE h=? AND name=?",
                (h, cfg)
            ).fetchone()
            if r:
                ns, np_, nm = r
                pct = 100*np_/ns if ns else 0
                print(f"  {h:>4} {cfg:<6} {ns:>10} {np_:>10} {pct:>7.2f}% {nm:>8}")

    conn.close()
    print(f"\n=== DONE ===")


if __name__ == "__main__":
    main()
