"""
Interface des strategies de validation.

Une strategy encapsule une maniere de transformer une solution CSP
(reconstruction 3D + test de planarite) en un verdict. Les strategies sont
independantes les unes des autres : on peut en ajouter sans modifier le
pipeline existant, et plusieurs peuvent s'appliquer a la meme solution
(les blocs de resultats coexistent dans data.json).

Convention :
    - Chaque strategy a un attribut de classe `name` (str) qui sert de cle
      dans le registry.
    - validate_solutions() boucle sur les solutions et retourne une liste
      de dicts (un par solution), compatible avec le format historique.
    - Les fichiers XYZ produits sont ecrits dans `output_dir`, dans une
      sous-arborescence specifique a la strategy (ex. "sol_X/run_NN_opt.xyz"
      pour multi-runs, "sol_X/md_validation/" pour md).
"""

from abc import ABC, abstractmethod


class ValidationStrategy(ABC):
    """Interface abstraite. Toute strategy doit definir `name` et
    `validate_solutions`."""

    name: str = ""  # identifiant utilise dans le registry, surcharge par les sous-classes

    @abstractmethod
    def validate_solutions(self, graph, solutions, output_dir):
        """Reconstruit chaque solution, l'optimise (selon la strategy) et
        teste la planarite.

        Args:
            graph: BenzenoidGraph.
            solutions: liste de dicts {hex_id: taille}.
            output_dir: pathlib.Path ou ecrire les XYZ produits.

        Returns:
            list[dict] : un dict par solution, avec au minimum les cles
                'index', 'planar', 'angle_deg', 'message'. Chaque strategy
                peut ajouter ses propres cles (ex. 'runs', 'md_validation').
        """
        raise NotImplementedError
