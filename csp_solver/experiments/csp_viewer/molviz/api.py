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

from .bonds import build_mol_graph
from .kekule import assign_kekule


_HERE = Path(__file__).resolve().parent
bp = Blueprint(
    "molviz", __name__,
    static_folder=str(_HERE / "static"),
    static_url_path="/molviz_static",
)


@lru_cache(maxsize=256)
def _compute_mol3d(xyz_path_str: str) -> dict:
    """Calcul lourd : lecture XYZ + bonds + Kekule + cycles.
    Cle de cache = chemin absolu du fichier.
    """
    p = Path(xyz_path_str)
    mol = build_mol_graph(p)
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
            "source": str(p),
        },
    }


def init_app(app, resolve_path_fn):
    """Branche le blueprint sur l'app Flask.

    Args:
      app             : Flask app
      resolve_path_fn : fonction `(rel_path: str) -> Path | None` du serveur
                        principal (deja gere le rewriting cluster<->local).
    """
    @bp.route("/api/mol3d")
    def api_mol3d():
        rel = request.args.get("path", "")
        if not rel:
            abort(400, description="missing 'path' parameter")
        target = resolve_path_fn(rel)
        if target is None:
            abort(404)
        if target.suffix.lower() not in (".xyz",):
            abort(403, description="only .xyz supported")
        return jsonify(_compute_mol3d(str(target.resolve())))

    app.register_blueprint(bp)
