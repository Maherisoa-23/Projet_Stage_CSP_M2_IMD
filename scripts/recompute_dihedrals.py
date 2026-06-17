"""Recalcule la nouvelle metrique de planeite : ecart-au-plan max sur les
angles diedres entre liaisons connectees (4 atomes A-B-C-D du squelette
carbone).

Cette metrique remplace l'angle ACP precedent (`angle_deg`) pour la
classification finale. L'ancien `angle_deg` est conserve dans la DB pour
comparaison.

Classification suggeree par Denis :
  tres_plan  : ecart < 10 deg
  acceptable : ecart < 25 deg
  non_plan   : ecart >= 25 deg

Le script :
  1. ALTER TABLE final_solutions ADD COLUMN max_dihedral_deg REAL
  2. Calcule pour chaque sol 'done' avec xyz_optimized_gz
  3. UPDATE par batch
  4. Idem pour la table 'solutions' (vue viewer) via jointure sur sol_dir

Total ~805 909 sols, estime ~6-10 min en single-thread.
"""

import gzip
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "experiments" / "final" / "final_h3_h9.db"

BOND_MIN_SQ = 1.20 ** 2
BOND_MAX_SQ = 2.00 ** 2

BATCH_SIZE = 2000     # UPDATE par batch
LOG_EVERY = 10000     # progression toutes les 10k sols


# ------------------------------ Compute --------------------------------

def parse_xyz_carbons_only(text):
    lines = text.split("\n", 2)
    if len(lines) < 2:
        return None
    try:
        n_total = int(lines[0].strip())
    except ValueError:
        return None
    coords = []
    if len(lines) >= 3:
        body = lines[2].split("\n")
    else:
        body = []
    for ln in body[:n_total]:
        p = ln.split()
        if len(p) < 4:
            continue
        if p[0].upper() != "C":
            continue
        try:
            coords.append((float(p[1]), float(p[2]), float(p[3])))
        except ValueError:
            continue
    if not coords:
        return None
    return np.array(coords, dtype=np.float64)


def detect_bonds(coords):
    n = len(coords)
    diff = coords[:, None, :] - coords[None, :, :]
    d2 = np.sum(diff * diff, axis=2)
    iu = np.triu_indices(n, k=1)
    d2_pairs = d2[iu]
    mask = (d2_pairs >= BOND_MIN_SQ) & (d2_pairs <= BOND_MAX_SQ)
    return list(zip(iu[0][mask].tolist(), iu[1][mask].tolist()))


def max_dihedral_ecart(coords, bonds):
    n = len(coords)
    adj = [[] for _ in range(n)]
    for u, v in bonds:
        adj[u].append(v)
        adj[v].append(u)

    chains = []
    for u, v in bonds:
        b, c = (u, v) if u < v else (v, u)
        for a in adj[b]:
            if a == c:
                continue
            for d in adj[c]:
                if d == b or d == a:
                    continue
                chains.append((a, b, c, d))
    if not chains:
        return None

    chains = np.array(chains)
    A = coords[chains[:, 0]]
    B = coords[chains[:, 1]]
    C = coords[chains[:, 2]]
    D = coords[chains[:, 3]]
    b1 = B - A
    b2 = C - B
    b3 = D - C
    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    x = np.einsum("ij,ij->i", n1, n2)
    b2norm = np.linalg.norm(b2, axis=1)
    y = b2norm * np.einsum("ij,ij->i", b1, n2)
    dihedrals = np.degrees(np.arctan2(y, x))
    abs_d = np.abs(dihedrals)
    devs = np.minimum(abs_d, 180.0 - abs_d)
    return float(devs.max())


def compute_one(blob):
    try:
        text = gzip.decompress(blob).decode("utf-8", errors="replace")
        coords = parse_xyz_carbons_only(text)
        if coords is None or len(coords) < 4:
            return None
        bonds = detect_bonds(coords)
        if not bonds:
            return None
        return max_dihedral_ecart(coords, bonds)
    except Exception:
        return None


# ------------------------------ DB ops ---------------------------------

def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return any(r[1] == column for r in rows)


def ensure_column(conn, table, column, sql_type):
    if not column_exists(conn, table, column):
        print(f"  ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        conn.commit()
    else:
        print(f"  Column {table}.{column} already exists")


def populate_final_solutions(conn):
    """Calcule max_dihedral_deg pour chaque final_solutions.done avec xyz."""
    print("\n=== Populate final_solutions.max_dihedral_deg ===")
    cur = conn.cursor()

    total = cur.execute(
        "SELECT COUNT(*) FROM final_solutions "
        "WHERE status='done' AND xyz_optimized_gz IS NOT NULL "
        "  AND max_dihedral_deg IS NULL"
    ).fetchone()[0]
    print(f"  A traiter : {total:,}")
    if total == 0:
        return 0

    # Iterer en streaming
    src = conn.cursor()
    src.execute(
        "SELECT sol_id, xyz_optimized_gz FROM final_solutions "
        "WHERE status='done' AND xyz_optimized_gz IS NOT NULL "
        "  AND max_dihedral_deg IS NULL"
    )

    buf = []
    n_done = 0
    n_err = 0
    t_start = time.perf_counter()
    t_last = t_start

    while True:
        row = src.fetchone()
        if row is None:
            break
        sol_id, blob = row
        val = compute_one(blob)
        if val is None:
            n_err += 1
        buf.append((val, sol_id))

        if len(buf) >= BATCH_SIZE:
            cur.executemany(
                "UPDATE final_solutions SET max_dihedral_deg=? WHERE sol_id=?",
                buf,
            )
            conn.commit()
            n_done += len(buf)
            buf = []
            if n_done % LOG_EVERY == 0 or n_done >= total:
                now = time.perf_counter()
                rate = n_done / (now - t_start)
                eta = (total - n_done) / max(rate, 1)
                print(f"  {n_done:>8,}/{total:,}  ({100*n_done/total:5.1f}%)  "
                      f"{rate:6.0f} sols/s  ETA {eta/60:5.1f}min  errs={n_err}")
                t_last = now

    if buf:
        cur.executemany(
            "UPDATE final_solutions SET max_dihedral_deg=? WHERE sol_id=?",
            buf,
        )
        conn.commit()
        n_done += len(buf)

    dt = time.perf_counter() - t_start
    print(f"  DONE : {n_done:,} sols traitees en {dt/60:.1f} min  "
          f"({n_done/dt:.0f} sols/s)  errs={n_err}")
    return n_done


_SOL_DIR_RE = re.compile(
    r"^final/h(\d+)/([^/]+)/([^/]+)/sol(\d+)$"
)


def propagate_to_solutions(conn):
    """Propage max_dihedral_deg de final_solutions vers solutions via sol_dir.

    solutions.sol_dir = 'final/h{N}/{cfg}/{graph}/sol{idx}'.
    Pour les sols Ctopo, sol_dir pointe vers C1 (reuse) : on extrait quand
    meme size_h+graph+sol_index du sol_dir, et on cherche dans final_solutions
    le row C1 correspondant.
    """
    print("\n=== Propagate solutions.max_dihedral_deg ===")
    cur = conn.cursor()
    total = cur.execute(
        "SELECT COUNT(*) FROM solutions WHERE max_dihedral_deg IS NULL"
    ).fetchone()[0]
    print(f"  A traiter : {total:,}")

    # On joint via parse du sol_dir. Le plus efficace : UPDATE via sous-requete.
    # Mais SQLite ne joint pas facilement sur des sous-strings ; on construit
    # un index temporaire sol_id -> value, puis on associe.
    t_start = time.perf_counter()

    # 1. Build map (size_h, config_in_dir, graph_name, sol_index) -> max_dihedral
    print("  Building lookup map from final_solutions...")
    fs_map = {}
    for sh, cfg, gn, si, val in cur.execute(
        "SELECT size_h, config, graph_name, sol_index, max_dihedral_deg "
        "FROM final_solutions WHERE max_dihedral_deg IS NOT NULL"
    ):
        fs_map[(sh, cfg, gn, si)] = val
    print(f"  Lookup size : {len(fs_map):,}")

    # 2. Iter solutions, parse sol_dir, lookup, batch UPDATE
    src = conn.cursor()
    src.execute("SELECT id, sol_dir FROM solutions WHERE max_dihedral_deg IS NULL")
    buf = []
    n_done = 0
    n_skip = 0
    while True:
        row = src.fetchone()
        if row is None:
            break
        sol_id, sol_dir = row
        m = _SOL_DIR_RE.match((sol_dir or "").replace("\\", "/").rstrip("/"))
        if not m:
            n_skip += 1
            continue
        sh, cfg, gn, si = int(m.group(1)), m.group(2), m.group(3), int(m.group(4))
        val = fs_map.get((sh, cfg, gn, si))
        if val is None:
            n_skip += 1
            continue
        buf.append((val, sol_id))
        if len(buf) >= BATCH_SIZE:
            cur.executemany(
                "UPDATE solutions SET max_dihedral_deg=? WHERE id=?", buf
            )
            conn.commit()
            n_done += len(buf)
            buf = []
            if n_done % LOG_EVERY == 0:
                rate = n_done / (time.perf_counter() - t_start)
                print(f"  {n_done:>8,}/{total:,}  ({100*n_done/total:5.1f}%)  "
                      f"{rate:6.0f} sols/s")

    if buf:
        cur.executemany(
            "UPDATE solutions SET max_dihedral_deg=? WHERE id=?", buf
        )
        conn.commit()
        n_done += len(buf)

    dt = time.perf_counter() - t_start
    print(f"  DONE : {n_done:,} updates, {n_skip:,} skip (no match)  "
          f"en {dt/60:.1f}min")


# ------------------------------ Main -----------------------------------

def main():
    print(f"DB : {DB_PATH}")
    print(f"Size : {DB_PATH.stat().st_size / 1024 / 1024:.0f} MB")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    print("\n--- Ensure columns ---")
    ensure_column(conn, "final_solutions", "max_dihedral_deg", "REAL")
    ensure_column(conn, "solutions", "max_dihedral_deg", "REAL")

    populate_final_solutions(conn)
    propagate_to_solutions(conn)

    print("\n--- Stats apres update ---")
    for h in [3, 4, 5, 6, 7, 8, 9]:
        for cfg in ["C1", "C2", "C3", "Ctopo"]:
            n_tot = conn.execute(
                "SELECT COUNT(*) FROM solutions WHERE h=? AND config=?",
                (f"h{h}", cfg),
            ).fetchone()[0]
            if n_tot == 0:
                continue
            n_tres = conn.execute(
                "SELECT COUNT(*) FROM solutions WHERE h=? AND config=? "
                "AND max_dihedral_deg < 10",
                (f"h{h}", cfg),
            ).fetchone()[0]
            n_acc = conn.execute(
                "SELECT COUNT(*) FROM solutions WHERE h=? AND config=? "
                "AND max_dihedral_deg >= 10 AND max_dihedral_deg < 25",
                (f"h{h}", cfg),
            ).fetchone()[0]
            n_non = conn.execute(
                "SELECT COUNT(*) FROM solutions WHERE h=? AND config=? "
                "AND max_dihedral_deg >= 25",
                (f"h{h}", cfg),
            ).fetchone()[0]
            print(f"  h{h} {cfg:<6} : {n_tot:>7,}  "
                  f"tres_plan={n_tres:>6,} ({100*n_tres/n_tot:4.1f}%)  "
                  f"acc={n_acc:>6,} ({100*n_acc/n_tot:4.1f}%)  "
                  f"non_plan={n_non:>6,} ({100*n_non/n_tot:4.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
