"""
Endpoints Flask du module designer.

Routes (toutes prefixees par /api/designer/ sauf /designer pour la page) :

    GET    /designer                          -> page principale (template)
    GET    /api/designer/configs              -> options CSP disponibles (statique)
    GET    /api/designer/templates            -> liste des .graph dans data/
    GET    /api/designer/templates/<name>     -> contenu d'un .graph
    POST   /api/designer/run                  -> lance un job, retourne job_id
    GET    /api/designer/jobs                 -> liste des jobs recents
    GET    /api/designer/jobs/<id>            -> etat d'un job (polling)
    POST   /api/designer/jobs/<id>/cancel     -> annule un job en cours
    GET    /api/designer/jobs/<id>/viewer     -> URL viewer pour les resultats

Tous les endpoints retournent du JSON sauf /designer (HTML) et les contenus
de fichier (text/plain).
"""

import json
from pathlib import Path
from typing import Optional

from flask import Blueprint, abort, jsonify, render_template, request, current_app

from . import graph_io, jobs, runner, solutions_db
from .csp_presets import (
    CSP_PRESETS_CANONICAL,
    CSP_PRESETS_LEGACY,
    CSP_ADVANCED_OPTIONS,
    ADVANCED_GROUPS,
    VALIDATION_OPTIONS,
    resolve_preset_flags,
)


_HERE = Path(__file__).resolve().parent
bp = Blueprint(
    "designer", __name__,
    static_folder=str(_HERE / "static"),
    static_url_path="/designer_static",
)


# Definitions des configs/presets/options : extraites dans csp_presets.py
# pour ne pas alourdir ce fichier (~150 lignes de declarations).


def _cluster_globally_enabled() -> bool:
    """True si le toggle global DESIGNER_CLUSTER_ENABLED=1 est dans l'env."""
    import os
    return os.getenv("DESIGNER_CLUSTER_ENABLED", "0") == "1"


# =====================================================================
#  Helpers
# =====================================================================

def _project_root() -> Path:
    """Resout la racine du projet.
    __file__ = viewer/designer/api.py (option C) -> 2 niveaux au-dessus.
    """
    return _HERE.parent.parent


def _designer_output_root() -> Path:
    """Dossier ou sont stockes les outputs des jobs designer."""
    return _project_root() / "viewer" / "output" / "designer_jobs"


def _data_dir() -> Path:
    """Dossier ou sont stockes les .graph templates (csp_solver/data/)."""
    return _project_root() / "csp_solver" / "data"


# =====================================================================
#  Route HTML
# =====================================================================

@bp.route("/designer")
def page_designer():
    return render_template("designer.html")


# =====================================================================
#  Configs CSP
# =====================================================================

@bp.route("/api/designer/configs")
def api_configs():
    """Retourne la structure declarative pour construire le panneau designer.

    Format de la reponse :
      {
        "presets_canonical": [...],   // 4 presets C1/C2/C3/Ctopo (radios)
        "advanced_options": [...],    // options du tableau de bord
        "advanced_groups": [...],     // groupes thematiques (ordre + label)
        "validation_options": [...],  // options xTB (bloc separe)
        "cluster_enabled": bool,      // masque l'option cluster si False
      }

    Le frontend utilise `cluster_enabled` pour decider d'afficher ou non
    la case "Executer xTB sur cluster". Quand False, l'option est masquee.
    """
    return jsonify({
        "presets_canonical": CSP_PRESETS_CANONICAL,
        "advanced_options": CSP_ADVANCED_OPTIONS,
        "advanced_groups": [
            {"key": k, "label": label} for k, label in ADVANCED_GROUPS
        ],
        "validation_options": VALIDATION_OPTIONS,
        "cluster_enabled": _cluster_globally_enabled(),
    })


# =====================================================================
#  Templates .graph (molecules existantes dans csp_solver/data/)
# =====================================================================

@bp.route("/api/designer/templates")
def api_templates():
    """Liste les .graph disponibles dans csp_solver/data/."""
    data_dir = _data_dir()
    if not data_dir.is_dir():
        return jsonify({"templates": []})
    templates = []
    for f in sorted(data_dir.glob("*.graph")):
        try:
            content = f.read_text(encoding="utf-8")
            hexes = graph_io.parse_graph_to_hexes(content)
            templates.append({
                "name": f.stem,
                "filename": f.name,
                "n_hex": len(hexes),
                "size_bytes": f.stat().st_size,
            })
        except Exception:
            # Fichier .graph non-conforme : on l'ignore
            continue
    return jsonify({"templates": templates})


@bp.route("/api/designer/templates/<name>")
def api_template_content(name: str):
    """Retourne le contenu d'un .graph + ses hexagones extraits.

    Le param `name` est sans extension (ex : "1" pour 1.graph).
    """
    # Securite : refuser tout caractere bizarre dans le nom
    if not name.replace("_", "").replace("-", "").isalnum():
        abort(400, description="invalid template name")
    f = _data_dir() / f"{name}.graph"
    if not f.is_file():
        abort(404)
    content = f.read_text(encoding="utf-8")
    try:
        hexes = graph_io.parse_graph_to_hexes(content)
    except Exception as e:
        return jsonify({"error": f"parse failed: {e}"}), 400
    return jsonify({
        "name": name,
        "content": content,
        "hexes": [{"q": q, "r": r} for q, r in hexes],
    })


# =====================================================================
#  Jobs : lancement, suivi, annulation
# =====================================================================

@bp.route("/api/designer/run", methods=["POST"])
def api_run():
    """Lance un nouveau job CSP.

    Body JSON :
        {
            "hexes": [{"q": 0, "r": 0}, ...],   # ou bien
            "graph_content": "...",              # alternative directe
            "config": { ... options CSP ... }
        }

    Reponse : 202 Accepted, { "job_id": "abc12345" }
    """
    data = request.get_json(silent=True) or {}
    config = data.get("config", {}) or {}

    # Resoudre le contenu .graph : soit depuis hexes (priorite), soit
    # depuis graph_content directement.
    graph_content: Optional[str] = None
    if "hexes" in data:
        try:
            hexes_list = [(int(h["q"]), int(h["r"])) for h in data["hexes"]]
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "champ 'hexes' invalide"}), 400
        ok, msg = graph_io.validate_hex_set(hexes_list)
        if not ok:
            return jsonify({"error": f"hex set invalide : {msg}"}), 400
        graph_content = graph_io.serialize_to_graph(hexes_list)
    elif "graph_content" in data:
        graph_content = str(data["graph_content"])
    else:
        return jsonify({"error": "champ 'hexes' ou 'graph_content' requis"}), 400

    # Cree le job en DB
    db_path = current_app.config["DB_PATH"]
    job_id_tmp = jobs.create_job(db_path, graph_content, config, output_dir="tmp")
    # Maintenant qu'on a un job_id, fixe le vrai output_dir relatif
    rel_output = (Path("viewer/output/designer_jobs")
                  / job_id_tmp).as_posix()
    jobs.update_job(db_path, job_id_tmp, output_dir=rel_output)

    # Lance le thread runner
    runner.start_job_thread(db_path, job_id_tmp, _project_root())

    return jsonify({"job_id": job_id_tmp}), 202


@bp.route("/api/designer/jobs")
def api_jobs_list():
    """Liste les jobs recents (limite a 50)."""
    db_path = current_app.config["DB_PATH"]
    return jsonify({"jobs": jobs.list_jobs(db_path, limit=50)})


@bp.route("/api/designer/jobs/<job_id>")
def api_job_status(job_id: str):
    """Retourne l'etat complet d'un job."""
    db_path = current_app.config["DB_PATH"]
    job = jobs.get_job(db_path, job_id)
    if job is None:
        abort(404, description="job not found")
    # Ne pas exposer le graph_content dans tous les polls (ca peut etre lourd)
    if request.args.get("include_graph") != "1":
        job.pop("graph_content", None)
    return jsonify(job)


@bp.route("/api/designer/jobs/<job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id: str):
    """Tente d'annuler un job en cours."""
    db_path = current_app.config["DB_PATH"]
    ok = runner.cancel_job(db_path, job_id)
    return jsonify({"ok": ok})


def _compute_verdict(md_verdict, planar):
    """Verdict global d'une solution. Identique fs et DB.

    md_failed prime sur tout. Sinon planar=True -> 'plan', False -> 'non_plan',
    None -> 'unknown' (MD ok mais planarite non calculee).
    """
    if md_verdict == "md_failed":
        return "md_failed"
    if planar is True:
        return "plan"
    if planar is False:
        return "non_plan"
    return "unknown"


def _build_sol_dict_from_db(row):
    """Construit le dict de reponse d'une solution depuis une row designer_solutions.

    Format identique a celui produit par le parcours filesystem, pour ne
    pas casser le frontend.
    """
    planar = row.get("planar")
    md_verdict = row.get("md_verdict") or "unknown"
    best = row.get("md_xyz_path") or row.get("source_xyz_path")
    return {
        "name": row["sol_name"],
        "sol_idx": str(row["sol_idx"]),
        "sizes": row.get("sizes") or "",
        "has_source_xyz": bool(row.get("source_xyz_path")),
        "has_md_xyz": bool(row.get("md_xyz_path")),
        "best_xyz_path": best,
        "md_verdict": md_verdict,
        "n_attempts": row.get("n_attempts"),
        "planar": planar,
        "angle_deg": row.get("angle_deg"),
        "rmsd": row.get("rmsd"),
        "height": row.get("height"),
        "verdict": _compute_verdict(md_verdict, planar),
    }


def _read_original_block(output_dir, project_root, summary=None):
    """Retourne le dict 'original' (planarity du benzenoide d'entree).

    Strategie de lecture, par ordre de priorite :
      1. summary['original'] (ingere en DB par ingest_local_job) -> idempotent,
         survit a la suppression du workdir.
      2. output_dir/original/planarity.json + original_opt.xyz (legacy fs).
      3. None si ni l'un ni l'autre.
    """
    if summary and isinstance(summary.get("original"), dict):
        return summary["original"]
    orig_dir = output_dir / "original"
    orig_plan = orig_dir / "planarity.json"
    orig_opt_xyz = orig_dir / "original_opt.xyz"
    if not orig_plan.is_file():
        return None
    try:
        original = json.loads(orig_plan.read_text(encoding="utf-8",
                                                   errors="replace"))
        if orig_opt_xyz.is_file():
            original["xyz_path"] = orig_opt_xyz.relative_to(project_root).as_posix()
        return original
    except (OSError, ValueError):
        return {"success": False, "message": "planarity.json corrompu"}


def _count_verdicts(sols):
    """Compteurs agreges pour les badges du frontend."""
    return {
        "plan": sum(1 for s in sols if s["verdict"] == "plan"),
        "non_plan": sum(1 for s in sols if s["verdict"] == "non_plan"),
        "md_failed": sum(1 for s in sols if s["verdict"] == "md_failed"),
        "unknown": sum(1 for s in sols if s["verdict"] == "unknown"),
    }


@bp.route("/api/designer/jobs/<job_id>/solutions")
def api_job_solutions(job_id: str):
    """Liste les solutions d'un job designer.

    Pour chaque sol_X_<sizes> trouve dans le output_dir du job, retourne :
      - name           : "sol_1_5_6_7"
      - sol_idx        : "1"
      - sizes          : "5_6_7" (ou "" si non parsable)
      - has_source_xyz, has_md_xyz : flags de presence
      - best_xyz_path  : chemin relatif vers le xyz a afficher (priorise
                         md_final_opt.xyz, sinon source.xyz, sinon None)
      - md_verdict     : "md_ok" | "md_failed" | "unknown" (statut convergence MD)
      - n_attempts     : nombre de tentatives MD (depuis md_meta.json)
      - planar         : True/False/None (depuis sol_dir/planarity.json)
      - angle_deg, rmsd, height : metriques de planarite (None si pas calcule)
      - verdict        : "plan" | "non_plan" | "md_failed" | "unknown"
                         (verdict global combinant MD et planarite)

    Inclut aussi le bloc "original" depuis output_dir/original/planarity.json :
    metriques de planarite du benzenoide d'entree (tout-hexagones, opt xTB).
    """
    db_path = current_app.config["DB_PATH"]
    job = jobs.get_job(db_path, job_id)
    if job is None:
        abort(404, description="job not found")
    output_dir = _project_root() / job["output_dir"]
    project_root = _project_root()

    # --- Lecture DB en priorite, conditionnee a ingest_complete ---
    # On lit la DB UNIQUEMENT si l'ingestion s'est terminee avec succes
    # (summary.ingest_complete=True). Sinon on retombe sur le filesystem
    # pour eviter de masquer une ingestion partielle (cf. audit phase 2 :
    # une exception au milieu de ingest_local_job pouvait laisser N-1
    # rows en DB sans qu'on le sache).
    summary = job.get("summary") or {}
    if summary.get("ingest_complete"):
        db_sols = solutions_db.get_job_solutions(db_path, job_id)
        if db_sols:
            sols = [_build_sol_dict_from_db(row) for row in db_sols]
            original = _read_original_block(output_dir, project_root, summary)
            counts = _count_verdicts(sols)
            return jsonify({
                "job_id": job_id,
                "state": job["state"],
                "n_solutions": len(sols),
                "output_dir": job["output_dir"],
                "output_dir_exists": output_dir.is_dir(),
                "original": original,
                "counts": counts,
                "solutions": sols,
            })

    # --- Fallback : lecture filesystem (mode legacy, jobs pre-DB) ---
    if not output_dir.is_dir():
        return jsonify({
            "job_id": job_id,
            "state": job["state"],
            "solutions": [],
            "original": None,
            "output_dir_exists": False,
        })

    original = _read_original_block(output_dir, project_root)

    sols = []
    for sol_dir in sorted(output_dir.glob("sol_*"), key=lambda p: p.name):
        if not sol_dir.is_dir():
            continue
        parts = sol_dir.name.split("_")
        sol_idx = parts[1] if len(parts) > 1 else "?"
        sizes = "_".join(parts[2:]) if len(parts) > 2 else ""
        source_xyz = sol_dir / "source.xyz"
        md_dir = sol_dir / "md_validation"
        md_final = md_dir / "md_final_opt.xyz"

        # md_verdict + n_attempts depuis md_meta.json
        md_verdict = "unknown"
        n_attempts = None
        meta_file = md_dir / "md_meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                n_attempts = meta.get("n_attempts")
                if meta.get("success") and meta.get("converged"):
                    md_verdict = "md_ok"
                else:
                    md_verdict = "md_failed"
            except Exception:
                pass

        # planarite depuis sol_dir/planarity.json (ecrit par le runner apres main.py)
        planar = None
        angle_deg = None
        rmsd = None
        height = None
        plan_file = sol_dir / "planarity.json"
        if plan_file.is_file():
            try:
                p = json.loads(plan_file.read_text(encoding="utf-8"))
                if p.get("success"):
                    planar = p.get("planar")
                    angle_deg = p.get("angle_deg")
                    rmsd = p.get("rmsd")
                    height = p.get("height")
            except Exception:
                pass

        # Verdict global : prioritise la planarite si calculee, sinon md_verdict.
        # Coherent avec view-mol : un sol "MD ok" sans planarite calculee
        # reste flou ; on l'expose comme "unknown".
        if md_verdict == "md_failed":
            verdict = "md_failed"
        elif planar is True:
            verdict = "plan"
        elif planar is False:
            verdict = "non_plan"
        else:
            verdict = "unknown"

        if md_final.is_file():
            best_xyz = md_final.relative_to(project_root).as_posix()
        elif source_xyz.is_file():
            best_xyz = source_xyz.relative_to(project_root).as_posix()
        else:
            best_xyz = None

        sols.append({
            "name": sol_dir.name,
            "sol_idx": sol_idx,
            "sizes": sizes,
            "has_source_xyz": source_xyz.is_file(),
            "has_md_xyz": md_final.is_file(),
            "best_xyz_path": best_xyz,
            "md_verdict": md_verdict,
            "n_attempts": n_attempts,
            "planar": planar,
            "angle_deg": angle_deg,
            "rmsd": rmsd,
            "height": height,
            "verdict": verdict,
        })

    # Compteurs agreges pour les badges du frontend
    counts = {
        "plan": sum(1 for s in sols if s["verdict"] == "plan"),
        "non_plan": sum(1 for s in sols if s["verdict"] == "non_plan"),
        "md_failed": sum(1 for s in sols if s["verdict"] == "md_failed"),
        "unknown": sum(1 for s in sols if s["verdict"] == "unknown"),
    }

    return jsonify({
        "job_id": job_id,
        "state": job["state"],
        "n_solutions": len(sols),
        "output_dir": job["output_dir"],
        "output_dir_exists": True,
        "original": original,
        "counts": counts,
        "solutions": sols,
    })


@bp.route("/api/designer/jobs/<job_id>/viewer")
def api_job_viewer_link(job_id: str):
    """Retourne un lien vers le viewer pour explorer les resultats du job.

    Comme on stocke les outputs sous designer_jobs/<id>/, on retourne un
    chemin que le viewer principal peut interpreter.
    """
    db_path = current_app.config["DB_PATH"]
    job = jobs.get_job(db_path, job_id)
    if job is None:
        abort(404)
    if job.get("state") != "success":
        return jsonify({"error": "job not in success state"}), 400
    return jsonify({
        "output_dir": job["output_dir"],
        "summary": job.get("summary", {}),
    })


# =====================================================================
#  Initialisation
# =====================================================================

def init_app(app):
    """Branche le blueprint sur l'app Flask.

    Doit etre appele apres app.config['DB_PATH'] = ...
    Cree la table designer_jobs et le dossier de sortie au passage.
    """
    db_path = app.config.get("DB_PATH")
    if db_path:
        jobs.init_jobs_table(db_path)
        solutions_db.init_solutions_table(db_path)
    _designer_output_root().mkdir(parents=True, exist_ok=True)
    app.register_blueprint(bp)
