"""Execute UN seul sample de validation : xTB sur source.xyz extrait de db_v4.

Workflow :
  1. Connexion read-only a db_v4
  2. Recupere source.xyz BLOB par rel_path (cle xyz_files.rel_path)
  3. Ecrit en scratch local
  4. Lance md_then_optimize (xTB MD + opt) -> md_final_opt.xyz
  5. Calcule planarite (PCA sur atomes lourds)
  6. Ecrit job_status.json sur NFS avec :
       - mmff_angle_deg, xtb_angle_deg, xtb_planar
       - duree, host, etc.

Usage (typiquement appele par validation/worker.py) :
    python -m csp_solver.experiments_v3.validation.run_one \\
        --job-json '{"h":"h7","config":"pb1_curv1",...}' \\
        --db /home/.../db_v4.db \\
        --output-root /home/.../validation_run/output \\
        --scratch-root /tmp \\
        [--timeout 600]
"""

import argparse
import gzip
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CSP_ROOT = _HERE.parent.parent
_PROJECT_ROOT = _CSP_ROOT.parent
sys.path.insert(0, str(_CSP_ROOT / "experiments" / "cluster"))
sys.path.insert(0, str(_PROJECT_ROOT))
from atomic_io import write_atomic_json  # noqa: E402

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

SCRATCH_PREFIX = "coala_val_"


def fetch_source_xyz(db_path: str, key: str) -> str | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT content_gz FROM xyz_files WHERE rel_path=?", (key,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return gzip.decompress(row[0]).decode("utf-8")


def run_xtb_md_opt(source_xyz_path: Path, md_dir: Path):
    """Lance md_then_optimize sur source.xyz. Return (success, final_xyz)."""
    _gen_root = _PROJECT_ROOT / "non_benzenoid_generator"
    sys.path.insert(0, str(_gen_root))
    from core.optimizer_md import md_then_optimize
    md_dir.mkdir(parents=True, exist_ok=True)
    success, final_xyz, info = md_then_optimize(
        str(source_xyz_path), str(md_dir),
        params=None, opt_level="tight",
        deterministic=True,
    )
    return success, final_xyz, info


def planarity_from_xyz(xyz_text: str, threshold_deg: float = 10.0):
    """PCA sur atomes lourds. Return (angle_deg, planar)."""
    import numpy as np
    lines = xyz_text.splitlines()
    if len(lines) < 3:
        return None, None
    try:
        n = int(lines[0].strip())
    except ValueError:
        return None, None
    coords = []
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4 and parts[0] != "H":
            try:
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                pass
    if len(coords) < 3:
        return None, None
    pts = np.array(coords, dtype=float)
    centered = pts - pts.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[2]
    dists = centered @ normal
    norms = np.linalg.norm(centered, axis=1)
    norms = np.where(norms > 1e-9, norms, 1e-9)
    sin_a = np.clip(np.abs(dists) / norms, 0, 1)
    angle = float(np.degrees(np.arcsin(sin_a)).max())
    return angle, angle <= threshold_deg


def run_one(entry: dict, db_path: str, output_root: Path,
             scratch_root: Path, timeout_sec: int = 600,
             cleanup: bool = True) -> dict:
    job_id = entry["job_id"]
    scratch = scratch_root / f"{SCRATCH_PREFIX}{job_id}_{os.getpid()}"
    scratch.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    status = {
        "job_id": job_id,
        "h": entry["h"],
        "config": entry["config"],
        "mol": entry["mol"],
        "sol_idx": entry["sol_idx"],
        "mmff_angle_deg": entry.get("mmff_angle_deg"),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
    }
    status_file = output_root / f"{job_id}.json"
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        text = fetch_source_xyz(db_path, entry["source_xyz_key"])
        if text is None:
            status["status"] = "failed"
            status["error"] = f"xyz missing: {entry['source_xyz_key']}"
            return _finalize(status, t0, status_file)
        src = scratch / "source.xyz"
        src.write_text(text, encoding="utf-8")

        md_dir = scratch / "md"
        success, final_xyz, info = run_xtb_md_opt(src, md_dir)
        status["xtb_success"] = bool(success)
        if not success:
            status["status"] = "xtb_failed"
            status["error"] = info.get("message", "?")
            return _finalize(status, t0, status_file)

        final_text = Path(final_xyz).read_text(encoding="utf-8")
        angle, planar = planarity_from_xyz(final_text, threshold_deg=10.0)
        status["xtb_angle_deg"] = angle
        status["xtb_planar"] = bool(planar) if planar is not None else None
        status["status"] = "ok"
        return _finalize(status, t0, status_file)
    except Exception as e:
        status["status"] = "failed"
        status["error"] = f"{type(e).__name__}: {e}"
        return _finalize(status, t0, status_file)
    finally:
        if cleanup:
            shutil.rmtree(scratch, ignore_errors=True)


def _finalize(status, t0, status_file):
    status["duration_sec"] = round(time.time() - t0, 1)
    status["ended_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        write_atomic_json(status_file, status)
    except OSError as e:
        print(f"  WARN status write : {e}", flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-json", required=True,
                        help="JSON dict de l'entree manifest (line)")
    parser.add_argument("--db", required=True, help="db_v4.db path")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()

    scratch_root = Path(args.scratch_root) if args.scratch_root \
                    else Path(tempfile.gettempdir())
    entry = json.loads(args.job_json)
    status = run_one(entry, args.db, Path(args.output_root),
                      scratch_root, args.timeout,
                      cleanup=not args.no_cleanup)
    sys.exit(0 if status["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
