"""
Script d'execution batch du solveur CSP sur un ensemble de fichiers .graph.

Usage :
    python batch_run.py <dossier_ou_fichier> [--structural] [--solve] [--validate]
                                             [--no-freeze] [--timeout T]

Modes :
    --structural : extrait les proprietes structurelles
    --solve      : resout le CSP
    --validate   : reconstruit 3D + xTB, teste la planarite

Resultats :
    JSON par benzenoide dans results/benzdb/hN/ (ou results/<categorie>/)
    HTML genere automatiquement apres --solve ou --validate
"""

import sys
import csv
import json
import time
import argparse
from pathlib import Path

# Ajouter les chemins necessaires
EXPERIMENTS_ROOT = Path(__file__).parent
CSP_SOLVER_ROOT = EXPERIMENTS_ROOT.parent
sys.path.insert(0, str(CSP_SOLVER_ROOT))

from config import (
    STRUCTURAL_CSV, RESULTS_BENZDB_DIR, HTML_DIR,
    RESULTS_DIR, SOLUTIONS_DIR, CSP_TIMEOUT, PLANARITY_ANGLE_THRESHOLD
)


# ===== Utilitaires fichiers =====

def find_graph_files(path):
    """Trouve tous les .graph dans un chemin (fichier ou dossier recursif)."""
    p = Path(path)
    if not p.exists():
        p = EXPERIMENTS_ROOT / path
    if p.is_file() and p.suffix == '.graph':
        return [p]
    elif p.is_dir():
        return sorted(p.rglob("*.graph"))
    else:
        print(f"ERREUR: {path} n'est ni un fichier .graph ni un dossier")
        return []


def _result_json_path(graph_path):
    """Chemin du JSON de resultats pour un .graph.

    Conserve la hierarchie de dossiers source :
        benzenoids/benzdb/h4/foo.graph -> results/benzdb/h4/foo.json
    """
    gp = Path(graph_path).resolve()
    benz_dir = (EXPERIMENTS_ROOT / "benzenoids").resolve()

    try:
        rel = gp.relative_to(benz_dir)
        return RESULTS_DIR / rel.with_suffix(".json")
    except ValueError:
        # Fichier hors de benzenoids/ : mettre dans results/misc/
        return RESULTS_DIR / "misc" / (gp.stem + ".json")


def load_result_json(graph_path):
    """Charge le JSON de resultats existant pour un .graph."""
    jp = _result_json_path(graph_path)
    if not jp.exists():
        return None
    with open(jp, 'r') as f:
        return json.load(f)


def save_result_json(graph_path, data):
    """Sauvegarde le JSON de resultats pour un .graph."""
    jp = _result_json_path(graph_path)
    jp.parent.mkdir(parents=True, exist_ok=True)
    with open(jp, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_csv(filepath, rows, fieldnames=None):
    """Ajoute des lignes a un CSV."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_header = not filepath.exists() or filepath.stat().st_size == 0
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(filepath, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ===== Phases =====

def extract_structural(graph_path):
    """Extrait les proprietes structurelles d'un .graph."""
    from utils.parser import parse

    try:
        graph = parse(str(graph_path))
    except Exception as e:
        print(f"  ERREUR parse {graph_path}: {e}")
        return None

    h = graph.h
    degrees = [graph.degree(v) for v in range(h)]
    n_internal = sum(1 for d in degrees if d == 6)
    n_frozen = sum(1 for v in range(h) if graph.is_frozen(v, freeze_b2=True))

    import networkx as nx
    if h > 1 and nx.is_connected(graph.dual):
        diameter = nx.diameter(graph.dual)
    else:
        diameter = 0

    return {
        "file": str(graph_path),
        "category": graph_path.parent.name,
        "h": h,
        "n_vertices": len(graph.vertices),
        "n_edges": len(graph.edges),
        "n_dual_edges": graph.dual.number_of_edges(),
        "n_internal": n_internal,
        "n_boundary": h - n_internal,
        "n_frozen": n_frozen,
        "n_free": h - n_frozen,
        "frozen_ratio": round(n_frozen / h, 3) if h > 0 else 0,
        "diameter": diameter,
        "is_catacondensed": n_internal == 0,
    }


def solve_csp(graph_path, no_freeze=False, timeout=CSP_TIMEOUT):
    """Resout le CSP. Retourne (solutions, h, solve_time) ou (None, None, None)."""
    from utils.parser import parse
    from utils.preprocessing import preprocess
    from utils.model import build_and_solve

    try:
        graph = parse(str(graph_path))
        preprocessed = preprocess(graph, freeze_b2=not no_freeze)
        t0 = time.time()
        solutions = build_and_solve(graph, preprocessed, enumerate_all=True)
        solve_time = time.time() - t0
        return solutions if solutions else [], graph.h, round(solve_time, 3)
    except Exception as e:
        print(f"  ERREUR solve {graph_path}: {e}")
        return None, None, None


def validate_solutions(graph_path, solutions):
    """Valide les solutions avec xTB."""
    from utils.parser import parse
    from reconstruction import reconstruct_and_validate

    try:
        graph = parse(str(graph_path))
        return reconstruct_and_validate(graph, solutions)
    except Exception as e:
        print(f"  ERREUR validate {graph_path}: {e}")
        return []


# ===== Construction du JSON par benzenoide =====

def build_solution_entry(sol, h, val_result=None):
    """Construit le dict d'une solution pour le JSON."""
    sizes = [sol[v] for v in range(h)]
    n_5, n_6, n_7 = sizes.count(5), sizes.count(6), sizes.count(7)

    entry = {
        "tailles": sizes,
        "nb_pentagones": n_5,
        "nb_hexagones": n_6,
        "nb_heptagones": n_7,
        "est_original": (n_5 == 0 and n_7 == 0),
    }

    if val_result:
        entry["validation"] = {
            "est_planaire": val_result.get("planar", False),
            "angle_max_deg": round(val_result.get("angle_deg", -1), 2),
            "rmsd_plan": round(val_result.get("rmsd", -1), 4),
            "hauteur": round(val_result.get("height", -1), 4),
        }

    return entry


# ===== Main =====

def main():
    parser = argparse.ArgumentParser(description="Batch CSP runner")
    parser.add_argument("path", help="Fichier .graph ou dossier")
    parser.add_argument("--structural", action="store_true",
                        help="Extraire proprietes structurelles")
    parser.add_argument("--solve", action="store_true",
                        help="Resoudre le CSP")
    parser.add_argument("--validate", action="store_true",
                        help="Valider avec xTB")
    parser.add_argument("--no-freeze", action="store_true",
                        help="Desactiver contrainte b(v)>=2")
    parser.add_argument("--timeout", type=int, default=CSP_TIMEOUT,
                        help=f"Timeout ACE (defaut: {CSP_TIMEOUT}s)")

    args = parser.parse_args()

    if not (args.structural or args.solve or args.validate):
        print("ERREUR: specifier au moins --structural, --solve ou --validate")
        sys.exit(1)

    files = find_graph_files(args.path)
    if not files:
        print("Aucun fichier .graph trouve.")
        sys.exit(1)

    print(f"=== Batch run: {len(files)} fichier(s) ===\n")

    all_json_paths = []

    for i, gf in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {gf.name}")

        # Charger ou creer le JSON du benzenoide
        data = load_result_json(gf) or {
            "file": gf.name,
            "h": None,
        }

        # Phase A : structural
        if args.structural:
            props = extract_structural(gf)
            if props:
                data["structural"] = props
                data["h"] = props["h"]
                append_csv(STRUCTURAL_CSV, [props])
                print(f"  structural: h={props['h']}, "
                      f"frozen={props['n_frozen']}/{props['h']}")

        # Phase B : solve
        solutions = None
        h = data.get("h")

        if args.solve:
            solutions, h, solve_time = solve_csp(
                gf, no_freeze=False, timeout=args.timeout)

            if solutions is not None:
                data["h"] = h
                data["solve"] = {
                    "freeze_mode": "freeze",
                    "nb_solutions": len(solutions),
                    "temps_s": solve_time,
                    "solutions": [
                        build_solution_entry(sol, h)
                        for sol in solutions
                    ],
                }
                # Stocker les solutions brutes pour validate
                data["_solutions_raw"] = [
                    {str(k): v for k, v in sol.items()}
                    for sol in solutions
                ]
                print(f"  solve: {len(solutions)} solutions en {solve_time}s")

            if args.no_freeze:
                sol_nf, h_nf, t_nf = solve_csp(
                    gf, no_freeze=True, timeout=args.timeout)
                if sol_nf is not None:
                    data["solve_no_freeze"] = {
                        "freeze_mode": "no-freeze",
                        "nb_solutions": len(sol_nf),
                        "temps_s": t_nf,
                        "solutions": [
                            build_solution_entry(sol, h_nf)
                            for sol in sol_nf
                        ],
                    }
                    print(f"  solve (no-freeze): {len(sol_nf)} solutions")

        # Phase C : validate
        if args.validate:
            # Recuperer les solutions depuis le JSON si pas de --solve
            if not solutions and data.get("_solutions_raw"):
                h = data["h"]
                solutions = [
                    {int(k): v for k, v in sol.items()}
                    for sol in data["_solutions_raw"]
                ]
                print(f"  {len(solutions)} solution(s) chargee(s)")
            elif not solutions:
                print(f"  Pas de solutions pour {gf.name}, "
                      f"lancer --solve d'abord")

            if solutions:
                val_results = validate_solutions(gf, solutions)
                if val_results:
                    n_planar = sum(1 for vr in val_results
                                   if vr.get("planar", False))
                    print(f"  validate: {n_planar}/{len(val_results)} "
                          f"planes")

                    # Mettre a jour les solutions avec la validation
                    sol_entries = []
                    for idx, sol in enumerate(solutions):
                        vr = val_results[idx] if idx < len(val_results) \
                            else None
                        sol_entries.append(
                            build_solution_entry(sol, h, vr))

                    data["solve"]["solutions"] = sol_entries
                    data["solve"]["nb_planaires"] = n_planar
                    data["solve"]["nb_non_planaires"] = \
                        len(solutions) - n_planar

        # Sauvegarder le JSON
        save_result_json(gf, data)
        all_json_paths.append(_result_json_path(gf))

    # Generer le HTML
    if args.solve or args.validate:
        try:
            from viewer import generate_html
            # Determiner le nom du rapport
            first_file = files[0]
            category = first_file.parent.name  # ex: "h4"
            html_path = HTML_DIR / f"rapport_{category}.html"
            generate_html(all_json_paths, html_path)
            print(f"  -> {html_path}")
        except ImportError:
            print("  (viewer.py non trouve, HTML non genere)")

    print(f"\n=== Termine ===")
    for jp in all_json_paths[:3]:
        print(f"  -> {jp}")
    if len(all_json_paths) > 3:
        print(f"  ... et {len(all_json_paths) - 3} autres")


if __name__ == "__main__":
    main()
