"""Tests de non-regression rapide pour la phase 2 (option B + DB).

Ne lance PAS de vrai job. Verifie juste :
  1. Tous les modules touches importent sans erreur
  2. solutions_db.init_solutions_table cree bien les 2 tables
  3. solutions_db.get_job_solutions retourne None pour un job sans rows
  4. /api/designer/configs expose cluster_enabled
  5. Avec cluster=True dans config + env=0, run_job marque le job 'failed'
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "viewer"))


def test_imports():
    print("Test 1 : imports...")
    from viewer.designer import api, runner, cluster_runner, solutions_db, jobs
    assert hasattr(solutions_db, "init_solutions_table")
    assert hasattr(solutions_db, "ingest_local_job")
    assert hasattr(solutions_db, "get_job_solutions")
    assert hasattr(cluster_runner, "run_job_cluster")
    assert hasattr(cluster_runner, "check_cluster_alive")
    assert hasattr(runner, "run_job")
    print("  OK")


def test_init_tables():
    print("Test 2 : init tables solutions_db...")
    from viewer.designer import solutions_db, jobs
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = Path(d) / "test.db"
        jobs.init_jobs_table(str(db))
        solutions_db.init_solutions_table(str(db))
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            names = [r[0] for r in rows]
            assert "designer_jobs" in names, f"manque designer_jobs : {names}"
            assert "designer_solutions" in names, f"manque designer_solutions : {names}"
            assert "xyz_files" in names, f"manque xyz_files : {names}"
        # Verifie le schema designer_solutions
        with sqlite3.connect(str(db)) as conn:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(designer_solutions)").fetchall()]
            for needed in ("job_id", "sol_idx", "sol_name", "source_xyz_path",
                           "md_xyz_path", "planar", "angle_deg"):
                assert needed in cols, f"colonne manquante : {needed}"
    print("  OK")


def test_get_solutions_empty():
    print("Test 3 : get_job_solutions sur job vide retourne None...")
    from viewer.designer import solutions_db
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = Path(d) / "test.db"
        solutions_db.init_solutions_table(str(db))
        result = solutions_db.get_job_solutions(str(db), "nonexistent")
        assert result is None, f"attendu None, recu {result}"
    print("  OK")


def test_configs_exposes_cluster_flag():
    print("Test 4 : /api/designer/configs expose cluster_enabled...")
    # On instancie une app Flask minimaliste avec le blueprint
    from flask import Flask
    from viewer.designer import api as designer_api
    app = Flask(__name__)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = Path(d) / "test.db"
        app.config["DB_PATH"] = str(db)
        designer_api.init_app(app)
        client = app.test_client()
        # Sans env : cluster_enabled doit etre False
        os.environ.pop("DESIGNER_CLUSTER_ENABLED", None)
        r = client.get("/api/designer/configs")
        assert r.status_code == 200, r.status_code
        data = r.get_json()
        assert "cluster_enabled" in data
        assert data["cluster_enabled"] is False, data["cluster_enabled"]
        assert "configs" in data
        # Verifier qu'il y a bien une entree cluster dans configs
        keys = [c["key"] for c in data["configs"]]
        assert "cluster" in keys, f"manque cluster dans configs : {keys}"
        # Avec env=1
        os.environ["DESIGNER_CLUSTER_ENABLED"] = "1"
        r = client.get("/api/designer/configs")
        data = r.get_json()
        assert data["cluster_enabled"] is True
        os.environ.pop("DESIGNER_CLUSTER_ENABLED", None)
    print("  OK")


def test_run_with_cluster_disabled_fails_explicit():
    print("Test 5 : config.cluster=True + env off -> job 'failed' explicite...")
    from viewer.designer import runner, jobs, solutions_db
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = Path(d) / "test.db"
        jobs.init_jobs_table(str(db))
        solutions_db.init_solutions_table(str(db))
        job_id = jobs.create_job(
            str(db),
            graph_content="dummy",
            config={"cluster": True, "validate": False},
            output_dir="viewer/output/designer_jobs/test",
        )
        # S'assurer que l'env n'active pas le cluster
        os.environ.pop("DESIGNER_CLUSTER_ENABLED", None)
        # run_job sera bloquant mais doit retourner vite (fail immediat)
        runner.run_job(str(db), job_id, Path(d))
        job = jobs.get_job(str(db), job_id)
        assert job["state"] == "failed", f"attendu failed, recu {job['state']}"
        assert "DESIGNER_CLUSTER_ENABLED" in (job.get("error") or ""), \
            f"message d'erreur inattendu : {job.get('error')}"
    print("  OK")


def main():
    print("=" * 60)
    print("Phase 2 - tests de non-regression (smoke)")
    print("=" * 60)
    test_imports()
    test_init_tables()
    test_get_solutions_empty()
    test_configs_exposes_cluster_flag()
    test_run_with_cluster_disabled_fails_explicit()
    print("=" * 60)
    print("TOUS LES TESTS OK")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
