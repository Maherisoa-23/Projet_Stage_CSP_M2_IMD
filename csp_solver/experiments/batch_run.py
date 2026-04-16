"""
Script d'execution batch du solveur CSP sur un ensemble de fichiers .graph.

Usage :
    python batch_run.py <dossier_ou_fichier> [--structural] [--solve] [--validate]
                                             [--no-freeze] [--timeout T]

Modes :
    --structural : extrait les proprietes structurelles (pas de CSP)
    --solve      : resout le CSP (avec et sans --no-freeze)
    --validate   : reconstruit 3D + xTB pour chaque solution

Les resultats sont ecrits dans results/structural.csv, csp_results.csv, validation.csv.
"""

import sys
import csv
import time
import argparse
from pathlib import Path

# Ajouter les chemins necessaires
EXPERIMENTS_ROOT = Path(__file__).parent
CSP_SOLVER_ROOT = EXPERIMENTS_ROOT.parent
sys.path.insert(0, str(CSP_SOLVER_ROOT))

from config import (
    STRUCTURAL_CSV, CSP_RESULTS_CSV, VALIDATION_CSV,
    RESULTS_DIR, LOGS_DIR, CSP_TIMEOUT
)


def find_graph_files(path):
    """Trouve tous les .graph dans un chemin (fichier ou dossier recursif)."""
    p = Path(path)
    if p.is_file() and p.suffix == '.graph':
        return [p]
    elif p.is_dir():
        return sorted(p.rglob("*.graph"))
    else:
        print(f"ERREUR: {path} n'est ni un fichier .graph ni un dossier")
        return []


def extract_structural(graph_path):
    """
    Extrait les proprietes structurelles d'un .graph (pas de CSP).
    Retourne un dict ou None en cas d'erreur.
    """
    from utils.parser import parse, count_zero_blocks

    try:
        graph = parse(str(graph_path))
    except Exception as e:
        print(f"  ERREUR parse {graph_path}: {e}")
        return None

    h = graph.h
    n_vertices = len(graph.vertices)
    n_edges = len(graph.edges)
    n_dual_edges = graph.dual.number_of_edges()

    degrees = [graph.degree(v) for v in range(h)]
    patterns = [graph.patterns[v] for v in range(h)]
    b_values = [count_zero_blocks(p) for p in patterns]

    n_internal = sum(1 for d in degrees if d == 6)
    n_frozen = sum(1 for v in range(h) if graph.is_frozen(v, freeze_b2=True))
    n_free = h - n_frozen

    # Diametre du graphe dual
    import networkx as nx
    if h > 1 and nx.is_connected(graph.dual):
        diameter = nx.diameter(graph.dual)
    else:
        diameter = 0

    # Catacondense ? (pas de triplet d'hexagones 2 a 2 adjacents)
    is_catacondensed = n_internal == 0

    return {
        "file": str(graph_path),
        "category": graph_path.parent.name,
        "h": h,
        "n_vertices": n_vertices,
        "n_edges": n_edges,
        "n_dual_edges": n_dual_edges,
        "max_degree": max(degrees) if degrees else 0,
        "min_degree": min(degrees) if degrees else 0,
        "avg_degree": sum(degrees) / len(degrees) if degrees else 0,
        "n_internal": n_internal,
        "n_boundary": h - n_internal,
        "n_frozen": n_frozen,
        "n_free": n_free,
        "frozen_ratio": n_frozen / h if h > 0 else 0,
        "diameter": diameter,
        "is_catacondensed": is_catacondensed,
    }


def solve_csp(graph_path, no_freeze=False, timeout=CSP_TIMEOUT):
    """
    Resout le CSP pour un .graph. Retourne un dict ou None.
    """
    from utils.parser import parse
    from utils.preprocessing import preprocess
    from utils.model import build_and_solve

    try:
        graph = parse(str(graph_path))
        preprocessed = preprocess(graph, freeze_b2=not no_freeze)

        t0 = time.time()
        solutions = build_and_solve(graph, preprocessed, enumerate_all=True)
        solve_time = time.time() - t0

        # Distribution des tailles
        counts = {5: 0, 6: 0, 7: 0}
        if solutions:
            for sol in solutions:
                for v, size in sol.items():
                    counts[size] += 1

        total_assignments = len(solutions) * graph.h if solutions else 0

        return {
            "file": str(graph_path),
            "h": graph.h,
            "n_solutions": len(solutions) if solutions else 0,
            "solve_time": round(solve_time, 3),
            "freeze_mode": "no-freeze" if no_freeze else "freeze",
            "pct_5": round(100 * counts[5] / total_assignments, 1) if total_assignments else 0,
            "pct_6": round(100 * counts[6] / total_assignments, 1) if total_assignments else 0,
            "pct_7": round(100 * counts[7] / total_assignments, 1) if total_assignments else 0,
            "solutions": solutions,  # pour validation
        }
    except Exception as e:
        print(f"  ERREUR solve {graph_path}: {e}")
        return None


def validate_solutions(graph_path, solutions):
    """
    Valide les solutions avec xTB. Retourne une liste de dicts.
    """
    from utils.parser import parse
    from reconstruction import reconstruct_and_validate

    try:
        graph = parse(str(graph_path))
        results = reconstruct_and_validate(graph, solutions)
        return results
    except Exception as e:
        print(f"  ERREUR validate {graph_path}: {e}")
        return []


def append_csv(filepath, rows, fieldnames=None):
    """Ajoute des lignes a un CSV (cree le fichier + header si necessaire)."""
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

    print(f"=== Batch run: {len(files)} fichier(s) ===")
    print(f"  Modes: structural={args.structural} solve={args.solve} "
          f"validate={args.validate}")
    print()

    for i, gf in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {gf.name}")

        # Phase A : structural
        if args.structural:
            props = extract_structural(gf)
            if props:
                append_csv(STRUCTURAL_CSV, [props])
                print(f"  structural: h={props['h']}, "
                      f"frozen={props['n_frozen']}/{props['h']}, "
                      f"internal={props['n_internal']}")

        # Phase B : solve
        solutions = None
        if args.solve:
            result = solve_csp(gf, no_freeze=False, timeout=args.timeout)
            if result:
                solutions = result.pop("solutions", None)
                append_csv(CSP_RESULTS_CSV, [result])
                print(f"  solve (freeze): {result['n_solutions']} solutions "
                      f"en {result['solve_time']}s")

            if args.no_freeze:
                result_nf = solve_csp(gf, no_freeze=True, timeout=args.timeout)
                if result_nf:
                    result_nf.pop("solutions", None)
                    append_csv(CSP_RESULTS_CSV, [result_nf])
                    print(f"  solve (no-freeze): "
                          f"{result_nf['n_solutions']} solutions")

        # Phase C : validate
        if args.validate and solutions:
            val_results = validate_solutions(gf, solutions)
            if val_results:
                val_rows = []
                n_planar = 0
                for vr in val_results:
                    is_p = vr.get("planar", False)
                    if is_p:
                        n_planar += 1
                    val_rows.append({
                        "file": str(gf),
                        "solution_idx": vr.get("index", 0),
                        "is_planar": is_p,
                        "max_angle_deg": vr.get("angle_deg", -1),
                        "rmsd_plane": vr.get("rmsd", -1),
                        "height": vr.get("height", -1),
                    })
                append_csv(VALIDATION_CSV, val_rows)
                print(f"  validate: {n_planar}/{len(val_results)} planes")

    print(f"\n=== Termine ===")
    if args.structural:
        print(f"  → {STRUCTURAL_CSV}")
    if args.solve:
        print(f"  → {CSP_RESULTS_CSV}")
    if args.validate:
        print(f"  → {VALIDATION_CSV}")


if __name__ == "__main__":
    main()
