"""Migration : bascule complete vers la metrique angle diedre.

Avant : verdict / planar / angle_deg / n_plans bases sur l'ancien angle ACP.
Apres : verdict in {tres_plan, acceptable, non_plan, geom_infeasible, xtb_failed}
        + planar = 1 si tres_plan or acceptable, 0 sinon
        + angle_deg = max_dihedral_deg (nouveau standard)
        + l'ancienne ACP est preservee dans angle_deg_acp etc.

Tables modifiees :
  solutions : verdict + planar + angle_deg (+ angle_deg_acp preserve)
  molecules : n_plans + n_non_plans recalcules + ajout n_tres_plan, n_acceptable
              + min_angle / max_angle recalcules en diedre
              + min_angle_acp, max_angle_acp preserves
  configs   : n_plans + n_non_plans recalcules + ajout n_tres_plan, n_acceptable
"""
import sqlite3
import time
from pathlib import Path

DB = Path("experiments/final/final_h3_h9.db")


def col_exists(c, table, col):
    return any(r[1] == col for r in c.execute(f"PRAGMA table_info('{table}')"))


def add_col(c, table, col, sql_type):
    if not col_exists(c, table, col):
        print(f"  ALTER {table} ADD {col} {sql_type}")
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}")
    else:
        print(f"  {table}.{col} exists, skip")


def main():
    print(f"DB: {DB}")
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA synchronous = NORMAL")

    # ============ 1. ALTER TABLE ============
    print("\n=== 1. ALTER TABLE (ajouts colonnes) ===")
    add_col(c, "solutions", "angle_deg_acp", "REAL")
    add_col(c, "molecules", "min_angle_acp", "REAL")
    add_col(c, "molecules", "max_angle_acp", "REAL")
    add_col(c, "molecules", "original_angle_deg_acp", "REAL")
    add_col(c, "molecules", "original_planar_acp", "INTEGER")
    add_col(c, "molecules", "n_plans_acp", "INTEGER")
    add_col(c, "molecules", "n_non_plans_acp", "INTEGER")
    add_col(c, "molecules", "n_tres_plan", "INTEGER")
    add_col(c, "molecules", "n_acceptable", "INTEGER")
    add_col(c, "configs", "n_plans_acp", "INTEGER")
    add_col(c, "configs", "n_non_plans_acp", "INTEGER")
    add_col(c, "configs", "n_tres_plan", "INTEGER")
    add_col(c, "configs", "n_acceptable", "INTEGER")
    c.commit()

    # ============ 2. solutions ============
    print("\n=== 2. solutions : preserve angle ACP + bascule verdict/planar/angle_deg ===")
    t0 = time.perf_counter()

    # Copie l'ancien angle_deg dans angle_deg_acp si pas deja fait
    n = c.execute(
        "UPDATE solutions SET angle_deg_acp = angle_deg "
        "WHERE angle_deg_acp IS NULL AND angle_deg IS NOT NULL"
    ).rowcount
    print(f"  copie angle_deg -> angle_deg_acp : {n:,} rows")
    c.commit()

    # Bascule angle_deg = max_dihedral_deg (nouveau standard)
    n = c.execute(
        "UPDATE solutions SET angle_deg = max_dihedral_deg "
        "WHERE max_dihedral_deg IS NOT NULL"
    ).rowcount
    print(f"  bascule angle_deg = max_dihedral_deg : {n:,} rows")
    c.commit()

    # Recalcule verdict en 3 categories pour les sols sans geom_infeasible/xtb_failed
    n_tp = c.execute(
        "UPDATE solutions SET verdict='tres_plan', planar=1 "
        "WHERE angle_deg IS NOT NULL AND angle_deg < 10 "
        "  AND verdict NOT IN ('geom_infeasible', 'xtb_failed')"
    ).rowcount
    n_a = c.execute(
        "UPDATE solutions SET verdict='acceptable', planar=1 "
        "WHERE angle_deg IS NOT NULL AND angle_deg >= 10 AND angle_deg < 25 "
        "  AND verdict NOT IN ('geom_infeasible', 'xtb_failed')"
    ).rowcount
    n_np = c.execute(
        "UPDATE solutions SET verdict='non_plan', planar=0 "
        "WHERE angle_deg IS NOT NULL AND angle_deg >= 25 "
        "  AND verdict NOT IN ('geom_infeasible', 'xtb_failed')"
    ).rowcount
    c.commit()
    print(f"  verdict tres_plan: {n_tp:,}  acceptable: {n_a:,}  non_plan: {n_np:,}")
    print(f"  total temps : {time.perf_counter()-t0:.1f}s")

    # ============ 3. molecules : recalc agregats ============
    print("\n=== 3. molecules : recalcul agregats ===")
    t0 = time.perf_counter()

    # Preserve l'ancien dans *_acp si pas deja fait
    for src, dst in [
        ("n_plans", "n_plans_acp"),
        ("n_non_plans", "n_non_plans_acp"),
        ("min_angle", "min_angle_acp"),
        ("max_angle", "max_angle_acp"),
        ("original_angle_deg", "original_angle_deg_acp"),
        ("original_planar", "original_planar_acp"),
    ]:
        n = c.execute(
            f"UPDATE molecules SET {dst} = {src} WHERE {dst} IS NULL AND {src} IS NOT NULL"
        ).rowcount
        print(f"  preserve {src} -> {dst} : {n:,} rows")
    c.commit()

    # Recalcule depuis solutions
    print("  recalcul depuis solutions...")
    c.execute("""
        UPDATE molecules
        SET n_tres_plan = COALESCE((
            SELECT COUNT(*) FROM solutions s
            WHERE s.h = molecules.h AND s.config = molecules.config AND s.mol = molecules.mol
              AND s.verdict = 'tres_plan'
        ), 0),
            n_acceptable = COALESCE((
            SELECT COUNT(*) FROM solutions s
            WHERE s.h = molecules.h AND s.config = molecules.config AND s.mol = molecules.mol
              AND s.verdict = 'acceptable'
        ), 0),
            n_non_plans = COALESCE((
            SELECT COUNT(*) FROM solutions s
            WHERE s.h = molecules.h AND s.config = molecules.config AND s.mol = molecules.mol
              AND s.verdict = 'non_plan'
        ), 0),
            min_angle = (
            SELECT MIN(s.angle_deg) FROM solutions s
            WHERE s.h = molecules.h AND s.config = molecules.config AND s.mol = molecules.mol
              AND s.angle_deg IS NOT NULL AND s.verdict NOT IN ('geom_infeasible','xtb_failed')
        ),
            max_angle = (
            SELECT MAX(s.angle_deg) FROM solutions s
            WHERE s.h = molecules.h AND s.config = molecules.config AND s.mol = molecules.mol
              AND s.angle_deg IS NOT NULL AND s.verdict NOT IN ('geom_infeasible','xtb_failed')
        )
    """)
    # n_plans = TP + A (cumulatif)
    c.execute(
        "UPDATE molecules SET n_plans = n_tres_plan + n_acceptable"
    )
    # original_* : pas de recalcul possible (besoin du xyz original), on
    # set a NULL pour eviter confusion. _acp preserve l'ancienne valeur.
    c.execute(
        "UPDATE molecules SET original_angle_deg = NULL, original_planar = NULL"
    )
    c.commit()
    print(f"  total temps : {time.perf_counter()-t0:.1f}s")

    # ============ 4. configs : agreger depuis molecules ============
    print("\n=== 4. configs : recalc agregats ===")
    t0 = time.perf_counter()

    # Preserve ancien
    for src, dst in [("n_plans", "n_plans_acp"), ("n_non_plans", "n_non_plans_acp")]:
        n = c.execute(
            f"UPDATE configs SET {dst} = {src} WHERE {dst} IS NULL AND {src} IS NOT NULL"
        ).rowcount
        print(f"  preserve configs.{src} -> {dst} : {n:,}")
    c.commit()

    c.execute("""
        UPDATE configs
        SET n_tres_plan = COALESCE((
            SELECT SUM(n_tres_plan) FROM molecules m
            WHERE m.h = configs.h AND m.config = configs.name
        ), 0),
            n_acceptable = COALESCE((
            SELECT SUM(n_acceptable) FROM molecules m
            WHERE m.h = configs.h AND m.config = configs.name
        ), 0),
            n_non_plans = COALESCE((
            SELECT SUM(n_non_plans) FROM molecules m
            WHERE m.h = configs.h AND m.config = configs.name
        ), 0)
    """)
    c.execute("UPDATE configs SET n_plans = n_tres_plan + n_acceptable")
    c.commit()
    print(f"  total temps : {time.perf_counter()-t0:.1f}s")

    # ============ 5. Stats finales ============
    print("\n=== Stats apres migration ===")
    print(f"{'h':<4} {'cfg':<8} {'N_sols':>8} {'TP':>6} {'A':>6} {'%plan':>7} {'%TP':>6}")
    for h, name, ns, np, nnp, ntp, nacc in c.execute(
        "SELECT h, name, n_solutions, n_plans, n_non_plans, n_tres_plan, n_acceptable "
        "FROM configs ORDER BY h, name"
    ):
        pct_plan = (100.0 * np / ns) if ns else 0
        pct_tp = (100.0 * ntp / ns) if ns else 0
        print(f"{h:<4} {name:<8} {ns:>8,} {ntp:>6,} {nacc:>6,} {pct_plan:>6.1f}% {pct_tp:>5.1f}%")

    c.close()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
