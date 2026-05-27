"""
Entry point experiments_v2 : CSP enrichi + drapeaux des nouvelles
contraintes. Reprend la structure de csp_solver/main.py, mais utilise
csp_model.build_and_solve_v2 pour pouvoir ajouter les contraintes
optionnelles --sym / --pb / --hb / --tot ou un --config preset.

USAGE
=====
    python -m experiments.v2.main file.graph \\
        [--config NAME] [--sym K] [--pb K] [--hb K] [--tot K] \\
        [--adj-57] [--no-table] [--no-freeze] \\
        [--count] [--count-hexagon] [--all] \\
        [--validate] [--n-runs N] [--method M] [--md-no-deterministic] \\
        [--output-dir DIR] [--ace-timeout SEC]

CONFIGS preset (voir experiments_v2/configs.py) :
    baseline_v2, sym1, pb2, sym1_pb2, all_strict

Drapeaux explicites (--sym K ...) ecrasent ceux d'un preset si presents.
"""

import sys
import os
from pathlib import Path

# Sauvegarder argv avant pycsp3
_own_argv = sys.argv[:]


def _flag(name): return name in _own_argv
def _kw(name):
    if name not in _own_argv: return None
    idx = _own_argv.index(name)
    return _own_argv[idx + 1] if idx + 1 < len(_own_argv) else None
def _int(s):
    if s is None: return None
    try: return int(s)
    except (TypeError, ValueError): return None


def _parse_args():
    args = {
        "filepath": _own_argv[1] if len(_own_argv) >= 2 else None,
        "config": _kw("--config"),
        "K_sym": _int(_kw("--sym")),
        "K_pb": _int(_kw("--pb")),
        "K_hb": _int(_kw("--hb")),
        "K_tot": _int(_kw("--tot")),
        "adj_57": _flag("--adj-57"),
        "no_table": _flag("--no-table"),
        "no_freeze": _flag("--no-freeze"),
        "count_only": _flag("--count"),
        "count_hexagon": _flag("--count-hexagon"),
        "enumerate_all": _flag("--all") or not _flag("--count"),
        "do_validate": _flag("--validate"),
        "n_runs": _int(_kw("--n-runs")) or 1,
        "method": _kw("--method") or "md",
        "md_deterministic": "--md-no-deterministic" not in _own_argv,
        "output_dir": _kw("--output-dir"),
        "ace_timeout": _int(_kw("--ace-timeout")) or 60,
    }
    if args["config"]:
        # Late import (apres path setup)
        _root = Path(__file__).resolve().parents[2]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from experiments.v2 import configs as _configs
        try:
            preset = _configs.get(args["config"])
        except KeyError:
            print(f"ERREUR : config inconnue '{args['config']}'. "
                  f"Disponibles : {_configs.all_names()}", file=sys.stderr)
            sys.exit(1)
        for k, v in preset.items():
            if args[k] is None:
                args[k] = v
    return args


def main():
    args = _parse_args()
    if args["filepath"] is None:
        print(__doc__)
        sys.exit(1)

    # Nettoyer sys.argv pour pycsp3
    sys.argv = [_own_argv[0]]

    # Path setup : on a besoin d'utils.* (utils.parser, utils.preprocessing,
    # reconstruction.*) qui sont dans csp_solver/. On ajoute csp_solver/ au path.
    # __file__ = experiments/v2/main.py ; parents[2] = racine projet
    _project_root = Path(__file__).resolve().parents[2]
    _csp_root = _project_root / "csp_solver"
    if str(_csp_root) not in sys.path:
        sys.path.insert(0, str(_csp_root))

    from utils.parser import parse  # noqa: E402
    from utils.preprocessing import preprocess  # noqa: E402
    from experiments.v2.csp_model import build_and_solve_v2  # noqa: E402

    print(f"=== experiments_v2 : {args['filepath']} ===")
    config_name = args["config"] or "(custom)"
    print(f"   config={config_name}  sym={args['K_sym']} "
          f"pb={args['K_pb']} hb={args['K_hb']} tot={args['K_tot']}")

    print(f"=== Lecture de {args['filepath']} ===")
    graph = parse(args["filepath"])
    print(graph.summary())
    print()

    print("=== Pre-traitement ===")
    preprocessed = preprocess(graph, freeze_b2=not args["no_freeze"])
    if args["no_freeze"]:
        print("  (contrainte b(v)>=2 DESACTIVEE)")

    print()
    print("=== Resolution CSP (v2) ===")
    if args["adj_57"]: print("  C5 (adjacence 5-7) : ACTIVEE")
    if args["no_table"]: print("  C3 (table voisinage) : DESACTIVEE")
    if args["count_hexagon"]: print("  Solution tout-hexagones : INCLUSE")

    solutions = build_and_solve_v2(
        graph, preprocessed,
        enumerate_all=args["enumerate_all"],
        adj_57=args["adj_57"],
        no_table=args["no_table"],
        count_hexagon=args["count_hexagon"],
        K_sym=args["K_sym"], K_pb=args["K_pb"],
        K_hb=args["K_hb"], K_tot=args["K_tot"],
        ace_timeout=args["ace_timeout"],
    )

    if not solutions:
        print("Aucune solution trouvee.")
        return

    print(f"Nombre de solutions: {len(solutions)}")
    if not args["count_only"]:
        print()
        print("=== Solutions ===")
        for i, sol in enumerate(solutions[:20], 1):
            line = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
            print(f"  solution {i}: {line}")
        if len(solutions) > 20:
            print(f"  ... ({len(solutions) - 20} autres)")
        print()
        # Repartition
        counts = {5: 0, 6: 0, 7: 0}
        for sol in solutions:
            for v, sz in sol.items():
                counts[sz] += 1
        total = len(solutions) * graph.h
        print("Repartition des tailles :")
        for sz in (5, 6, 7):
            pct = 100 * counts[sz] / total if total > 0 else 0
            print(f"  Taille {sz}: {counts[sz]} ({pct:.1f}%)")

    # Validation MD (deleguee a reconstruction/)
    if args["do_validate"]:
        print()
        print("=== Validation xTB + planarite ===")
        from reconstruction import reconstruct_and_validate  # noqa: E402
        reconstruct_and_validate(graph, solutions,
                                  output_dir=args["output_dir"],
                                  n_runs=args["n_runs"],
                                  method=args["method"],
                                  md_deterministic=args["md_deterministic"])


if __name__ == "__main__":
    main()
