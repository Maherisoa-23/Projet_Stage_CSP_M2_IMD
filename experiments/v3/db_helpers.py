"""Helpers d'ingestion DB pour experiments_v3.

Schema = identique a csp_viewer/schema.sql + 2 colonnes ajoutees sur
'solutions' :
   - decision_path  TEXT  : 'mmff_sure_plan', 'mmff_sure_non_plan',
                            'mmff_gray_xtb_plan', 'mmff_gray_xtb_non_plan',
                            'mmff_failed_xtb_plan', 'mmff_failed_xtb_non_plan',
                            'mmff_*_xtb_failed', 'geom_infeasible'
   - mmff_angle_deg REAL  : angle PCA MMFF, NULL si MMFF a echoue

Le champ 'verdict' (existant) reste : 'plan' / 'non_plan' / 'geom_infeasible'
/ 'xtb_failed'. Une solution acceptee par MMFF seul a verdict='plan' avec
decision_path='mmff_sure_plan' : compatible avec csp_viewer existant.

Workflow par job (dans run_one_job_v3) :
  1. CSP + reconstruction + (MMFF | xTB) en scratch local
  2. ingest_mol_dir_v3() lit scratch + insere TOUT dans worker_db local (sqlite)
  3. scratch detruit, worker_db sur NFS
  4. finalize_v3 merge tous les worker DBs en db_v4.db
"""

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Optional


# Le SCHEMA est compatible db_v3 (=v2 schema) mais ajoute 2 colonnes optionnelles.
# Pour rester COMPATIBLE BACKWARD avec csp_viewer existant, on garde toutes les
# colonnes v2, juste etendues.

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS configs (
    h TEXT NOT NULL,
    name TEXT NOT NULL,
    n_molecules INTEGER NOT NULL DEFAULT 0,
    n_solutions INTEGER NOT NULL DEFAULT 0,
    n_geom_infeasible INTEGER NOT NULL DEFAULT 0,
    n_plans INTEGER NOT NULL DEFAULT 0,
    n_non_plans INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (h, name)
);

CREATE TABLE IF NOT EXISTS molecules (
    h TEXT NOT NULL,
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    n_solutions_csp INTEGER,
    n_md_completed INTEGER,
    n_geom_infeasible INTEGER NOT NULL DEFAULT 0,
    n_xtb_failed INTEGER NOT NULL DEFAULT 0,
    n_plans INTEGER NOT NULL DEFAULT 0,
    n_non_plans INTEGER NOT NULL DEFAULT 0,
    n_mmff_sure_plan INTEGER NOT NULL DEFAULT 0,
    n_mmff_sure_non_plan INTEGER NOT NULL DEFAULT 0,
    n_mmff_gray INTEGER NOT NULL DEFAULT 0,
    min_angle REAL,
    max_angle REAL,
    original_planar INTEGER,
    original_angle_deg REAL,
    job_status TEXT,
    job_duration_sec REAL,
    PRIMARY KEY (h, config, mol)
);
CREATE INDEX IF NOT EXISTS idx_mol_name ON molecules(mol);
CREATE INDEX IF NOT EXISTS idx_mol_h_config_plans ON molecules(h, config, n_plans DESC);

CREATE TABLE IF NOT EXISTS solutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    h TEXT NOT NULL,
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    sol_idx INTEGER NOT NULL,
    sizes TEXT NOT NULL,
    verdict TEXT NOT NULL,
    planar INTEGER,
    angle_deg REAL,
    rmsd REAL,
    height REAL,
    n_attempts INTEGER,
    deterministic INTEGER,
    sol_dir TEXT NOT NULL,
    decision_path TEXT,
    mmff_angle_deg REAL
);
CREATE INDEX IF NOT EXISTS idx_sol_mol ON solutions(h, config, mol);
CREATE INDEX IF NOT EXISTS idx_sol_verdict ON solutions(h, config, mol, verdict);
CREATE INDEX IF NOT EXISTS idx_sol_angle ON solutions(h, config, mol, angle_deg);
CREATE INDEX IF NOT EXISTS idx_sol_decision ON solutions(decision_path);

CREATE TABLE IF NOT EXISTS xyz_files (
    rel_path   TEXT PRIMARY KEY,
    content_gz BLOB NOT NULL,
    size_raw   INTEGER NOT NULL
);
"""


def init_worker_db(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# ---------------- Planarite (copie de v2 pour eviter import croise) -----------

def _read_xyz_coords(text: str):
    coords = []
    syms = []
    lines = text.splitlines()
    if len(lines) < 3:
        return syms, coords
    try:
        n = int(lines[0].strip())
    except ValueError:
        return syms, coords
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                syms.append(parts[0])
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                pass
    return syms, coords


def _compute_planarity(coords, syms=None):
    import numpy as np
    if syms is not None:
        coords = [c for c, s in zip(coords, syms) if s != "H"]
    if len(coords) < 3:
        return None
    pts = np.array(coords, dtype=float)
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    try:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    normal = vh[2]
    dists = centered @ normal
    height = float(np.max(np.abs(dists)))
    rmsd = float(np.sqrt(np.mean(dists ** 2)))
    norms = np.linalg.norm(centered, axis=1)
    import numpy as np2
    norms = np2.where(norms > 1e-9, norms, 1e-9)
    sin_a = np2.clip(np2.abs(dists) / norms, 0, 1)
    angles_deg = np2.degrees(np2.arcsin(sin_a))
    return {
        "max_angle_deg": float(np2.max(angles_deg)),
        "rmsd_plane": rmsd,
        "height": height,
    }


def _is_planar(metrics, threshold_deg: float = 10.0) -> bool:
    return metrics["max_angle_deg"] <= threshold_deg


def test_planarity_from_text(xyz_text: str) -> Optional[dict]:
    syms, coords = _read_xyz_coords(xyz_text)
    if len(coords) < 3:
        return None
    m = _compute_planarity(coords, syms)
    if m is None:
        return None
    return {
        "planar": _is_planar(m, 10.0),
        "angle_deg": m["max_angle_deg"],
        "rmsd": m["rmsd_plane"],
        "height": m["height"],
    }


def parse_sol_dirname(name: str):
    """sol_42_5_7_6_6_5_6 -> (42, '5_7_6_6_5_6')."""
    if not name.startswith("sol_"):
        return None, None
    parts = name.split("_", 2)
    if len(parts) < 3:
        return None, None
    try:
        idx = int(parts[1])
    except ValueError:
        return None, None
    return idx, parts[2]


def _store_xyz(conn: sqlite3.Connection, rel_path: str, xyz_text: str) -> None:
    raw = xyz_text.encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    conn.execute(
        "INSERT OR REPLACE INTO xyz_files (rel_path, content_gz, size_raw) "
        "VALUES (?, ?, ?)",
        (rel_path, gz, len(raw))
    )


# ---------------- Ingestion v3 ----------------

def ingest_mol_dir_v3(conn: sqlite3.Connection,
                       local_mol_dir: Path,
                       h_name: str,
                       config: str,
                       mol: str,
                       sol_dir_prefix: str,
                       job_status: str = "ok",
                       job_duration_sec: Optional[float] = None,
                       n_solutions_csp: Optional[int] = None) -> dict:
    """Ingere le scratch d'UN mol post-pipeline v3.

    Structure attendue dans local_mol_dir :
        solutions/
            sol_<i>_<sizes>/
                source.xyz                  (toujours)
                mmff_validation/
                    mmff_opt.xyz            (si MMFF a tourne)
                    mmff_meta.json          (decision, angle)
                md_validation/              (uniquement si MMFF gray/failed)
                    md_final_opt.xyz
                    md_meta.json

    Le verdict / decision_path / mmff_angle sont determines en lisant
    mmff_meta.json (priorite) puis md_meta.json (si gray).
    """
    local_mol_dir = Path(local_mol_dir)

    n_md_completed = 0
    n_geom_infeasible = 0
    n_xtb_failed = 0
    n_plans = 0
    n_non_plans = 0
    n_mmff_sure_plan = 0
    n_mmff_sure_non_plan = 0
    n_mmff_gray = 0
    min_angle = None
    max_angle = None

    sol_root = local_mol_dir / "solutions"
    if sol_root.is_dir():
        for sd in sorted(sol_root.iterdir()):
            if not sd.is_dir():
                continue
            idx, sizes = parse_sol_dirname(sd.name)
            if idx is None:
                continue
            sol_dir_rel = f"{sol_dir_prefix}/{sd.name}"

            # Lecture du meta MMFF (s'il existe)
            mmff_meta_path = sd / "mmff_validation" / "mmff_meta.json"
            mmff_meta = None
            if mmff_meta_path.is_file():
                try:
                    mmff_meta = json.loads(mmff_meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    mmff_meta = None

            decision = (mmff_meta or {}).get("decision_path", "unknown")
            mmff_angle = (mmff_meta or {}).get("mmff_angle_deg")

            # --- 1. Cas geom_infeasible ---
            if decision == "geom_infeasible" or not (sd / "source.xyz").is_file():
                n_geom_infeasible += 1
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir, "
                    "decision_path, mmff_angle_deg) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, "geom_infeasible",
                     None, None, None, None, None, None, sol_dir_rel,
                     decision, mmff_angle)
                )
                continue

            # Stocker source.xyz (utile pour audit & re-validation)
            try:
                _store_xyz(conn, f"{sol_dir_rel}/source.xyz",
                           (sd / "source.xyz").read_text(encoding="utf-8"))
            except OSError:
                pass

            # Stocker mmff_opt.xyz si dispo
            mmff_xyz_path = sd / "mmff_validation" / "mmff_opt.xyz"
            if mmff_xyz_path.is_file():
                try:
                    _store_xyz(conn,
                               f"{sol_dir_rel}/mmff_validation/mmff_opt.xyz",
                               mmff_xyz_path.read_text(encoding="utf-8"))
                except OSError:
                    pass

            # --- 2. Cas mmff_sure_plan (skip xTB) ---
            if decision == "mmff_sure_plan":
                n_mmff_sure_plan += 1
                n_plans += 1
                n_md_completed += 1
                angle = mmff_angle
                if angle is not None:
                    if min_angle is None or angle < min_angle: min_angle = angle
                    if max_angle is None or angle > max_angle: max_angle = angle
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir, "
                    "decision_path, mmff_angle_deg) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, "plan",
                     1, angle,
                     (mmff_meta or {}).get("mmff_rmsd"),
                     (mmff_meta or {}).get("mmff_height"),
                     None, None, sol_dir_rel,
                     decision, mmff_angle)
                )
                continue

            # --- 3. Cas mmff_sure_non_plan (skip xTB) ---
            if decision == "mmff_sure_non_plan":
                n_mmff_sure_non_plan += 1
                n_non_plans += 1
                n_md_completed += 1
                angle = mmff_angle
                if angle is not None:
                    if min_angle is None or angle < min_angle: min_angle = angle
                    if max_angle is None or angle > max_angle: max_angle = angle
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir, "
                    "decision_path, mmff_angle_deg) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, "non_plan",
                     0, angle,
                     (mmff_meta or {}).get("mmff_rmsd"),
                     (mmff_meta or {}).get("mmff_height"),
                     None, None, sol_dir_rel,
                     decision, mmff_angle)
                )
                continue

            # --- 4. Cas gray / mmff_failed -> xTB a tourne (ou pas) ---
            n_mmff_gray += 1
            final_xyz = sd / "md_validation" / "md_final_opt.xyz"
            if not final_xyz.is_file():
                n_xtb_failed += 1
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir, "
                    "decision_path, mmff_angle_deg) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, "xtb_failed",
                     None, None, None, None, None, None, sol_dir_rel,
                     f"{decision}_xtb_failed", mmff_angle)
                )
                continue

            try:
                final_text = final_xyz.read_text(encoding="utf-8")
            except OSError:
                n_xtb_failed += 1
                continue

            plan = test_planarity_from_text(final_text)
            if plan is None:
                n_xtb_failed += 1
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir, "
                    "decision_path, mmff_angle_deg) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, "xtb_failed",
                     None, None, None, None, None, None, sol_dir_rel,
                     f"{decision}_xtb_failed", mmff_angle)
                )
                continue

            n_md_completed += 1
            planar = 1 if plan["planar"] else 0
            angle = plan["angle_deg"]
            verdict = "plan" if planar else "non_plan"
            full_decision = f"{decision}_xtb_{verdict}"
            if planar: n_plans += 1
            else: n_non_plans += 1
            if min_angle is None or angle < min_angle: min_angle = angle
            if max_angle is None or angle > max_angle: max_angle = angle

            n_attempts = None
            deterministic = None
            md_meta_path = sd / "md_validation" / "md_meta.json"
            if md_meta_path.is_file():
                try:
                    md_meta = json.loads(md_meta_path.read_text(encoding="utf-8"))
                    n_attempts = md_meta.get("n_attempts")
                    det = md_meta.get("deterministic")
                    if det is not None:
                        deterministic = 1 if det else 0
                except (OSError, json.JSONDecodeError):
                    pass

            conn.execute(
                "INSERT INTO solutions "
                "(h, config, mol, sol_idx, sizes, verdict, "
                "planar, angle_deg, rmsd, height, "
                "n_attempts, deterministic, sol_dir, "
                "decision_path, mmff_angle_deg) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (h_name, config, mol, idx, sizes, verdict,
                 planar, angle, plan["rmsd"], plan["height"],
                 n_attempts, deterministic, sol_dir_rel,
                 full_decision, mmff_angle)
            )

            _store_xyz(conn,
                       f"{sol_dir_rel}/md_validation/md_final_opt.xyz",
                       final_text)

    # Insertion molecules
    conn.execute(
        "INSERT OR REPLACE INTO molecules "
        "(h, config, mol, n_solutions_csp, n_md_completed, "
        "n_geom_infeasible, n_xtb_failed, "
        "n_plans, n_non_plans, "
        "n_mmff_sure_plan, n_mmff_sure_non_plan, n_mmff_gray, "
        "min_angle, max_angle, "
        "original_planar, original_angle_deg, "
        "job_status, job_duration_sec) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (h_name, config, mol, n_solutions_csp, n_md_completed,
         n_geom_infeasible, n_xtb_failed,
         n_plans, n_non_plans,
         n_mmff_sure_plan, n_mmff_sure_non_plan, n_mmff_gray,
         min_angle, max_angle,
         None, None,
         job_status, job_duration_sec)
    )

    # Compteur cumulatif configs (idem v2)
    conn.execute("""
        INSERT OR REPLACE INTO configs (h, name, n_molecules, n_solutions,
                                          n_geom_infeasible, n_plans, n_non_plans)
        VALUES (?, ?,
                COALESCE((SELECT n_molecules FROM configs WHERE h=? AND name=?), 0) + 1,
                COALESCE((SELECT n_solutions FROM configs WHERE h=? AND name=?), 0) + ?,
                COALESCE((SELECT n_geom_infeasible FROM configs WHERE h=? AND name=?), 0) + ?,
                COALESCE((SELECT n_plans FROM configs WHERE h=? AND name=?), 0) + ?,
                COALESCE((SELECT n_non_plans FROM configs WHERE h=? AND name=?), 0) + ?)
    """, (h_name, config,
          h_name, config,
          h_name, config, n_md_completed,
          h_name, config, n_geom_infeasible,
          h_name, config, n_plans,
          h_name, config, n_non_plans))

    conn.commit()

    return {
        "n_md_completed": n_md_completed,
        "n_geom_infeasible": n_geom_infeasible,
        "n_xtb_failed": n_xtb_failed,
        "n_plans": n_plans,
        "n_non_plans": n_non_plans,
        "n_mmff_sure_plan": n_mmff_sure_plan,
        "n_mmff_sure_non_plan": n_mmff_sure_non_plan,
        "n_mmff_gray": n_mmff_gray,
    }
