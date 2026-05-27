"""
Construit la base SQLite multi-datasets (h3 a h9) pour le viewer CSP.

Multiprocessing : un worker par molecule (h, config, mol). Chaque worker
calcule la planarite de tous ses sol_dirs et renvoie les rangees a inserer.
Le main process agrege et ecrit dans SQLite (un seul writer pour eviter
les locks).

Usage typique :

    # Build complet (cree ou recrie la DB)
    python build_db.py --h h3,h4,h5,h6,h7,h8,h9

    # Build d'une portion seulement (cree la DB si absente, sinon ajoute
    # cette portion sans toucher au reste)
    python build_db.py --h h9 --append

    # Auto-detection : scanne cluster_results/ et csp_solver/experiments/output/
    python build_db.py --auto-detect

Options :
    --h h3,h4,...    : liste de datasets a traiter (separes par virgule).
    --root-pattern   : motif pour localiser les donnees brutes (defaut :
                       essaie "cluster_results/{h}" puis "csp_solver/experiments/output/{h}").
    --db             : chemin de la base sqlite (defaut db_all.db).
    --append         : ne pas effacer la DB. Re-insere uniquement les datasets
                       cibles (UPSERT par cle).
    --limit N        : ne traite que N (h, config, mol) au total (debug).
    --processes K    : nb de workers (defaut CPU - 1).
    --auto-detect    : scanne le project root pour trouver tous les hN/.
"""

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
_GEN_ROOT = _PROJECT_ROOT / "non_benzenoid_generator"

_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_GEN_ROOT / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar

THRESHOLD_DEG = 10.0

# Emplacements connus ou trouver les donnees brutes pour un dataset hN.
# On essaie ces patterns dans l'ordre, le premier qui matche gagne.
DEFAULT_ROOT_PATTERNS = [
    "cluster_results/{h}",                  # post-cluster (telechargement local)
    "csp_solver/experiments/output/{h}",    # batch local
    "_{h}_run/output/{h}",                  # arborescence cluster (cas SSH direct)
]


# =====================================================================
#  Lecture XYZ + planarite
# =====================================================================

def read_xyz_coords(xyz_path):
    coords = []
    try:
        with open(xyz_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return coords
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


def test_planarity(xyz_path):
    coords = read_xyz_coords(str(xyz_path))
    if len(coords) < 3:
        return None
    metrics = compute_planarity(coords)
    return {
        "planar": is_planar(metrics, THRESHOLD_DEG),
        "angle_deg": float(metrics["max_angle_deg"]),
        "rmsd": float(metrics["rmsd_plane"]),
        "height": float(metrics["height"]),
    }


def parse_sol_dirname(name):
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


# =====================================================================
#  Worker
# =====================================================================

def process_molecule(args):
    """Worker : traite une (h, config, mol). Retourne (mol_row, [sol_rows])."""
    project_root, root_abs, h_name, config, mol = args
    project_root = Path(project_root)
    root_abs = Path(root_abs)
    mol_dir = root_abs / config / mol

    js = mol_dir / "job_status.json"
    job_status = None
    job_duration = None
    n_solutions_csp = None
    if js.is_file():
        try:
            jj = json.loads(js.read_text(encoding="utf-8"))
            job_status = jj.get("status")
            job_duration = jj.get("duration_sec")
            n_solutions_csp = jj.get("n_solutions")
        except (OSError, json.JSONDecodeError):
            pass

    orig_opt = mol_dir / f"{mol}_original_opt.xyz"
    original_planar = None
    original_angle = None
    if orig_opt.is_file():
        plan = test_planarity(orig_opt)
        if plan is not None:
            original_planar = 1 if plan["planar"] else 0
            original_angle = plan["angle_deg"]

    sol_root = mol_dir / "solutions"
    sol_rows = []
    n_md_completed = 0
    n_geom_infeasible = 0
    n_xtb_failed = 0
    n_plans = 0
    n_non_plans = 0
    min_angle = None
    max_angle = None

    if sol_root.is_dir():
        for sol_dir in sorted(sol_root.iterdir()):
            if not sol_dir.is_dir():
                continue
            idx, sizes = parse_sol_dirname(sol_dir.name)
            if idx is None:
                continue
            source_xyz = sol_dir / "source.xyz"
            final_xyz = sol_dir / "md_validation" / "md_final_opt.xyz"

            try:
                sol_dir_rel = str(sol_dir.relative_to(project_root)).replace("\\", "/")
            except ValueError:
                sol_dir_rel = str(sol_dir).replace("\\", "/")

            if not final_xyz.is_file():
                # Pas de geometrie validee : soit reconstruction impossible,
                # soit xtb a echoue. On insere quand meme une ligne pour
                # rendre le sol visible dans le viewer.
                if not source_xyz.is_file():
                    n_geom_infeasible += 1
                    sol_rows.append((
                        h_name, config, mol, idx, sizes,
                        "geom_infeasible",
                        None, None, None, None,    # planar, angle, rmsd, height
                        None, None,                 # n_attempts, deterministic
                        sol_dir_rel,
                    ))
                else:
                    n_xtb_failed += 1
                    sol_rows.append((
                        h_name, config, mol, idx, sizes,
                        "xtb_failed",
                        None, None, None, None,
                        None, None,
                        sol_dir_rel,
                    ))
                continue

            plan = test_planarity(final_xyz)
            if plan is None:
                n_xtb_failed += 1
                sol_rows.append((
                    h_name, config, mol, idx, sizes,
                    "xtb_failed",
                    None, None, None, None,
                    None, None,
                    sol_dir_rel,
                ))
                continue

            n_md_completed += 1
            planar = 1 if plan["planar"] else 0
            angle = plan["angle_deg"]
            verdict = "plan" if planar else "non_plan"
            if planar:
                n_plans += 1
            else:
                n_non_plans += 1
            if min_angle is None or angle < min_angle:
                min_angle = angle
            if max_angle is None or angle > max_angle:
                max_angle = angle

            n_attempts = None
            deterministic = None
            meta_path = sol_dir / "md_validation" / "md_meta.json"
            if meta_path.is_file():
                try:
                    md_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    n_attempts = md_meta.get("n_attempts")
                    det = md_meta.get("deterministic")
                    if det is not None:
                        deterministic = 1 if det else 0
                except (OSError, json.JSONDecodeError):
                    pass

            sol_rows.append((
                h_name, config, mol, idx, sizes,
                verdict,
                planar, angle, plan["rmsd"], plan["height"],
                n_attempts, deterministic, sol_dir_rel,
            ))

    mol_row = (
        h_name, config, mol, n_solutions_csp, n_md_completed,
        n_geom_infeasible, n_xtb_failed,
        n_plans, n_non_plans,
        min_angle, max_angle,
        original_planar, original_angle,
        job_status, job_duration,
    )
    return mol_row, sol_rows


# =====================================================================
#  Discovery
# =====================================================================

def resolve_root_for_h(project_root, h_name, custom_pattern=None):
    """Trouve le dossier racine pour un dataset donne."""
    patterns = [custom_pattern] if custom_pattern else DEFAULT_ROOT_PATTERNS
    for pat in patterns:
        if pat is None:
            continue
        candidate = Path(pat.format(h=h_name, H=h_name))
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.is_dir():
            return candidate
    return None


def discover_jobs_for_h(project_root, root_abs, h_name, limit=None):
    jobs = []
    if not root_abs.is_dir():
        return jobs
    for cfg_dir in sorted(root_abs.iterdir()):
        if not cfg_dir.is_dir():
            continue
        for mol_dir in sorted(cfg_dir.iterdir()):
            if not mol_dir.is_dir():
                continue
            jobs.append((str(project_root), str(root_abs), h_name,
                         cfg_dir.name, mol_dir.name))
            if limit and len(jobs) >= limit:
                return jobs
    return jobs


def auto_detect_datasets(project_root):
    """Liste les hN disponibles sur disque (max h3..h12)."""
    found = []
    for n in range(3, 13):
        h = f"h{n}"
        if resolve_root_for_h(project_root, h) is not None:
            found.append(h)
    return found


# =====================================================================
#  DB init + migration
# =====================================================================

def init_db(db_path, schema_path, append=False):
    """Cree la DB si absente, ou applique le schema (CREATE IF NOT EXISTS)
    sur une DB existante. Si append=False et la DB existe, on l'ecrase."""
    if not append and db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def wipe_h(conn, h_name):
    """En mode append : on efface uniquement les lignes du dataset cible
    pour ne pas garder d'entrees obsoletes."""
    conn.execute("DELETE FROM solutions WHERE h = ?", (h_name,))
    conn.execute("DELETE FROM molecules WHERE h = ?", (h_name,))
    conn.execute("DELETE FROM configs WHERE h = ?", (h_name,))
    conn.commit()


# =====================================================================
#  Main
# =====================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", default=None,
                    help="datasets a traiter, separes par virgule (ex. h3,h4,h7). "
                         "Implicite si --auto-detect.")
    ap.add_argument("--auto-detect", action="store_true",
                    help="Detecte tous les hN/ disponibles sur disque.")
    ap.add_argument("--root-pattern", default=None,
                    help="Motif d'emplacement des donnees brutes "
                         "(ex. 'cluster_results/{h}'). Par defaut, essaie "
                         "plusieurs emplacements connus.")
    ap.add_argument("--db", default=str(_HERE / "db_all.db"),
                    help="chemin de la DB sqlite a creer/mettre a jour")
    ap.add_argument("--append", action="store_true",
                    help="Ne pas ecraser la DB existante : les datasets "
                         "cibles sont re-inseres, le reste est preserve.")
    ap.add_argument("--limit", type=int, default=None,
                    help="ne traite que N (config, mol) par dataset (debug)")
    ap.add_argument("--processes", type=int,
                    default=max(1, (os.cpu_count() or 4) - 1))
    args = ap.parse_args()

    project_root = _PROJECT_ROOT
    db_path = Path(args.db)
    schema_path = _HERE / "schema.sql"

    if args.auto_detect:
        datasets = auto_detect_datasets(project_root)
        if not datasets:
            print("ERREUR : aucun dataset hN detecte sur disque.")
            return
        print(f"Auto-detect : {datasets}")
    elif args.h:
        datasets = [s.strip() for s in args.h.split(",") if s.strip()]
    else:
        print("ERREUR : precise --h ou --auto-detect.")
        return

    # Resolution des roots
    resolved = []
    for h in datasets:
        root = resolve_root_for_h(project_root, h, args.root_pattern)
        if root is None:
            print(f"  [SKIP] {h} : aucun dossier de donnees trouve.")
            continue
        resolved.append((h, root))
    if not resolved:
        print("ERREUR : aucun dataset utilisable.")
        return

    print(f"Project root: {project_root}")
    print(f"DB          : {db_path}  (append={args.append})")
    print(f"Workers     : {args.processes}")
    print(f"Datasets    :")
    for h, root in resolved:
        print(f"  {h}  <- {root}")

    conn = init_db(db_path, schema_path, append=args.append)
    cur = conn.cursor()

    if args.append:
        for h, _ in resolved:
            wipe_h(conn, h)

    # Discovery
    print("\nDiscovery des jobs ...")
    t0 = time.time()
    all_jobs = []
    for h, root in resolved:
        jobs = discover_jobs_for_h(project_root, root, h, args.limit)
        all_jobs.extend(jobs)
        print(f"  {h:4s} : {len(jobs):6d} (config, mol)")
    print(f"  TOTAL : {len(all_jobs)} jobs ({time.time()-t0:.1f}s)")

    if not all_jobs:
        print("Rien a faire.")
        conn.close()
        return

    n_done = 0
    n_sols_total = 0
    t0 = time.time()
    print("\nCalcul de planarite + insertion ...")
    with mp.Pool(args.processes) as pool:
        for mol_row, sol_rows in pool.imap_unordered(
                process_molecule, all_jobs, chunksize=4):
            cur.execute(
                "INSERT INTO molecules "
                "(h, config, mol, n_solutions_csp, n_md_completed, "
                " n_geom_infeasible, n_xtb_failed, "
                " n_plans, n_non_plans, min_angle, max_angle, "
                " original_planar, original_angle_deg, "
                " job_status, job_duration_sec) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                mol_row,
            )
            if sol_rows:
                cur.executemany(
                    "INSERT INTO solutions "
                    "(h, config, mol, sol_idx, sizes, verdict, "
                    " planar, angle_deg, rmsd, height, n_attempts, "
                    " deterministic, sol_dir) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    sol_rows,
                )
            n_sols_total += len(sol_rows)
            n_done += 1
            if n_done % 200 == 0 or n_done == len(all_jobs):
                conn.commit()
                elapsed = time.time() - t0
                rate = n_done / elapsed if elapsed > 0 else 0
                eta = (len(all_jobs) - n_done) / rate if rate > 0 else 0
                print(f"  [{n_done}/{len(all_jobs)}] sols={n_sols_total}  "
                      f"({rate:.1f} mol/s, eta {eta/60:.1f} min)")
    conn.commit()

    # Stats agregees par (h, config) -- on ecrase pour les datasets traites
    print("\nCalcul des stats par (h, config) ...")
    for h, _ in resolved:
        conn.execute("DELETE FROM configs WHERE h = ?", (h,))
        conn.execute("""
            INSERT INTO configs
                (h, name, n_molecules, n_solutions, n_geom_infeasible,
                 n_plans, n_non_plans)
            SELECT
                h,
                config,
                COUNT(*),
                COALESCE(SUM(n_md_completed), 0),
                COALESCE(SUM(n_geom_infeasible), 0),
                COALESCE(SUM(n_plans), 0),
                COALESCE(SUM(n_non_plans), 0)
            FROM molecules
            WHERE h = ?
            GROUP BY h, config
        """, (h,))
    conn.commit()

    print("\nDatasets dans la DB :")
    for row in cur.execute(
            "SELECT h, COUNT(*) AS n_cfg, "
            "       SUM(n_molecules) AS n_mols, "
            "       SUM(n_solutions) AS n_sols, "
            "       SUM(n_geom_infeasible) AS n_geom, "
            "       SUM(n_plans) AS n_plans "
            "FROM configs GROUP BY h ORDER BY h"):
        h, n_cfg, n_mols, n_sols, n_geom, n_plans = row
        pct = (100 * n_plans / n_sols) if n_sols else 0
        print(f"  {h:4s}  {n_cfg} configs  mols={n_mols:6d}  "
              f"valides={n_sols:7d}  infaisables={n_geom:7d}  "
              f"plans={n_plans:7d} ({pct:.1f}%)")

    conn.close()
    print(f"\nTermine en {(time.time()-t0)/60:.1f} min.")


if __name__ == "__main__":
    main()
