"""Entry point experiments_v3 : CSP enrichi (Gauss-Bonnet local + contraintes
v2) + pipeline MMFF 3-tier + xTB conditionnel.

USAGE
=====
    python -m csp_solver.experiments_v3.main file.graph \\
        [--config NAME] [--sym K] [--pb K] [--hb K] [--tot K] \\
        [--tau-gb K] [--radius-gb R] \\
        [--adj-57] [--no-table] [--no-freeze] \\
        [--count] [--count-hexagon] [--all] \\
        [--validate] [--method md] \\
        [--th-sure-plan F] [--th-sure-non-plan F] [--threshold-xtb F] \\
        [--output-dir DIR] [--ace-timeout SEC]

CONFIGS preset (cf experiments_v3/configs.py) :
    baseline_v3, curv0, curv1, sym1_curv1, pb2_curv1,
    sym1_pb2_curv1 (recommande), all_strict_curv0

Drapeaux explicites (--sym K, --tau-gb K, ...) ecrasent ceux d'un preset.

DIFFERENCE V2 -> V3
===================
- Nouvelle contrainte CSP "tau_gb" : Gauss-Bonnet local
- Nouveau pipeline : MMFF avant xTB pour filtrer 3-tier
"""

import sys
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
def _float(s):
    if s is None: return None
    try: return float(s)
    except (TypeError, ValueError): return None


def _parse_args():
    args = {
        "filepath": _own_argv[1] if len(_own_argv) >= 2 else None,
        "config": _kw("--config"),
        "K_sym": _int(_kw("--sym")),
        "K_pb": _int(_kw("--pb")),
        "K_hb": _int(_kw("--hb")),
        "K_tot": _int(_kw("--tot")),
        "tau_gb": _int(_kw("--tau-gb")),
        "radius_gb": _int(_kw("--radius-gb")),
        "adj_57": _flag("--adj-57"),
        "no_table": _flag("--no-table"),
        "no_freeze": _flag("--no-freeze"),
        "count_only": _flag("--count"),
        "count_hexagon": _flag("--count-hexagon"),
        "enumerate_all": _flag("--all") or not _flag("--count"),
        "do_validate": _flag("--validate"),
        "th_sure_plan": _float(_kw("--th-sure-plan")),
        "th_sure_non_plan": _float(_kw("--th-sure-non-plan")),
        "threshold_xtb": _float(_kw("--threshold-xtb")),
        "method": _kw("--method") or "md",
        "md_deterministic": "--md-no-deterministic" not in _own_argv,
        "output_dir": _kw("--output-dir"),
        "ace_timeout": _int(_kw("--ace-timeout")) or 60,
    }
    if args["config"]:
        _root = Path(__file__).resolve().parents[2]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from csp_solver.experiments_v3 import configs as _configs
        try:
            preset = _configs.get(args["config"])
        except KeyError:
            print(f"ERREUR : config inconnue '{args['config']}'. "
                  f"Disponibles : {_configs.all_names()}", file=sys.stderr)
            sys.exit(1)
        for k, v in preset.items():
            if args.get(k) is None:
                args[k] = v
    # defauts pour les seuils MMFF/xTB
    if args["th_sure_plan"] is None: args["th_sure_plan"] = 5.0
    if args["th_sure_non_plan"] is None: args["th_sure_non_plan"] = 25.0
    if args["threshold_xtb"] is None: args["threshold_xtb"] = 10.0
    if args["radius_gb"] is None: args["radius_gb"] = 2
    return args


def main():
    args = _parse_args()
    if args["filepath"] is None:
        print(__doc__)
        sys.exit(1)

    # Nettoyer sys.argv pour pycsp3
    sys.argv = [_own_argv[0]]

    _csp_root = Path(__file__).resolve().parents[1]
    if str(_csp_root) not in sys.path:
        sys.path.insert(0, str(_csp_root))

    from utils.parser import parse  # noqa: E402
    from utils.preprocessing import preprocess  # noqa: E402
    from csp_solver.experiments_v3.csp_model import build_and_solve_v3  # noqa: E402

    print(f"=== experiments_v3 : {args['filepath']} ===")
    config_name = args["config"] or "(custom)"
    print(f"  config={config_name}  sym={args['K_sym']} pb={args['K_pb']} "
          f"hb={args['K_hb']} tot={args['K_tot']}  "
          f"tau_gb={args['tau_gb']}(r={args['radius_gb']})")

    print(f"=== Lecture de {args['filepath']} ===")
    graph = parse(args["filepath"])
    print(graph.summary())
    print()

    print("=== Pre-traitement ===")
    preprocessed = preprocess(graph, freeze_b2=not args["no_freeze"])
    if args["no_freeze"]:
        print("  (contrainte b(v)>=2 DESACTIVEE)")

    print()
    print("=== Resolution CSP (v3) ===")
    if args["adj_57"]: print("  C5 (adjacence 5-7) : ACTIVEE")
    if args["no_table"]: print("  C3 (table voisinage) : DESACTIVEE")
    if args["count_hexagon"]: print("  Solution tout-hexagones : INCLUSE")

    solutions = build_and_solve_v3(
        graph, preprocessed,
        enumerate_all=args["enumerate_all"],
        adj_57=args["adj_57"],
        no_table=args["no_table"],
        count_hexagon=args["count_hexagon"],
        K_sym=args["K_sym"], K_pb=args["K_pb"],
        K_hb=args["K_hb"], K_tot=args["K_tot"],
        tau_gb=args["tau_gb"], radius_gb=args["radius_gb"],
        ace_timeout=args["ace_timeout"],
    )

    if not solutions:
        print("Aucune solution trouvee.")
        return

    print(f"Nombre de solutions: {len(solutions)}")
    if not args["count_only"]:
        print()
        print("=== Solutions (extrait) ===")
        for i, sol in enumerate(solutions[:20], 1):
            line = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
            print(f"  solution {i}: {line}")
        if len(solutions) > 20:
            print(f"  ... ({len(solutions) - 20} autres)")

    # Validation pipeline v3 : MMFF 3-tier + xTB conditionnel
    if args["do_validate"]:
        print()
        print("=== Pipeline v3 : MMFF 3-tier + xTB conditionnel ===")
        from csp_solver.experiments_v3.v3_pipeline import (
            reconstruct_filter_validate_v3
        )
        output_dir = args["output_dir"] or "output_v3"
        reconstruct_filter_validate_v3(
            graph, solutions,
            output_dir=output_dir,
            th_sure_plan=args["th_sure_plan"],
            th_sure_non_plan=args["th_sure_non_plan"],
            threshold_xtb=args["threshold_xtb"],
            md_deterministic=args["md_deterministic"],
        )


if __name__ == "__main__":
    main()
