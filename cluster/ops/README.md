# cluster/ops

Scripts operationnels du run final cluster. A executer dans cet ordre pour
relancer une production complete :

```bash
# 1. Deploiement du code sur les 16 workers
bash cluster/ops/deploy_cluster.sh

# 2. Init DB + enumeration CSP + insertion sols pending
python -m csp_solver.final.run setup --db ~/final.db --sizes 3,4,5,6,7,8,9

# 3. Dispatcher (orchestration parallele SSH)
python -m csp_solver.final.run dispatch --db ~/final.db --run-id 1 \
    --workers 49,50,...,64

# 4. Si des sols stuck (running > seuil sans heartbeat), reset + retry
python cluster/ops/finalize_stuck.py --db ~/final.db
python cluster/ops/retry_failed.py --db ~/final.db

# 5. Optionnel : copier les solutions C1 reussies vers C2/C3 (gain temps)
python cluster/ops/copy_C1_results.py --db ~/final.db

# 6. Plafonnement h9 (limitation a 100k sols par mol pour eviter explosion)
python cluster/ops/plafond_h9_C1.py --db ~/final.db

# 7. Nettoyage en fin de run
bash cluster/ops/cleanup_projet_cluster.sh
```

Apres production, migrer vers la DB viewer :

```bash
python -m viewer.migrations.final_to_viewer
```

Et calculer les features pour Ctopo : voir `csp_solver/analysis/__init__.py`.

## Variables d'environnement

- `CSP_CLUSTER_CONDA_INIT` : commande shell pour activer l'env conda
  (defaut : `eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" && conda activate nonbenz`)
- `CSP_CLUSTER_PROJECT_PATH` : chemin du repo sur les workers (defaut : `~/projet`)
