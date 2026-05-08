"""
Serveur Flask local pour explorer la base h9.db.

Endpoints :
  GET /                                            → page principale
  GET /api/summary                                 → stats par config
  GET /api/molecules?config=X&search=&page=&size=&sort=
  GET /api/solutions?config=X&mol=Y&filter=&page=&size=&sort=
  GET /api/sol/<id>                                → détails d'une solution
  GET /file?path=<chemin relatif>                  → sert un fichier xyz/json
                                                     depuis le project root

Lancer :
    python server.py [--db h9.db] [--host 127.0.0.1] [--port 8765]

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
app.config["DB_PATH"] = str(_HERE / "h9.db")


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

@app.route("/api/summary")
def api_summary():
    with db() as conn:
        rows = conn.execute(
            "SELECT name, n_molecules, n_solutions, n_geom_infeasible, "
            "       n_plans, n_non_plans "
            "FROM configs ORDER BY name"
        ).fetchall()
        total_mols = conn.execute(
            "SELECT COUNT(DISTINCT mol) FROM molecules"
        ).fetchone()[0]
    return jsonify({
        "configs": [dict(r) for r in rows],
        "n_unique_molecules": total_mols,
    })


@app.route("/api/molecules")
def api_molecules():
    config = request.args.get("config", "")
    search = request.args.get("search", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    size = min(500, max(10, int(request.args.get("size", 50))))
    sort = request.args.get("sort", "name")  # name | plans | sols
    if sort not in {"name", "plans", "sols", "min_angle"}:
        sort = "name"
    sort_sql = {
        "name": "mol ASC",
        "plans": "n_plans DESC, mol ASC",
        "sols": "n_md_completed DESC, mol ASC",
        "min_angle": "(min_angle IS NULL), min_angle ASC",
    }[sort]

    where = ["config = ?"]
    params = [config]
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
    config = request.args.get("config", "")
    mol = request.args.get("mol", "")
    flt = request.args.get("filter", "all")  # all | plans | non_plans
    page = max(1, int(request.args.get("page", 1)))
    size = min(500, max(10, int(request.args.get("size", 50))))
    sort = request.args.get("sort", "angle")  # angle | idx
    sort_sql = "angle_deg ASC" if sort == "angle" else "sol_idx ASC"

    where = ["config = ?", "mol = ?"]
    params = [config, mol]
    if flt == "plans":
        where.append("planar = 1")
    elif flt == "non_plans":
        where.append("planar = 0")
    where_sql = " WHERE " + " AND ".join(where)

    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM solutions{where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, sol_idx, sizes, planar, angle_deg, rmsd, height, "
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
            "FROM molecules WHERE config = ? AND mol = ?",
            (config, mol)
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
    """Sert un fichier (xyz, json, ...) référencé par chemin relatif depuis
    le project root. Sécurité : vérifie que le chemin résolu reste sous
    project root et sous cluster_results/ ou csp_solver/."""
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
    # Limiter aux extensions textuelles attendues
    if target.suffix.lower() not in (".xyz", ".json", ".inp", ".log", ".txt"):
        abort(403)
    return send_file(str(target), mimetype="text/plain")


# =====================================================================
#  Main
# =====================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_HERE / "h9.db"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    app.config["DB_PATH"] = args.db
    if not Path(args.db).is_file():
        print(f"ERREUR : DB introuvable : {args.db}")
        print("Lance d'abord :")
        print(f"    python {_HERE / 'build_db.py'}")
        return
    print(f"DB    : {args.db}")
    print(f"Serve : http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
