"""Pipeline cluster pour experiments_v2.

Reutilise au max l'infra existante de experiments/cluster/ (atomic_io,
patterns de claim, format manifest JSONL). Seules differences :
  - build_manifest : configs depuis experiments_v2/configs.py (5 noms v2)
  - worker : appelle experiments_v2/run_one_job.py au lieu de
    experiments/run_one_job.py
  - dispatcher : identique (peut etre reutilise tel quel)
  - finalize : identique (peut etre reutilise tel quel)
"""
