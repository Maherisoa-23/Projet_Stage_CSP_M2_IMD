"""
Helpers pour l'ecriture des resultats experiments_v2 DIRECTEMENT en sqlite,
sans passer par des fichiers xyz/json sur le NFS partage.

Schema utilise = identique a celui de csp_solver/experiments/csp_viewer/schema.sql
(tables configs, molecules, solutions, xyz_files) pour que le viewer existant
puisse lire la nouvelle db_v3.db sans modification.

Workflow par job (dans run_one_job_v2) :
  1. CSP + reconstruction + xTB MD se font dans scratch local (xyz sur tmpfs)
  2. A la fin, on appelle ingest_mol_dir(scratch_mol_dir, h, config, mol, ...)
     qui lit les xyz scratch + calcule planarite + insere TOUT dans un sqlite
     local au job (worker_dbs/<job_id>.db)
  3. Le scratch est detruit
  4. La mini DB (typ. < 1 MB) est conservee sur NFS
  5. finalize_v2 merge toutes les mini DBs dans db_v3.db
"""

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Optional


# ---------------- Schema (copie de csp_viewer/schema.sql) ----------------

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
    sol_dir TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sol_mol ON solutions(h, config, mol);
CREATE INDEX IF NOT EXISTS idx_sol_verdict ON solutions(h, config, mol, verdict);
CREATE INDEX IF NOT EXISTS idx_sol_angle ON solutions(h, config, mol, angle_deg);

CREATE TABLE IF NOT EXISTS xyz_files (
    rel_path   TEXT PRIMARY KEY,
    content_gz BLOB NOT NULL,
    size_raw   INTEGER NOT NULL
);
"""


def init_worker_db(path: Path) -> sqlite3.Connection:
    """Cree (ou ouvre) un sqlite contenant le schema viewer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# ---------------- Planarite (copie locale, evite import croise) ----------------

def _read_xyz_coords(text: str):
    coords = []
    lines = text.splitlines()
    if len(lines) < 3:
        return coords
    try:
        n = int(lines[0].strip())
    except ValueError:
        return coords
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                pass
    return coords


def _compute_planarity(coords):
    """Reproduit non_benzenoid_generator/utils/planarity.py::compute_planarity.

    Retourne {max_angle_deg, rmsd_plane, height}. Approche : ACP, le plan
    moyen est l'hyperplan defini par les 2 premieres composantes, l'angle
    max est l'angle entre la normale du plan d'un cycle et la normale
    du plan moyen ; ici on simplifie en reproduisant la metrique
    'max angle from mean plane' utilisee par build_db.
    """
    import numpy as np
    if len(coords) < 3:
        return None
    pts = np.array(coords, dtype=float)
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    try:
        _, sv, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    normal = vh[2]
    # Distance signee de chaque point au plan moyen
    dists = centered @ normal
    height = float(np.max(np.abs(dists)))
    # RMSD au plan moyen
    rmsd = float(np.sqrt(np.mean(dists ** 2)))
    # max angle : angle entre la normale et l'axe principal d'inertie
    # (i.e. acos(sv[2] / sqrt(sv[0]^2 + sv[1]^2 + sv[2]^2)))
    # Approche pragmatique : angle (deg) entre chaque liaison atom-centroide
    # et le plan moyen. Compatible avec test_planarity de build_db.
    norms = np.linalg.norm(centered, axis=1)
    # eviter division par 0
    norms = np.where(norms > 1e-9, norms, 1e-9)
    sin_a = np.abs(dists) / norms
    sin_a = np.clip(sin_a, 0, 1)
    angles_deg = np.degrees(np.arcsin(sin_a))
    return {
        "max_angle_deg": float(np.max(angles_deg)),
        "rmsd_plane": rmsd,
        "height": height,
    }


def _is_planar(metrics, threshold_deg: float = 10.0) -> bool:
    return metrics["max_angle_deg"] <= threshold_deg


def test_planarity_from_text(xyz_text: str) -> Optional[dict]:
    coords = _read_xyz_coords(xyz_text)
    if len(coords) < 3:
        return None
    m = _compute_planarity(coords)
    if m is None:
        return None
    return {
        "planar": _is_planar(m, 10.0),
        "angle_deg": m["max_angle_deg"],
        "rmsd": m["rmsd_plane"],
        "height": m["height"],
    }


# ---------------- Parsing sol_dir ----------------

def parse_sol_dirname(name: str):
    """sol_42_5_7_6_6_5_6 -> (42, '5_7_6_6_5_6'). Retourne (None,None) si invalide."""
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


# ---------------- Ingestion ----------------

def _store_xyz(conn: sqlite3.Connection, rel_path: str, xyz_text: str) -> None:
    """Stocke un xyz gzippe dans xyz_files."""
    raw = xyz_text.encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    conn.execute(
        "INSERT OR REPLACE INTO xyz_files (rel_path, content_gz, size_raw) "
        "VALUES (?, ?, ?)",
        (rel_path, gz, len(raw))
    )


def ingest_mol_dir(conn: sqlite3.Connection,
                    local_mol_dir: Path,
                    h_name: str,
                    config: str,
                    mol: str,
                    sol_dir_prefix: str,
                    job_status: str = "ok",
                    job_duration_sec: Optional[float] = None,
                    n_solutions_csp: Optional[int] = None) -> dict:
    """Ingere TOUT le contenu d'un local_mol_dir (apres run xTB MD) dans la
    DB ouverte sur conn. Calcule la planarite a la volee. Stocke les xyz
    en BLOB gzip. Renvoie un dict de stats (n_md_completed, n_plans, ...).

    Args:
        conn               : connexion sqlite (init_worker_db) avec schema
        local_mol_dir      : dossier scratch de la mol (contient sol_*/)
        h_name, config, mol: cle composite
        sol_dir_prefix     : chemin LOGIQUE des sols (sera concatene avec
                              le nom de sol_dir pour produire les `sol_dir`
                              en DB ; doit matcher le format que le viewer
                              attend, ex.:
                              csp_solver/experiments/_ev2_run/output/h7/sym1_pb2/<mol>/solutions
                              ).
        job_status         : 'ok' | 'failed' | 'timeout'
        job_duration_sec   : duree du job complet
        n_solutions_csp    : nb de solutions CSP trouvees (avant xTB)
    """
    local_mol_dir = Path(local_mol_dir)

    n_md_completed = 0
    n_geom_infeasible = 0
    n_xtb_failed = 0
    n_plans = 0
    n_non_plans = 0
    min_angle = None
    max_angle = None

    # 1. Original xyz du benzenoide (tout-6) si present
    orig_opt = local_mol_dir / f"{mol}_original_opt.xyz"
    original_planar = None
    original_angle = None
    if orig_opt.is_file():
        try:
            text = orig_opt.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text:
            plan = test_planarity_from_text(text)
            if plan is not None:
                original_planar = 1 if plan["planar"] else 0
                original_angle = plan["angle_deg"]
            # On stocke aussi le xyz du mol original (cle = chemin logique
            # cohérent avec le mol_dir prefix sans le sous-dossier solutions)
            mol_dir_rel = sol_dir_prefix.rsplit("/solutions", 1)[0]
            rel = f"{mol_dir_rel}/{mol}_original_opt.xyz"
            _store_xyz(conn, rel, text)

    # 2. Solutions
    sol_root = local_mol_dir / "solutions"
    if sol_root.is_dir():
        for sd in sorted(sol_root.iterdir()):
            if not sd.is_dir():
                continue
            idx, sizes = parse_sol_dirname(sd.name)
            if idx is None:
                continue

            sol_dir_rel = f"{sol_dir_prefix}/{sd.name}"
            source_xyz = sd / "source.xyz"
            final_xyz = sd / "md_validation" / "md_final_opt.xyz"

            if not final_xyz.is_file():
                # geom_infeasible ou xtb_failed
                if not source_xyz.is_file():
                    verdict = "geom_infeasible"
                    n_geom_infeasible += 1
                else:
                    verdict = "xtb_failed"
                    n_xtb_failed += 1
                    # On stocke quand meme source.xyz pour avoir une trace
                    try:
                        _store_xyz(conn, f"{sol_dir_rel}/source.xyz",
                                   source_xyz.read_text(encoding="utf-8"))
                    except OSError:
                        pass
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, verdict,
                     None, None, None, None, None, None, sol_dir_rel)
                )
                continue

            # Lire le xyz final et calculer la planarite
            try:
                final_text = final_xyz.read_text(encoding="utf-8")
            except OSError:
                final_text = ""

            plan = test_planarity_from_text(final_text) if final_text else None
            if plan is None:
                verdict = "xtb_failed"
                n_xtb_failed += 1
                conn.execute(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    "planar, angle_deg, rmsd, height, "
                    "n_attempts, deterministic, sol_dir) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (h_name, config, mol, idx, sizes, verdict,
                     None, None, None, None, None, None, sol_dir_rel)
                )
                continue

            n_md_completed += 1
            planar = 1 if plan["planar"] else 0
            angle = plan["angle_deg"]
            verdict = "plan" if planar else "non_plan"
            if planar: n_plans += 1
            else: n_non_plans += 1
            if min_angle is None or angle < min_angle: min_angle = angle
            if max_angle is None or angle > max_angle: max_angle = angle

            n_attempts = None
            deterministic = None
            meta_path = sd / "md_validation" / "md_meta.json"
            if meta_path.is_file():
                try:
                    md_meta = json.loads(meta_path.read_text(encoding="utf-8"))
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
                "n_attempts, deterministic, sol_dir) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (h_name, config, mol, idx, sizes, verdict,
                 planar, angle, plan["rmsd"], plan["height"],
                 n_attempts, deterministic, sol_dir_rel)
            )

            # Stocke les xyz : final (md_validation) + source si dispo
            _store_xyz(conn, f"{sol_dir_rel}/md_validation/md_final_opt.xyz",
                       final_text)
            if source_xyz.is_file():
                try:
                    _store_xyz(conn, f"{sol_dir_rel}/source.xyz",
                               source_xyz.read_text(encoding="utf-8"))
                except OSError:
                    pass

    # 3. Insertion molecules
    conn.execute(
        "INSERT OR REPLACE INTO molecules "
        "(h, config, mol, n_solutions_csp, n_md_completed, "
        "n_geom_infeasible, n_xtb_failed, "
        "n_plans, n_non_plans, "
        "min_angle, max_angle, "
        "original_planar, original_angle_deg, "
        "job_status, job_duration_sec) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (h_name, config, mol, n_solutions_csp, n_md_completed,
         n_geom_infeasible, n_xtb_failed,
         n_plans, n_non_plans,
         min_angle, max_angle,
         original_planar, original_angle,
         job_status, job_duration_sec)
    )

    # 4. Insertion configs (compteur cumulatif simple : 1 mol ajoutee, somme des stats)
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
    }
