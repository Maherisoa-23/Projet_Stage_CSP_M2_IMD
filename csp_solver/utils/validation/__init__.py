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

    - (futures) "md" : MD/MTD xTB suivi d'optimisation finale, deterministe
      avec seed fixe. Implementation : md.MDStrategy.

Usage :
    from utils.validation import get_strategy
    strategy = get_strategy("multi-runs", n_runs=10, threshold=10.0)
    results = strategy.validate_solutions(graph, solutions, output_dir)
"""

from utils.validation.base import ValidationStrategy
from utils.validation.multi_runs import MultiRunsStrategy
from utils.validation.md import MDStrategy

# Registry des strategies disponibles. Pour ajouter une methode, importer
# la classe et l'enregistrer ici.
_STRATEGIES = {
    "multi-runs": MultiRunsStrategy,
    "md": MDStrategy,
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
