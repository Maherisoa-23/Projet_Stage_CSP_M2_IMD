"""Alias retro-compat : csp_solver.xtb.md -> csp_solver.xtb.det_opt.

Le module a ete renomme en det_opt.py en juin 2026 (cf. det_opt.py:1-60).
Ce shim conserve les imports historiques (worker.py, viewer/aggregate_md.py,
experiments/v1/test_md_cases.py, etc.) sans refacto immediat.

A SUPPRIMER quand tous les callers auront ete migres vers
`from csp_solver.xtb.det_opt import deterministic_optimize`.
"""
import warnings as _warnings

from .det_opt import (  # noqa: F401
    DEFAULT_MD_PARAMS,
    md_then_optimize,
)

# Note : pas de warning au import pour eviter le bruit en prod. Mettre la
# deprecation dans la docstring suffit.
