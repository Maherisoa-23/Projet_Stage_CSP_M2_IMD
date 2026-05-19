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
import re
import sqlite3
import sys
from pathlib import Path
from flask import Flask, abort, jsonify, render_template, request, send_file

# Permet d'importer molviz comme un sous-module
sys.path.insert(0, str(Path(__file__).resolve().parent))
from molviz import api as molviz_api  # noqa: E402

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
    search = request.args.get("search", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    size = min(500, max(10, int(request.args.get("size", 50))))
    sort = request.args.get("sort", "angle")
    # Tri : pour 'angle', on met les NULL (infeasible/xtb_failed) en queue.
    sort_map = {
        "angle":     "(angle_deg IS NULL), angle_deg ASC",
        "angle_desc":"(angle_deg IS NULL), angle_deg DESC",
        "idx":       "sol_idx ASC",
        "idx_desc":  "sol_idx DESC",
    }
    sort_sql = sort_map.get(sort, sort_map["angle"])

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

    # Recherche libre : matche sol_idx (egalite numerique si entier) OU sizes
    # (sous-chaine, ex. "6_6_5_7" matchera "..._6_6_5_7_..." aussi). Insensible
    # a la casse via LIKE (les sizes ne contiennent que des chiffres et "_").
    if search:
        sub = f"(sizes LIKE ?"
        params.append(f"%{search}%")
        if search.isdigit():
            sub += " OR sol_idx = ?"
            params.append(int(search))
        sub += ")"
        where.append(sub)

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
        # Chemin relatif du fichier d'optim de la molecule d'origine.
        # On le deduit d'un sol_dir quelconque de la mol (deux niveaux au-dessus),
        # car la table molecules ne stocke pas le mol_dir explicitement.
        original_xyz_path = None
        any_sol_dir = conn.execute(
            "SELECT sol_dir FROM solutions "
            "WHERE h = ? AND config = ? AND mol = ? LIMIT 1",
            (h, config, mol)
        ).fetchone()
        if any_sol_dir and any_sol_dir["sol_dir"]:
            sd = any_sol_dir["sol_dir"].replace("\\", "/").rstrip("/")
            # Format attendu : <prefix>/<mol>/solutions/sol_X_Y
            # On remonte deux fois pour atteindre <prefix>/<mol>/
            parts = sd.split("/")
            if len(parts) >= 3 and parts[-2] == "solutions":
                mol_dir_rel = "/".join(parts[:-2])
                original_xyz_path = f"{mol_dir_rel}/{mol}_original_opt.xyz"

    meta_out = dict(meta) if meta else None
    if meta_out is not None:
        meta_out["original_xyz_path"] = original_xyz_path
    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "molecule": meta_out,
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


def _resolve_local_path(rel):
    """Resout un chemin relatif depuis project_root vers un fichier local.
    Tente plusieurs reecritures pour gerer les DBs buildees sur le cluster
    (chemins comme '_h9_run/output/h9/...') vs builds locaux
    (chemins comme 'cluster_results/h9/...').

    Retourne (path_resolved, suffix_ok) ou (None, _) si rien trouve.
    """
    rel = rel.replace("\\", "/").lstrip("/")
    candidates = [rel]

    # Reecriture cluster -> local : '_hN_run/output/hN/<rest>' -> 'cluster_results/hN/<rest>'
    m = re.match(r"^_h(\d+)_run/output/h\1/(.+)$", rel)
    if m:
        candidates.append(f"cluster_results/h{m.group(1)}/{m.group(2)}")

    # Et inversement local -> cluster (si jamais tu as encore les fichiers
    # cluster en place a cote)
    m = re.match(r"^cluster_results/(h\d+)/(.+)$", rel)
    if m:
        candidates.append(f"_{m.group(1)}_run/output/{m.group(1)}/{m.group(2)}")

    # Aussi : 'csp_solver/experiments/output/hN/<rest>' (build local h3-h5)
    # est deja une variante naturelle ; pas de reecriture necessaire.

    for c in candidates:
        target = (_PROJECT_ROOT / c).resolve()
        try:
            target.relative_to(_PROJECT_ROOT.resolve())
        except ValueError:
            continue
        if target.is_file():
            return target

    # Fallback : si aucun chemin exact ne marche, on tente un glob sur le
    # prefixe sol_<idx>_ (le suffixe sizes peut differer legerement entre
    # build cluster et copie locale -- ex. encodage des tailles).
    # Pattern attendu : .../solutions/sol_<idx>_<sizes>/<filename>
    sol_re = re.compile(r"^(.+/solutions/)sol_(\d+)_[^/]+(/.+)$")
    for c in candidates:
        m = sol_re.match(c)
        if not m:
            continue
        prefix, idx, suffix = m.group(1), m.group(2), m.group(3)
        parent_dir = (_PROJECT_ROOT / prefix).resolve()
        try:
            parent_dir.relative_to(_PROJECT_ROOT.resolve())
        except ValueError:
            continue
        if not parent_dir.is_dir():
            continue
        # Cherche un sol_<idx>_* unique
        matches = sorted(parent_dir.glob(f"sol_{idx}_*"))
        for sol_dir in matches:
            target = (sol_dir / suffix.lstrip("/")).resolve()
            try:
                target.relative_to(_PROJECT_ROOT.resolve())
            except ValueError:
                continue
            if target.is_file():
                return target
    return None


@app.route("/file")
def serve_file():
    """Sert un fichier (xyz, json, ...) reference par chemin relatif depuis
    le project root. Securite : verifie que le chemin reste sous project_root
    et a une extension textuelle attendue.

    Path rewriting automatique : si la DB a ete buildee sur le cluster, ses
    chemins commencent par '_hN_run/output/hN/...' qui n'existe pas en local.
    On reessaie avec 'cluster_results/hN/...' (et inversement)."""
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    target = _resolve_local_path(rel)
    if target is None:
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
    # Branche le blueprint molviz (endpoint /api/mol3d). Il reutilise
    # _resolve_local_path pour gerer les chemins cluster<->local.
    molviz_api.init_app(app, _resolve_local_path)
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
