"""Pipeline distribue : split, worker, finalize, dispatcher.

Strategie : write-many-then-merge.
  1. build_manifest.py : decoupe le travail en SLICES (~500 sols par slice)
     -> manifest.jsonl
  2. worker.py : reçoit un slice, calcule descripteurs, ecrit dans son
     propre sqlite local (worker_<slice_id>.db). Pas de lock contention.
  3. finalize.py : merge tous les worker_*.db dans db_v2.solution_descriptors
  4. dispatcher.py : orchestre l'execution SSH parallele des workers
     sur les 16 machines du cluster. Distinct du dispatcher CSP existant
     (qui est specifique a la pipeline CSP+xTB).

Idempotent : un worker peut etre re-execute sans dupliquer.
"""
