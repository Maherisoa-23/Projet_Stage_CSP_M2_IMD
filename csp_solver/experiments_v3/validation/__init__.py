"""Validation par sampling xTB des sols mmff_sure_plan de db_v4.

Pour verifier que MMFF n'a pas menti, on lance xTB MD+opt sur un echantillon
stratifie de sols declares "mmff_sure_plan" et on compare avec le verdict
xTB reel. La precision par (h, config) nous dit si MMFF est fiable.

Pipeline :
  1. build_manifest.py : sample N sols par (h, config) -> manifest.jsonl
  2. worker.py         : cluster worker, appelle run_one.py
  3. run_one.py        : extrait source.xyz de db_v4, lance xTB, ecrit json
  4. aggregate.py      : merge results -> rapport
"""
