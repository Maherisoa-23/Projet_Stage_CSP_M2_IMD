"""Sous-package du run final cluster h3-h9.

Modules :
  - run         : entree CLI (setup, dispatch, status). `python -m csp_solver.final.run ...`
  - dispatcher  : orchestration multi-workers SSH
  - db          : schema SQLite + helpers (claim_batch, commit_results_batch, ...)
  - configs     : definitions des configurations CSP C1/C2/C3 du run final
  - enumerate   : wrapper csp_solver.utils.* pour le run final
  - worker      : processus worker SSH (lance par dispatcher via SSH)
  - xtb_metrics : parsing energy/HOMO-LUMO depuis stdout xtb

Historique : ces modules etaient prefixes _ (convention privee Python)
alors qu'il s'agit du point d'entree principal de la production cluster.
Regroupes dans final/ en juin 2026 pour clarifier la structure du package.
"""
