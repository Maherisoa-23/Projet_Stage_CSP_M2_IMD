"""Wrappers xTB : optimisation simple et det-opt (perturbation z + opt).

Modules :
  - optimizer : xtb --opt avec perturbation z aleatoire (multi-runs)
  - det_opt   : xtb --opt avec perturbation z analytique deterministe
                (byte-deterministe -- remplace l'ancien protocole MD)
  - md        : shim retro-compat qui re-exporte depuis det_opt

Historique : le protocole 'MD + opt' a ete remplace par 'perturbation z
analytique + opt' en mai 2026 (xtb --md non deterministe, cf. det_opt.py).
"""
from .optimizer import optimize_xtb, read_optimized_coords, verify_distances  # noqa: F401
from .det_opt import md_then_optimize, DEFAULT_MD_PARAMS  # noqa: F401
