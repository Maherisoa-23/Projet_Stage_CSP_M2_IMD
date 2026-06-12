"""Copie les resultats xTB de C1.done vers C2/C3.pending pour les sols communes.

Justification :
  C2 et C3 ajoutent des contraintes au-dessus de C1, donc toute solution
  CSP-valide pour C2 (ou C3) est aussi CSP-valide pour C1. Match key :
  (size_h, graph_name, csp_solution_json).

  xTB est byte-deterministe (OMP_NUM_THREADS=1 + perturbation z structuree),
  donc une sol identique donne EXACTEMENT le meme resultat dans n'importe
  quelle config. -> Pas besoin de re-runner xTB sur les sols deja faites
  en C1.

Mode dry-run par defaut. --apply pour executer.
Idempotent : on peut le relancer N fois sans effet de bord.
"""

import argparse
import sqlite3
import time


COPY_FIELDS = [
    "verdict", "angle_deg", "energy_eh", "homo_lumo_ev",
    "cpu_time_s", "wall_time_s", "xyz_optimized_gz",
    "hostname", "started_at", "finished_at",
]


def copy_from_C1(conn, run_id, size_h, target_config, apply):
    """Copie C1.done -> target_config.pending pour (size_h, target_config).

    Retourne (n_pending_avant, n_matches, n_remain).
    """
    t0 = time.perf_counter()

    # Compter pending total
    n_pending = conn.execute(
        "SELECT COUNT(*) FROM final_solutions "
        "WHERE run_id=? AND size_h=? AND config=? AND status='pending'",
        (run_id, size_h, target_config),
    ).fetchone()[0]

    if n_pending == 0:
        return (0, 0, 0)

    # Fetch les matchs (sol_id cible + champs C1 a copier)
    fields_sel = ", ".join(f"c1.{f}" for f in COPY_FIELDS)
    rows = conn.execute(f"""
        SELECT c_tgt.sol_id AS sol_id_tgt, {fields_sel}
        FROM final_solutions c_tgt
        INNER JOIN final_solutions c1 ON
            c1.size_h = c_tgt.size_h
            AND c1.graph_name = c_tgt.graph_name
            AND c1.csp_solution_json = c_tgt.csp_solution_json
            AND c1.config = 'C1' AND c1.status = 'done'
        WHERE c_tgt.run_id = ?
          AND c_tgt.size_h = ?
          AND c_tgt.config = ?
          AND c_tgt.status = 'pending'
    """, (run_id, size_h, target_config)).fetchall()

    n_matches = len(rows)
    dt_select = time.perf_counter() - t0

    print(f"  h{size_h} {target_config} : pending={n_pending}  matchs={n_matches}  "
          f"remain_a_traiter={n_pending - n_matches}  (select en {dt_select:.1f}s)")

    if apply and n_matches > 0:
        t1 = time.perf_counter()
        sets = ", ".join(f"{f}=?" for f in COPY_FIELDS)
        update_sql = (
            f"UPDATE final_solutions SET status='done', {sets}, "
            f"error_message='copied_from_C1' "
            f"WHERE sol_id=? AND status='pending'"
        )
        # Chaque row : (sol_id_tgt, verdict, angle_deg, ...) -> reorder en (verdict, ..., sol_id_tgt)
        params = [tuple(r[1:]) + (r[0],) for r in rows]
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(update_sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        dt_apply = time.perf_counter() - t1
        print(f"     -> APPLIED {n_matches} copies en {dt_apply:.1f}s")

    return (n_pending, n_matches, n_pending - n_matches)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-id", type=int, default=1)
    ap.add_argument("--size-h", type=int, default=None,
                    help="Limiter a une taille (ex: 9). Sinon toutes (3..9)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=120.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")

    print(f"=== Copy C1 -> C2/C3 (mode={'APPLY' if args.apply else 'DRY RUN'}) ===")
    print()
    print("Creation de l'index de lookup (idempotent)...")
    t0 = time.perf_counter()
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_copy_lookup "
        "ON final_solutions(size_h, config, status, graph_name)"
    )
    print(f"  Index OK en {time.perf_counter()-t0:.1f}s")

    sizes = [args.size_h] if args.size_h else [3, 4, 5, 6, 7, 8, 9]

    grand_total_match = 0
    grand_total_remain = 0
    for size_h in sizes:
        print()
        print(f"=== h{size_h} ===")
        for target_cfg in ["C2", "C3"]:
            n_pend, n_match, n_remain = copy_from_C1(
                conn, args.run_id, size_h, target_cfg, args.apply
            )
            grand_total_match += n_match
            grand_total_remain += n_remain

    print()
    print("=== RESUME GLOBAL ===")
    print(f"  Total matchs (sols copiees) : {grand_total_match}")
    print(f"  Total restant a traiter      : {grand_total_remain}")
    if not args.apply:
        print()
        print("(dry-run, ajouter --apply pour executer)")

    conn.close()


if __name__ == "__main__":
    main()
