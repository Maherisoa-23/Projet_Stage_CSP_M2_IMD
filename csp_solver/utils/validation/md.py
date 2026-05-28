"""
Strategy "md" : 1 run de dynamique moleculaire (~1 ps a 298 K) suivi d'une
optimisation finale, par solution.

Protocole recommande par Yannick Carissan (chimiste AMU) :
  1. xtb input.xyz --md --input md.inp     # MD courte pour casser symetries
  2. extraire la derniere frame de xtb.trj
  3. xtb md_geom.xyz --opt                  # opt finale -> minimum local

Avantages vs multi-runs :
  - 1 seul run par solution (vs N=10) -> plus rapide
  - Exploration thermique reelle (vs perturbation aleatoire en z) -> plus
    fiable theoriquement pour eviter les minima locaux plats parasites

Inconvenients :
  - Verdict binaire planar/non-planar (vs distribution statistique multi-runs)
  - Necessite un xTB recent (>= 6.0 pour --md)
  - xTB MD n'est pas bit-deterministe (vitesses initiales seed par horloge),
    mais la variance d'angle reste sub-seuil pour les cas non marginaux
    (typiquement std < 0.01 deg sur structures planaires). Pour les cas
    limites pres du seuil 10 deg, multi-runs reste preferable.

Cette strategy ECRIT son resultat dans le bloc data.json 'md_validation'
(produit par aggregate_md.py). Elle ne touche pas au bloc 'runs' qui peut
coexister (les 2 methodes peuvent valider la meme solution pour comparaison).
"""

from utils.validation.base import ValidationStrategy
# Re-exporte les defauts pour qu'ils soient accessibles via cette strategy.
import sys
from pathlib import Path
_gen_root = Path(__file__).parent.parent.parent.parent / "non_benzenoid_generator"
_gen_str = str(_gen_root)
if _gen_str not in sys.path:
    sys.path.insert(0, _gen_str)
from csp_solver.xtb.md import DEFAULT_MD_PARAMS  # re-export pratique


class MDStrategy(ValidationStrategy):
    """Validation par MD courte + opt finale (1 run par solution)."""

    name = "md"

    def __init__(self, threshold=10.0, opt_level="tight",
                 md_params=None, deterministic=True):
        """
        Args:
            threshold     : seuil de planarite en degres.
            opt_level     : niveau de convergence pour l'opt finale (--opt LEVEL).
            md_params     : dict overridant DEFAULT_MD_PARAMS. Cles acceptees :
                            temp, time, dump, step, velo, nvt, hmass, sccacc
                            (cf. doc xTB $md block). xTB n'accepte PAS 'seed' --
                            la reproductibilite est obtenue via deterministic=True.
            deterministic : True (defaut) -> xTB tourne en single-thread, runs
                            consecutifs IDENTIQUES (verifie par md5). False ->
                            multi-thread plus rapide mais variation minime
                            possible entre runs due aux race conditions SCF.
        """
        self.threshold = float(threshold)
        self.opt_level = opt_level
        params = dict(DEFAULT_MD_PARAMS)
        if md_params:
            params.update(md_params)
        self.md_params = params
        self.deterministic = bool(deterministic)

    def validate_solutions(self, graph, solutions, output_dir):
        from reconstruction.pipeline import _run_md

        results = []
        for i, sol in enumerate(solutions, 1):
            sol_str = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
            print(f"\n--- Solution {i}/{len(solutions)} : {sol_str} ---")
            r = _run_md(graph, sol, i, self.threshold, self.opt_level,
                        output_dir, sol_str,
                        md_params=self.md_params,
                        deterministic=self.deterministic)
            results.append(r)
        return results
