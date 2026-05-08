"""
Serveur Flask local pour explorer la base CSP multi-datasets (h3..h9).

Endpoints :
  GET /                                            -> page principale (SPA)
  GET /api/datasets                                -> liste des h disponibles
  GET /api/summary?h=hN                            -> stats par config (filtre h)
  GET /api/molecules?h=&config=&search=&page=&size=&sort=
  GET /api/solutions?h=&config=&mol=&filter=&page=&size=&sort=
  GET /api/sol/<id>                                -> details d'une solution
  GET /file?path=<chemin relatif>                  -> sert un fichier xyz/json
                                                      depuis le project root

Lancer :
    python server.py [--db db_all.db] [--host 127.0.0.1] [--port 8765]

Puis ouvrir http://127.0.0.1:8765 dans le navigateur.
"""

import argparse
import sqlite3
from pathlib import Path
from flask import Flask, abort, jsonify, render_template, request, send_file

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent

app = Flask(
    __name__,
    template_folder=str(_HERE / "templates"),
    static_folder=str(_HERE / "static"),
)
app.config["DB_PATH"] = str(_HERE / "db_all.db")


def db():
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


# =====================================================================
#  Pages
# =====================================================================

@app.route("/")
def index():
    return render_template("index.html")


# =====================================================================
#  API
# =====================================================================

@app.route("/api/datasets")
def api_datasets():
    """Liste les datasets (h) presents dans la DB avec un compte rapide."""
    with db() as conn:
        rows = conn.execute(
            "SELECT h, "
            "       COUNT(*) AS n_configs, "
            "       SUM(n_molecules) AS n_mol_rows, "
            "       SUM(n_solutions) AS n_solutions, "
            "       SUM(n_geom_infeasible) AS n_geom_infeasible, "
            "       SUM(n_plans) AS n_plans, "
            "       SUM(n_non_plans) AS n_non_plans "
            "FROM configs GROUP BY h ORDER BY h"
        ).fetchall()
    return jsonify({"datasets": [dict(r) for r in rows]})


@app.route("/api/summary")
def api_summary():
    """Stats par config pour UN dataset donne (param ?h=hN)."""
    h = request.args.get("h", "")
    if not h:
        abort(400, description="missing 'h' parameter")
    with db() as conn:
        rows = conn.execute(
            "SELECT name, n_molecules, n_solutions, n_geom_infeasible, "
            "       n_plans, n_non_plans "
            "FROM configs WHERE h = ? ORDER BY name",
            (h,),
        ).fetchall()
        total_mols = conn.execute(
            "SELECT COUNT(DISTINCT mol) FROM molecules WHERE h = ?",
            (h,),
        ).fetchone()[0]
    return jsonify({
        "h": h,
        "configs": [dict(r) for r in rows],
        "n_unique_molecules": total_mols,
    })


@app.route("/api/molecules")
def api_molecules():
    h = request.args.get("h", "")
    config = request.args.get("config", "")
    if not h or not config:
        abort(400, description="missing 'h' or 'config' parameter")
    search = request.args.get("search", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    size = min(500, max(10, int(request.args.get("size", 50))))
    sort = request.args.get("sort", "name")
    if sort not in {"name", "plans", "sols", "min_angle"}:
        sort = "name"
    sort_sql = {
        "name": "mol ASC",
        "plans": "n_plans DESC, mol ASC",
        "sols": "n_md_completed DESC, mol ASC",
        "min_angle": "(min_angle IS NULL), min_angle ASC",
    }[sort]

    where = ["h = ?", "config = ?"]
    params = [h, config]
    if search:
        where.append("mol LIKE ?")
        params.append(f"%{search}%")
    where_sql = " WHERE " + " AND ".join(where)

    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM molecules{where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT mol, n_solutions_csp, n_md_completed, "
            f"       n_geom_infeasible, n_xtb_failed, "
            f"       n_plans, n_non_plans, min_angle, max_angle, "
            f"       original_planar, original_angle_deg, "
            f"       job_status, job_duration_sec "
            f"FROM molecules{where_sql} "
            f"ORDER BY {sort_sql} "
            f"LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size]
        ).fetchall()
    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "molecules": [dict(r) for r in rows],
    })


@app.route("/api/solutions")
def api_solutions():
    h = request.args.get("h", "")
    config = request.args.get("config", "")
    mol = request.args.get("mol", "")
    if not h or not config or not mol:
        abort(400, description="missing 'h', 'config' or 'mol' parameter")
    flt = request.args.get("filter", "all")
    page = max(1, int(request.args.get("page", 1)))
    size = min(500, max(10, int(request.args.get("size", 50))))
    sort = request.args.get("sort", "angle")
    # Tri : pour 'angle', on met les NULL (infeasible/xtb_failed) en queue.
    sort_sql = ("(angle_deg IS NULL), angle_deg ASC"
                if sort == "angle" else "sol_idx ASC")

    where = ["h = ?", "config = ?", "mol = ?"]
    params = [h, config, mol]
    if flt == "plans":
        where.append("verdict = 'plan'")
    elif flt == "non_plans":
        where.append("verdict = 'non_plan'")
    elif flt == "infeasible":
        where.append("verdict = 'geom_infeasible'")
    elif flt == "xtb_failed":
        where.append("verdict = 'xtb_failed'")
    elif flt == "validated":
        where.append("verdict IN ('plan', 'non_plan')")
    # 'all' : pas de filtre supplementaire
    where_sql = " WHERE " + " AND ".join(where)

    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM solutions{where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, sol_idx, sizes, verdict, planar, angle_deg, rmsd, height, "
            f"       n_attempts, deterministic, sol_dir "
            f"FROM solutions{where_sql} "
            f"ORDER BY {sort_sql} "
            f"LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size]
        ).fetchall()
        meta = conn.execute(
            "SELECT n_solutions_csp, n_md_completed, "
            "       n_geom_infeasible, n_xtb_failed, "
            "       n_plans, n_non_plans, "
            "       min_angle, max_angle, original_planar, original_angle_deg, "
            "       job_status, job_duration_sec "
            "FROM molecules WHERE h = ? AND config = ? AND mol = ?",
            (h, config, mol)
        ).fetchone()
    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "molecule": dict(meta) if meta else None,
        "solutions": [dict(r) for r in rows],
    })


@app.route("/api/sol/<int:sol_id>")
def api_sol(sol_id):
    with db() as conn:
        r = conn.execute(
            "SELECT * FROM solutions WHERE id = ?", (sol_id,)
        ).fetchone()
    if not r:
        abort(404)
    return jsonify(dict(r))


@app.route("/file")
def serve_file():
    """Sert un fichier (xyz, json, ...) reference par chemin relatif depuis
    le project root. Securite : verifie que le chemin reste sous project_root
    et a une extension textuelle attendue."""
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    rel = rel.replace("\\", "/")
    target = (_PROJECT_ROOT / rel).resolve()
    try:
        target.relative_to(_PROJECT_ROOT.resolve())
    except ValueError:
        abort(403)
    if not target.is_file():
        abort(404)
    if target.suffix.lower() not in (".xyz", ".json", ".inp", ".log", ".txt"):
        abort(403)
    return send_file(str(target), mimetype="text/plain")


# =====================================================================
#  Main
# =====================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_HERE / "db_all.db"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    app.config["DB_PATH"] = args.db
    if not Path(args.db).is_file():
        print(f"ERREUR : DB introuvable : {args.db}")
        print("Lance d'abord :")
        print(f"    python {_HERE / 'build_db.py'} --auto-detect")
        return
    print(f"DB    : {args.db}")
    print(f"Serve : http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
