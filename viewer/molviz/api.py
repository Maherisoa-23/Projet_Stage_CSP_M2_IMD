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

import io
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file, send_from_directory

from .bonds import build_mol_graph_from_text
from .clar import enumerate_clar_covers
from .dual import build_dual, parse_sizes_from_name
from .kekule import assign_kekule, enumerate_kekule
from .rbo import compute_rbo, DEFAULT_MAX_KEKULE


_HERE = Path(__file__).resolve().parent
bp = Blueprint(
    "molviz", __name__,
    static_folder=str(_HERE / "static"),
    static_url_path="/molviz_static",
)


# Segment de chemin d'une solution designer : "sol_13_6_7_6_5_5_7".
# Capture les tailles de cycles attendues (ici [6,7,6,5,5,7]).
_SOL_SIZES_RE = re.compile(r"/sol_?\d+_((?:\d+_)*\d+)/")


def _detect_unclosed_ring(cache_key: str, mol) -> bool:
    """Detecte une geometrie skip CASSEE (a signaler dans le viewer).

    Le mode skip reconstruit une geometrie rigide (placement BFS sans
    relaxation xTB). A l'interface 5/7, la deformation produit deux types
    d'artefacts :
      a) un cycle non ferme  -> atome de degre 1 + cycle manquant (faux radical
         "flottant" dans le viewer) ;
      b) un cycle mal dimensionne -> un 5 ou un 7 deforme est detecte comme un
         hexagone (ou autre), parce que les distances ne correspondent plus a
         la taille reelle du cycle.

    On detecte les DEUX en comparant le MULTISET des tailles de cycles
    detectees au multiset ATTENDU (lu depuis le nom de dossier
    sol_<idx>_<s1>_<s2>...). Tout ecart = geometrie skip non fiable.

    Conditions (toutes requises) :
      1. Geometrie skip (chemin se terminant par source.xyz).
      2. Tailles attendues lisibles depuis le nom de dossier.
      3. Le multiset des tailles detectees DIFFERE du multiset attendu.

    En geometrie xTB (md_final_opt.xyz) on ne signale jamais : la relaxation
    retablit les vraies tailles 5/7, et les rares atomes degre-1 restants sont
    de vrais carbones terminaux.
    """
    from collections import Counter

    if not cache_key.endswith("source.xyz"):
        return False
    m = _SOL_SIZES_RE.search("/" + cache_key.replace("\\", "/") + "/")
    if not m:
        return False
    try:
        expected_sizes = Counter(int(s) for s in m.group(1).split("_"))
    except (AttributeError, ValueError):
        return False
    detected_sizes = Counter(c.size for c in mol.cycles)
    return detected_sizes != expected_sizes


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
    unclosed_ring = _detect_unclosed_ring(cache_key, mol)
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
            "unclosed_ring": bool(unclosed_ring),
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

    Retourne DEUX modes :
      - clar    : Option A (hex uniquement, Huckel n=1 neutre) -- compatibilite
      - clar_b  : Option B (hex + pent-anion + hept-cation, Huckel 4n+2 generalise)
                  Chaque cover de clar_b inclut sextet_sizes + n_hex/pent/hept
                  pour annoter visuellement les sextets non-hexagonaux dans
                  le viewer.

    Cle de cache = (rel_path, xyz_text, max_count).
    """
    mol = build_mol_graph_from_text(xyz_text)
    if not mol.atoms:
        return {"error": "empty or unreadable xyz"}

    covers_a, is_exact_a = enumerate_clar_covers(mol, max_count=max_count,
                                                 include_huckel_4n2=False)
    covers_b, is_exact_b = enumerate_clar_covers(mol, max_count=max_count,
                                                 include_huckel_4n2=True)
    clar_number_a = covers_a[0].n_sextets if covers_a else 0
    clar_number_b = covers_b[0].n_sextets if covers_b else 0

    def _serialize(c, with_breakdown):
        d = {
            "sextets": [int(s) for s in c.sextets],
            "bond_orders": [int(o) for o in c.bond_orders],
            "radicals": sorted(int(i) for i in c.radicals),
            "n_sextets": int(c.n_sextets),
        }
        if with_breakdown:
            d["sextet_sizes"] = [int(s) for s in c.sextet_sizes]
            d["n_hex"] = int(c.n_hex_sextets)
            d["n_pent_anion"] = int(c.n_pent_sextets)
            d["n_hept_cation"] = int(c.n_hept_sextets)
        return d

    return {
        # Option A (compat existing frontend)
        "clar": [_serialize(c, with_breakdown=False) for c in covers_a],
        # Option B (nouveau : sextets 5/6/7 avec annotation)
        "clar_b": [_serialize(c, with_breakdown=True) for c in covers_b],
        "meta": {
            "returned": len(covers_a),
            "returned_b": len(covers_b),
            "is_exact": bool(is_exact_a),
            "is_exact_b": bool(is_exact_b),
            "has_more": not is_exact_a,
            "max_requested": int(max_count),
            # Option A (compat existing)
            "clar_number": int(clar_number_a),
            # Annotations explicites Option A vs B
            "clar_number_a": int(clar_number_a),
            "clar_number_b": int(clar_number_b),
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


def init_app(app, resolve_path_fn, load_xyz_text_fn, load_graph_text_fn=None):
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
      load_graph_text_fn : `(rel_path: str) -> str | None`. Charge le .graph
                           DIMACS de la solution designer (pour /api/dual).
                           Optionnel : si None, /api/dual renvoie un dual vide.
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

    def _xyz_download_name(rel_path: str) -> str:
        """Derive un nom de fichier .xyz lisible depuis un chemin relatif.

        Le chemin type est ".../designer_jobs/<job>/sol_3_5_6_7/source.xyz"
        (peu parlant si on garde juste "source.xyz" ou "md_final_opt.xyz").
        On prefixe par le nom du dossier de solution (sol_3_5_6_7) quand il
        est disponible, sinon on retombe sur le nom du fichier seul.
        """
        p = Path(rel_path.replace("\\", "/"))
        stem = p.stem  # "source" ou "md_final_opt"
        parent_name = p.parent.name  # ex. "sol_3_5_6_7", ou "" si racine
        if parent_name and parent_name.lower() not in ("", "."):
            return f"{parent_name}_{stem}.xyz"
        return p.name

    @bp.route("/api/xyz_export")
    def api_xyz_export():
        """Exporte un ou plusieurs .xyz : telechargement direct si un seul
        chemin, sinon un .zip construit en memoire.

        Query params :
          path     : chemin relatif d'un .xyz. Repetable (?path=a&path=b).
          filename : nom du zip a produire (optionnel, sinon "export.zip").

        Reutilise load_xyz_text_fn (meme resolution fs/DB que /api/mol3d),
        donc aucun acces filesystem direct ici -- la validation de chemin
        (suffixe .xyz, existence) est deleguee au meme point que le reste
        du module.
        """
        rels = request.args.getlist("path")
        if not rels:
            abort(400, description="missing 'path' parameter (repeatable)")
        if len(rels) > 500:
            abort(400, description="too many paths (max 500)")

        entries = []  # [(download_name, xyz_text)]
        for rel in rels:
            cache_key = rel.replace("\\", "/").lstrip("/")
            if not cache_key.lower().endswith(".xyz"):
                continue  # ignore silencieusement les paths invalides du lot
            text = load_xyz_text_fn(cache_key)
            if text is None:
                continue  # idem pour les fichiers introuvables
            entries.append((_xyz_download_name(cache_key), text))

        if not entries:
            abort(404, description="no exportable .xyz found for given paths")

        if len(entries) == 1:
            name, text = entries[0]
            buf = io.BytesIO(text.encode("utf-8"))
            return send_file(buf, mimetype="chemical/x-xyz",
                             as_attachment=True, download_name=name)

        # Plusieurs fichiers : zip en memoire. Deduplique les noms (au cas
        # ou deux chemins differents produiraient le meme download_name).
        zip_buf = io.BytesIO()
        seen_names = {}
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, text in entries:
                if name in seen_names:
                    seen_names[name] += 1
                    stem = name[:-4] if name.lower().endswith(".xyz") else name
                    name = f"{stem}_{seen_names[name]}.xyz"
                else:
                    seen_names[name] = 0
                zf.writestr(name, text)
        zip_buf.seek(0)

        zip_name = request.args.get("filename") or "export.zip"
        if not zip_name.lower().endswith(".zip"):
            zip_name += ".zip"
        return send_file(zip_buf, mimetype="application/zip",
                         as_attachment=True, download_name=zip_name)

    @bp.route("/api/dual")
    def api_dual():
        """Graphe dual (vue topologique 2D) d'une solution designer.

        Renvoie {available, nodes, edges, sizes_expected} ou {available:False}
        si le .graph n'est pas accessible (solution non-designer, ou callback
        load_graph_text_fn absent).
        """
        rel = request.args.get("path", "")
        if not rel:
            abort(400, description="missing 'path' parameter")
        cache_key = rel.replace("\\", "/").lstrip("/")
        sizes = parse_sizes_from_name(cache_key)
        if load_graph_text_fn is None:
            return jsonify({"available": False,
                            "reason": "graph loader indisponible"})
        graph_text = load_graph_text_fn(cache_key)
        if not graph_text:
            return jsonify({"available": False,
                            "reason": "graphe d'entree introuvable"})
        dual = build_dual(graph_text, sizes or [])
        if dual is None:
            return jsonify({"available": False,
                            "reason": "dual non constructible"})
        return jsonify({
            "available": True,
            "nodes": dual["nodes"],
            "edges": dual["edges"],
            "sizes_expected": sizes,
        })

    app.register_blueprint(bp)
