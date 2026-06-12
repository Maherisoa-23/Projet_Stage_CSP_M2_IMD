"""Enumeration CSP programmatique (pas de parsing stdout).

Wrappe les fonctions csp_solver.utils.* pour retourner directement la
liste de solutions Python. Utilise par le master du run final pour
peupler la DB sans passer par main.py + subprocess + parse.

Une solution = dict {v_idx: taille}, ou taille ∈ {5, 6, 7}.
"""

from pathlib import Path
import sys


def _ensure_imports():
    """csp_solver/utils est importable comme `utils.X`. Assure que
    csp_solver/ (le parent de final/) est dans sys.path."""
    here = Path(__file__).resolve().parent
    csp_solver_dir = here.parent
    if str(csp_solver_dir) not in sys.path:
        sys.path.insert(0, str(csp_solver_dir))


def enumerate_solutions(graph_path: str, config: dict) -> list:
    """Lance le CSP et retourne la liste de solutions trouvees.

    Args:
        graph_path : chemin vers le fichier .graph
        config     : dict de _final_configs (avec preset_name, K_*, adj_57, ...)

    Returns:
        Liste de dicts {v_idx: taille}. Liste vide si aucune solution.
    """
    _ensure_imports()
    from utils.parser import parse
    from utils.preprocessing import preprocess
    from utils.model import build_and_solve

    graph = parse(graph_path)
    preprocessed = preprocess(graph, freeze_b2=config.get("freeze_b2", False))

    solutions = build_and_solve(
        graph, preprocessed,
        enumerate_all=True,
        adj_57=config.get("adj_57", False),
        no_table=config.get("no_table", False),
        count_hexagon=False,
        K_sym=config.get("K_sym"),
        K_pb=config.get("K_pb"),
        K_hb=config.get("K_hb"),
        K_tot=config.get("K_tot"),
        tau_gb=config.get("tau_gb"),
        radius_gb=config.get("radius_gb", 2),
    )
    return solutions or []


def read_graph_content(graph_path: str) -> str:
    """Retourne le contenu brut du fichier .graph (pour stockage DB)."""
    with open(graph_path, encoding="utf-8") as f:
        return f.read()
