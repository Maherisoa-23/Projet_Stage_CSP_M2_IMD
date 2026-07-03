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
import gzip
import os
import re
import sqlite3
import sys
from pathlib import Path
from flask import Flask, Response, abort, jsonify, render_template, request, send_file

# Permet d'importer molviz comme un sous-module
sys.path.insert(0, str(Path(__file__).resolve().parent))
from molviz import api as molviz_api  # noqa: E402
from designer import api as designer_api  # noqa: E402

_HERE = Path(__file__).resolve().parent          # viewer/
_PROJECT_ROOT = _HERE.parent                     # racine projet (option C : viewer/ est a la racine)

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
    """Page d'accueil : hub de navigation vers les fonctionnalites.

    Exception : si ?job=<id> est present dans l'URL (lien genere par
    designer.js / tests.js pour ouvrir directement une vue job), on sert
    explorer.html qui gere ce param cote JS -- garde /?job=<id> fonctionnel
    sans dupliquer la logique de job view dans le hub.
    """
    if request.args.get("job"):
        return render_template("explorer.html")
    return render_template("hub.html")


@app.route("/explorer")
def explorer():
    """Explorateur du corpus pre-calcule (molecules/solutions h3-h9).
    Vide en mode --designer-only (pas de table 'configs')."""
    return render_template("explorer.html")


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
    """Stats par config pour UN dataset donne (param ?h=hN).

    Pour chaque config :
      - max_angle : agrege depuis molecules.max_angle (deja precalcule)
      - median_angle : calcule a la volee sur solutions via ORDER+OFFSET
        (cout : ~4 s sur h9 entier, acceptable pour une page de stats)
    """
    h = request.args.get("h", "")
    if not h:
        abort(400, description="missing 'h' parameter")
    with db() as conn:
        rows = conn.execute(
            "SELECT c.name, c.n_molecules, c.n_solutions, c.n_geom_infeasible, "
            "       c.n_plans, c.n_non_plans, "
            "       (SELECT MAX(m.max_angle) FROM molecules m "
            "          WHERE m.h = c.h AND m.config = c.name) AS max_angle "
            "FROM configs c WHERE c.h = ? ORDER BY c.name",
            (h,),
        ).fetchall()
        configs = [dict(r) for r in rows]
        for c in configs:
            n_angle = conn.execute(
                "SELECT COUNT(*) FROM solutions "
                "WHERE h = ? AND config = ? AND angle_deg IS NOT NULL",
                (h, c["name"]),
            ).fetchone()[0]
            if n_angle == 0:
                c["median_angle"] = None
                continue
            med = conn.execute(
                "SELECT angle_deg FROM solutions "
                "WHERE h = ? AND config = ? AND angle_deg IS NOT NULL "
                "ORDER BY angle_deg LIMIT 1 OFFSET ?",
                (h, c["name"], n_angle // 2),
            ).fetchone()
            c["median_angle"] = med[0] if med else None
        total_mols = conn.execute(
            "SELECT COUNT(DISTINCT mol) FROM molecules WHERE h = ?",
            (h,),
        ).fetchone()[0]
    return jsonify({
        "h": h,
        "configs": configs,
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
            f"       n_plans, n_tres_plan, n_acceptable, n_non_plans, "
            f"       min_angle, max_angle, "
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
    # Tri : NULL en queue.
    # 'angle' = max_dihedral_deg (= angle_deg apres migration vers verdict diedre).
    # Seuils chimistes (Denis Hagebaum-Reignier) : <10 tres plan, 10-25
    # acceptable, >=25 non plan.
    sort_map = {
        "angle":      "(angle_deg IS NULL), angle_deg ASC",
        "angle_desc": "(angle_deg IS NULL), angle_deg DESC",
        "idx":        "sol_idx ASC",
        "idx_desc":   "sol_idx DESC",
    }
    sort_sql = sort_map.get(sort, sort_map["angle"])

    where = ["h = ?", "config = ?", "mol = ?"]
    params = [h, config, mol]
    # Filtres bases sur le verdict diedre.
    # 'plans' = cumul tres_plan + acceptable (defaut, cf. dashboard).
    if flt == "plans":
        where.append("verdict IN ('tres_plan', 'acceptable')")
    elif flt == "tres_plan":
        where.append("verdict = 'tres_plan'")
    elif flt == "acceptable":
        where.append("verdict = 'acceptable'")
    elif flt == "non_plans":
        where.append("verdict = 'non_plan'")
    elif flt == "infeasible":
        where.append("verdict = 'geom_infeasible'")
    elif flt == "xtb_failed":
        where.append("verdict = 'xtb_failed'")
    elif flt == "validated":
        where.append("verdict IN ('tres_plan', 'acceptable', 'non_plan')")
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
        # angle_deg = max_dihedral_deg (= valeur courante apres migration).
        # On expose une seule colonne 'angle_deg' a l'UI ; l'ancien ACP
        # est conserve en DB sous 'angle_deg_acp' pour comparaison.
        rows = conn.execute(
            f"SELECT id, sol_idx, sizes, verdict, planar, angle_deg, "
            f"       rmsd, height, "
            f"       n_attempts, deterministic, sol_dir "
            f"FROM solutions{where_sql} "
            f"ORDER BY {sort_sql} "
            f"LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size]
        ).fetchall()
        meta = conn.execute(
            "SELECT n_solutions_csp, n_md_completed, "
            "       n_geom_infeasible, n_xtb_failed, "
            "       n_plans, n_tres_plan, n_acceptable, n_non_plans, "
            "       min_angle, max_angle, "
            "       job_status, job_duration_sec "
            "FROM molecules WHERE h = ? AND config = ? AND mol = ?",
            (h, config, mol)
        ).fetchone()

    meta_out = dict(meta) if meta else None
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


# Pattern pour les rel_path issus du run final :
# final/h{size_h}/{config}/{graph_name}/sol{sol_index}/md_validation/md_final_opt.xyz
# Si on match ce pattern, on peut faire un SELECT DIRECT sur final_solutions
# (INDEX seek via idx_copy_lookup, ~10 ms) au lieu de passer par la VIEW
# xyz_files qui force un SCAN FULL des 1.5M rows (~5000 ms). Gain : 500x.
_FINAL_REL_PATH_RE = re.compile(
    r"^final/h(\d+)/([^/]+)/([^/]+)/sol(\d+)/md_validation/md_final_opt\.xyz$"
)


def _load_xyz_text(rel: str) -> str | None:
    """Charge le contenu d'un xyz par chemin relatif (depuis project_root).

    Strategie de lookup (par ordre de cout croissant) :
      1. Filesystem (via _resolve_local_path) si le fichier existe
      2. SELECT DIRECT sur final_solutions par composants (size_h, config,
         graph_name, sol_index) si le rel_path matche le pattern run-final.
         Utilise idx_copy_lookup -> ~10 ms.
      3. VIEW xyz_files -> SCAN FULL final_solutions (~5000 ms). Fallback de
         derniere chance pour les paths qui ne matchent pas (3).
      4. Table designer_xyz_files (sols designer mode skip ou DB designer-only).

    Retourne le contenu texte (str), ou None si introuvable.
    """
    rel_norm = rel.replace("\\", "/").lstrip("/")

    # 1. Filesystem
    target = _resolve_local_path(rel_norm)
    if target is not None and target.is_file():
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    # 2. Fast path : SELECT direct sur final_solutions via composants
    row = None
    m = _FINAL_REL_PATH_RE.match(rel_norm)
    if m:
        size_h, config, graph_name, sol_index = m.groups()
        with db() as conn:
            row = conn.execute(
                "SELECT xyz_optimized_gz AS content_gz "
                "FROM final_solutions "
                "WHERE size_h=? AND config=? AND graph_name=? AND sol_index=? "
                "  AND status='done' AND xyz_optimized_gz IS NOT NULL",
                (int(size_h), config, graph_name, int(sol_index)),
            ).fetchone()

    # 3. Fallback : VIEW xyz_files (SCAN) ou table designer_xyz_files
    if row is None:
        with db() as conn:
            row = conn.execute(
                "SELECT content_gz FROM xyz_files WHERE rel_path = ?", (rel_norm,)
            ).fetchone()
            if not row:
                has_designer_xyz = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE name='designer_xyz_files' AND type='table'"
                ).fetchone()
                if has_designer_xyz:
                    row = conn.execute(
                        "SELECT content_gz FROM designer_xyz_files WHERE rel_path = ?",
                        (rel_norm,),
                    ).fetchone()

    if not row:
        return None
    try:
        return gzip.decompress(row["content_gz"]).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


# Path designer d'une solution : .../designer_jobs/<job_id>/sol_.../source.xyz
_DESIGNER_JOB_RE = re.compile(r"designer_jobs/([^/]+)/")


def _load_graph_text(rel: str) -> str | None:
    """Charge le contenu .graph de la solution designer designee par `rel`.

    `rel` est un chemin de solution (ex. .../designer_jobs/<job>/sol_X/source.xyz).
    On en extrait le job_id et on lit designer_jobs.graph_content (le .graph
    DIMACS d'entree, qui contient les lignes 'h' decrivant les hexagones).

    Retourne le texte .graph, ou None si pas un path designer / job absent.
    Utilise par le viewer pour construire le graphe dual (vue topologique).
    """
    rel_norm = rel.replace("\\", "/").lstrip("/")
    m = _DESIGNER_JOB_RE.search(rel_norm)
    if not m:
        return None
    job_id = m.group(1)
    try:
        with db() as conn:
            has_jobs = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE name='designer_jobs' AND type='table'"
            ).fetchone()
            if not has_jobs:
                return None
            row = conn.execute(
                "SELECT graph_content FROM designer_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row["graph_content"]:
        return None
    return row["graph_content"]


@app.route("/file")
def serve_file():
    """Sert un fichier (xyz, json, ...) reference par chemin relatif depuis
    le project root. Securite : verifie que le chemin reste sous project_root
    et a une extension textuelle attendue.

    Pour les .xyz : fallback DB via xyz_files (gzippe). Pour les autres
    extensions (.json/.inp/.log/.txt) : filesystem uniquement.

    Path rewriting automatique : si la DB a ete buildee sur le cluster, ses
    chemins commencent par '_hN_run/output/hN/...' qui n'existe pas en local.
    On reessaie avec 'cluster_results/hN/...' (et inversement)."""
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    rel_norm = rel.replace("\\", "/").lstrip("/")
    suffix = Path(rel_norm).suffix.lower()
    if suffix not in (".xyz", ".json", ".inp", ".log", ".txt"):
        abort(403)
    if suffix == ".xyz":
        text = _load_xyz_text(rel_norm)
        if text is None:
            abort(404)
        return Response(text, mimetype="text/plain")
    target = _resolve_local_path(rel_norm)
    if target is None:
        abort(404)
    return send_file(str(target), mimetype="text/plain")


# =====================================================================
#  Main
# =====================================================================

def main():
    ap = argparse.ArgumentParser()
    # Defaut : DESIGNER_DB_PATH si definie (mode conteneur, volume /data),
    # sinon le chemin local historique viewer/db_all.db.
    ap.add_argument("--db", default=os.getenv("DESIGNER_DB_PATH",
                                               str(_HERE / "db_all.db")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument(
        "--designer-only", action="store_true",
        help="Demarre sans exiger la DB d'exploration h3-h9 (final_solutions, "
             "configs, ...). Cree juste les tables designer_* dans une DB "
             "vide/neuve. Usage : livrable conteneurise pour les chimistes, "
             "qui n'ont besoin que du designer (dessin + CSP + xTB + viz), "
             "pas de l'explorateur de corpus pre-calcule (DB ~4 GB).",
    )
    args = ap.parse_args()
    app.config["DB_PATH"] = args.db
    # Branche le blueprint molviz (endpoint /api/mol3d). Il recoit deux
    # callbacks : _resolve_local_path (fs avec reecritures cluster<->local)
    # et _load_xyz_text (fs first + fallback DB xyz_files gzippe).
    molviz_api.init_app(app, _resolve_local_path, _load_xyz_text,
                        _load_graph_text)
    # Branche le blueprint designer (page /designer, endpoints /api/designer/*).
    # Cree au passage la table designer_jobs et le dossier de sortie, meme
    # si le fichier DB n'existait pas encore (sqlite3.connect le cree).
    designer_api.init_app(app)
    db_exists = Path(args.db).is_file()
    if not db_exists and not args.designer_only:
        print(f"ERREUR : DB introuvable : {args.db}")
        print("Lance d'abord :")
        print(f"    python {_HERE / 'build_db.py'} --auto-detect")
        print("(ou demarre avec --designer-only si tu n'as besoin que du "
              "designer, sans l'explorateur de corpus h3-h9)")
        return
    if args.designer_only and not db_exists:
        print(f"DB    : {args.db} (neuve, tables designer_* uniquement)")
        print("Mode designer-only : l'explorateur de corpus (/, /api/datasets, "
              "/api/molecules, ...) n'affichera aucune donnee. Seul /designer "
              "est fonctionnel.")
    else:
        print(f"DB    : {args.db}")
    print(f"Serve : http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
