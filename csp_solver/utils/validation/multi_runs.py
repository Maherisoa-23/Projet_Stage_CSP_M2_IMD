"""
Strategy "multi-runs" : N optimisations xTB independantes par solution
avec perturbations aleatoires en z, puis classification statistique
(realisee a posteriori par aggregate_runs.py).

Comportement historique du pipeline. Si n_runs=1, retombe sur le mode
"single-run avec choix de la meilleure variante multi-blocs", egalement
historique.

Cette classe est volontairement un mince wrapper sur les fonctions
existantes _run_single / _run_multi de reconstruction.pipeline. Elle ne
duplique pas leur logique : elle se contente de les exposer derriere
l'interface ValidationStrategy. Quand une 2eme strategy (ex. MD) sera
ajoutee, elle aura sa propre logique completement separee.
"""

from utils.validation.base import ValidationStrategy


class MultiRunsStrategy(ValidationStrategy):
    """Validation par optimisations xTB multiples avec perturbations
    aleatoires. Ne calcule pas les stats (delegues a aggregate_runs.py)."""

    name = "multi-runs"

    def __init__(self, n_runs=1, threshold=10.0, opt_level="tight"):
        """
        Args:
            n_runs: nombre d'optimisations xTB par solution. Si n_runs=1,
                    comportement single-run historique (best variante
                    multi-blocs). Si n_runs>1, structure sol_X/run_NN_opt.xyz.
            threshold: seuil de planarite en degres (passe au test ACP).
            opt_level: niveau de convergence xTB (--opt LEVEL).
        """
        self.n_runs = max(1, int(n_runs))
        self.threshold = float(threshold)
        self.opt_level = opt_level

    def validate_solutions(self, graph, solutions, output_dir):
        """Boucle sur les solutions et delegue a _run_single / _run_multi
        selon n_runs."""
        # Import local : pipeline.py importe lui-meme cette strategy via
        # reconstruct_and_validate, donc on ne peut pas faire l'import en
        # haut du module sans circularite.
        from reconstruction.pipeline import _run_single, _run_multi

        results = []
        for i, sol in enumerate(solutions, 1):
            sol_str = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
            print(f"\n--- Solution {i}/{len(solutions)} : {sol_str} ---")
            if self.n_runs > 1:
                r = _run_multi(graph, sol, i, self.threshold, self.opt_level,
                               output_dir, sol_str, self.n_runs)
            else:
                r = _run_single(graph, sol, i, self.threshold, self.opt_level,
                                output_dir, sol_str)
            results.append(r)
        return results
