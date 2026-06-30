"""
Strategies de validation d'une solution CSP.

Chaque strategy implemente la meme interface (cf. base.ValidationStrategy)
mais avec une approche differente pour valider la planarite d'une molecule
reconstruite. Elles peuvent coexister dans le meme data.json (chaque solution
peut avoir 0, 1 ou 2 blocs de validation, un par strategy).

Strategies disponibles :
    - "multi-runs" : N optimisations xTB avec perturbations aleatoires en z,
      puis classification statistique (bloc data.json "runs"). Comportement
      historique. Implementation : multi_runs.MultiRunsStrategy.

    - "md" / "det-opt" : perturbation z analytique deterministe + xtb --opt,
      1 run par solution (bloc data.json "md_validation"). Les deux noms
      pointent vers la meme MDStrategy ; "det-opt" est le nom aligne sur le
      module xTB renomme (cf. csp_solver/xtb/det_opt.py), "md" reste pour
      retro-compat. Implementation : md.MDStrategy.

Usage :
    from utils.validation import get_strategy
    strategy = get_strategy("det-opt", threshold=10.0)
    results = strategy.validate_solutions(graph, solutions, output_dir)
"""

from utils.validation.base import ValidationStrategy
from utils.validation.multi_runs import MultiRunsStrategy
from utils.validation.md import MDStrategy

# Registry des strategies disponibles. Pour ajouter une methode, importer
# la classe et l'enregistrer ici.
#
# Note sur "det-opt" : le module xTB sous-jacent a ete renomme md -> det_opt
# en juin 2026 (la "MD" etait en realite une perturbation z analytique
# deterministe + opt, pas une vraie dynamique). Le designer expose desormais
# l'option "det-opt". On l'enregistre comme ALIAS de MDStrategy (meme code,
# meme bloc data.json 'md_validation') pour que le nouveau nom fonctionne sans
# casser la retro-compat de "md".
_STRATEGIES = {
    "multi-runs": MultiRunsStrategy,
    "md": MDStrategy,
    "det-opt": MDStrategy,
}


def list_strategies():
    """Retourne la liste des noms de strategies disponibles."""
    return list(_STRATEGIES.keys())


def get_strategy(name, **kwargs):
    """Instancie la strategy demandee.

    Args:
        name: identifiant de la strategy (ex. "multi-runs").
        **kwargs: parametres specifiques a la strategy (ex. n_runs=10
                  pour "multi-runs"). Voir la docstring de chaque classe.

    Returns:
        Instance de ValidationStrategy.

    Raises:
        ValueError: si la strategy n'existe pas.
    """
    if name not in _STRATEGIES:
        avail = ", ".join(sorted(_STRATEGIES.keys()))
        raise ValueError(f"Strategy inconnue : '{name}'. Disponibles : {avail}")
    return _STRATEGIES[name](**kwargs)


__all__ = ["ValidationStrategy", "MultiRunsStrategy", "MDStrategy",
           "get_strategy", "list_strategies"]
