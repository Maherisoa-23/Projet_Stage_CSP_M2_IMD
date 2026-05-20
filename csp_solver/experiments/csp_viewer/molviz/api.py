"""
Endpoint Flask /api/mol3d.

Sert un JSON consommable par 3Dmol.js cote frontend, avec :
  - atoms     : carbones uniquement (les H sont droppes pour le rendu)
  - bonds     : liaisons C-C avec ordre (1 ou 2) determine par matching Kekule
  - radicals  : indices d'atomes non couverts par le matching
  - cycles    : faces 5/6/7 du graphe planaire (pour coloration)
  - meta      : sources, n_atoms, etc.

L'endpoint accepte un parametre `path` qui est resolu cote serveur via
le helper de path-rewriting de server.py (gere les chemins cluster vs locaux).

Cache LRU 256 entrees (~2 MB max) pour eviter de recalculer matching +
cycles a chaque clic sur la meme molecule.
"""

from functools import lru_cache
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_from_directory

from .bonds import build_mol_graph_from_text
from .clar import enumerate_clar_covers
from .kekule import assign_kekule, enumerate_kekule
from .rbo import compute_rbo, DEFAULT_MAX_KEKULE


_HERE = Path(__file__).resolve().parent
bp = Blueprint(
    "molviz", __name__,
    static_folder=str(_HERE / "static"),
    static_url_path="/molviz_static",
)


@lru_cache(maxsize=256)
def _compute_mol3d(cache_key: str, xyz_text: str) -> dict:
    """Calcul lourd : parse XYZ + bonds + Kekule + cycles.
    Cle de cache = (rel_path, xyz_text). En pratique xyz_text est stable
    pour une cle donnee, donc le tuple sert juste a cacher correctement.
    """
    mol = build_mol_graph_from_text(xyz_text)
    if not mol.atoms:
        return {"error": "empty or unreadable xyz"}

    kekule = assign_kekule(mol)

    n_anomaly = sum(1 for c in mol.cycles if c.anomaly)
    return {
        "atoms": [a.to_dict() for a in mol.atoms],
        "bonds": [
            {"a": int(u), "b": int(v), "order": int(order)}
            for (u, v), order in zip(mol.bonds, kekule.bond_orders)
        ],
        "cycles": [
            {
                "size": c.size,
                "atoms": [int(i) for i in c.atoms],
                "anomaly": bool(c.anomaly),
            }
            for c in mol.cycles
        ],
        "radicals": sorted(int(i) for i in kekule.radicals),
        "meta": {
            "n_carbons": len(mol.atoms),
            "n_bonds": len(mol.bonds),
            "n_doubles": int(kekule.n_doubles),
            "n_radicals": len(kekule.radicals),
            "n_cycles": len(mol.cycles),
            "n_anomaly_cycles": n_anomaly,
            "perfect_matching": bool(kekule.is_perfect),
            "source": cache_key,
        },
    }


@lru_cache(maxsize=256)
def _compute_kekule_list(cache_key: str, xyz_text: str, max_count: int) -> dict:
    """Calcul d'une liste de Kekule, plafonnee a max_count.

    Cle de cache = (rel_path, xyz_text, max_count). On garde une entree
    distincte par max_count pour eviter que demander 50 puis 500 ne re-utilise
    le cache tronque a 50.
    """
    mol = build_mol_graph_from_text(xyz_text)
    if not mol.atoms:
        return {"error": "empty or unreadable xyz"}

    kekule_list, is_exact = enumerate_kekule(mol, max_count=max_count)

    return {
        "kekule": [
            {
                "bond_orders": [int(o) for o in k.bond_orders],
                "radicals": sorted(int(i) for i in k.radicals),
                "n_doubles": int(k.n_doubles),
            }
            for k in kekule_list
        ],
        "meta": {
            "returned": len(kekule_list),
            "is_exact": bool(is_exact),
            "has_more": not is_exact,
            "max_requested": int(max_count),
            "source": cache_key,
        },
    }


@lru_cache(maxsize=256)
def _compute_clar_list(cache_key: str, xyz_text: str, max_count: int) -> dict:
    """Calcul des couvertures de Clar d'une molecule.

    Cle de cache = (rel_path, xyz_text, max_count). Retourne la liste des
    couvertures de score MAXIMUM (= nombre de Clar), chacune avec ses
    sextets, bond_orders canoniques et radicaux du residu.
    """
    mol = build_mol_graph_from_text(xyz_text)
    if not mol.atoms:
        return {"error": "empty or unreadable xyz"}

    covers, is_exact = enumerate_clar_covers(mol, max_count=max_count)
    clar_number = covers[0].n_sextets if covers else 0

    return {
        "clar": [
            {
                "sextets": [int(s) for s in c.sextets],
                "bond_orders": [int(o) for o in c.bond_orders],
                "radicals": sorted(int(i) for i in c.radicals),
                "n_sextets": int(c.n_sextets),
            }
            for c in covers
        ],
        "meta": {
            "returned": len(covers),
            "is_exact": bool(is_exact),
            "has_more": not is_exact,
            "max_requested": int(max_count),
            "clar_number": int(clar_number),
            "source": cache_key,
        },
    }


@lru_cache(maxsize=256)
def _compute_rbo_payload(cache_key: str, xyz_text: str, max_count: int) -> dict:
    """Calcul des Ring Bond Orders d'une molecule.

    Cle de cache = (rel_path, xyz_text, max_count). Si la molecule est
    radicalaire, available=False avec une raison textuelle. Sinon on renvoie
    les bond_orders par arete et le CBO par cycle.
    """
    mol = build_mol_graph_from_text(xyz_text)
    if not mol.atoms:
        return {"error": "empty or unreadable xyz"}

    result = compute_rbo(mol, max_count=max_count)

    return {
        "available": bool(result.available),
        "bond_orders": [float(b) for b in result.bond_orders],
        "cycles": [
            {
                "size": c.size,
                "atoms": [int(i) for i in c.atoms],
                "cbo": float(result.cbo[i]) if result.available else None,
                "cbo_max": int(result.cbo_max[i]) if result.available else None,
            }
            for i, c in enumerate(mol.cycles)
        ],
        "meta": {
            "n_kekule": int(result.n_kekule),
            "is_exact": bool(result.is_exact),
            "n_radicals": int(result.n_radicals),
            "max_requested": int(max_count),
            "reason": result.reason,
            "source": cache_key,
        },
    }


def init_app(app, resolve_path_fn, load_xyz_text_fn):
    """Branche le blueprint sur l'app Flask.

    Args:
      app                : Flask app
      resolve_path_fn    : `(rel_path: str) -> Path | None` du serveur
                           principal (rewriting cluster<->local). Conserve
                           pour compatibilite ; plus utilise directement ici.
      load_xyz_text_fn   : `(rel_path: str) -> str | None`. Resout en cherchant
                           d'abord sur le filesystem, puis en DB (table
                           xyz_files, contenu gzippe). Centralisee dans
                           server.py pour partager le meme comportement avec
                           la route /file.
    """
    def _resolve_xyz_key_and_text():
        """Extrait le param 'path', verifie suffix .xyz, charge le contenu
        (fs ou DB). Retourne (cache_key, xyz_text). cache_key = chemin
        relatif normalise (forward slashes), identique a la cle DB.
        Abort 4xx si invalide.
        """
        rel = request.args.get("path", "")
        if not rel:
            abort(400, description="missing 'path' parameter")
        cache_key = rel.replace("\\", "/").lstrip("/")
        if not cache_key.lower().endswith(".xyz"):
            abort(403, description="only .xyz supported")
        text = load_xyz_text_fn(cache_key)
        if text is None:
            abort(404)
        return cache_key, text

    def _parse_max(default: int, hard_cap: int) -> int:
        """Parse le param 'max' (entier, defaut + plafonnement dur).
        Abort 400 si non-entier. Borne le resultat dans [1, hard_cap].
        """
        try:
            n = int(request.args.get("max", default))
        except ValueError:
            abort(400, description="'max' must be an integer")
        return max(1, min(n, hard_cap))

    @bp.route("/api/mol3d")
    def api_mol3d():
        cache_key, text = _resolve_xyz_key_and_text()
        return jsonify(_compute_mol3d(cache_key, text))

    @bp.route("/api/kekule_list")
    def api_kekule_list():
        cache_key, text = _resolve_xyz_key_and_text()
        max_count = _parse_max(default=200, hard_cap=1000)
        return jsonify(_compute_kekule_list(cache_key, text, max_count))

    @bp.route("/api/clar_list")
    def api_clar_list():
        cache_key, text = _resolve_xyz_key_and_text()
        max_count = _parse_max(default=200, hard_cap=1000)
        return jsonify(_compute_clar_list(cache_key, text, max_count))

    @bp.route("/api/rbo")
    def api_rbo():
        cache_key, text = _resolve_xyz_key_and_text()
        max_count = _parse_max(default=DEFAULT_MAX_KEKULE,
                                hard_cap=DEFAULT_MAX_KEKULE)
        return jsonify(_compute_rbo_payload(cache_key, text, max_count))

    app.register_blueprint(bp)
