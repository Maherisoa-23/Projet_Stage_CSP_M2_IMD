# analysis_v2 — Mode d'emploi cluster

Pipeline distribué pour calculer les ~50 descripteurs topologiques /
géométriques / électroniques sur toutes les solutions h6-h9 de
`db_v2.db`. Vise les 16 machines COALA configurées dans
`DEPLOIEMENT_CLUSTER.md`.

---

## Pré-requis (à vérifier UNE FOIS sur le cluster)

1. **L'environnement `nonbenz`** est créé sur le NFS (`~/miniforge3/envs/nonbenz`),
   avec `python 3.14 + networkx + numpy + lxml + pycsp3` (cf. `DEPLOIEMENT_CLUSTER.md` §3-4).
   Si pas encore fait :
   ```bash
   ssh 192.168.200.49
   eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
   conda activate nonbenz
   python -c "import networkx, numpy; print(networkx.__version__, numpy.__version__)"
   ```

2. **Les clés SSH** sont distribuées entre les 16 machines (cf. §8 du déploiement).

3. **Le projet déjà uploadé** sur le cluster. **MAIS** : `analysis_v2/` est tout
   nouveau, il faut le pousser. Voir étape 1 ci-dessous.

---

## Étape 1 — Upload du nouveau code `analysis_v2/`

Depuis Git Bash sur ton PC Windows, dans le dossier du projet :

```bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/second try with scipt and CSP"

# Pousse uniquement le nouveau package (rapide, ~50 KB)
tar -czf - csp_solver/experiments/csp_viewer/analysis_v2 \
  | ssh 192.168.200.49 \
    "cd /home/COALA/ramaherisoa/projet && tar -xzf -"
```

Vérification :

```bash
ssh 192.168.200.49 'ls /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/analysis_v2/'
# devrait montrer : schema.sql descriptors/ cluster/ compute_one.py CLUSTER_USAGE.md ...
```

---

## Étape 2 — Upload de la DB

`db_v2.db` doit être accessible depuis les 16 machines. Comme `/home/COALA`
est en NFS, on l'upload **une seule fois** sur la 49 et c'est visible
partout.

**Si tu n'as PAS encore db_v2.db sur le cluster** (probable, on l'a remplie
en local) :

```bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/second try with scipt and CSP/csp_solver/experiments/csp_viewer"

# La DB fait ~2.8 GB. scp avec progression.
scp db_v2.db 192.168.200.49:/home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db
```

Vérification :

```bash
ssh 192.168.200.49 'ls -lh /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db'
# doit montrer ~2.8G
```

**Sinon** (si la DB cluster est déjà à jour) : skip cette étape.

---

## Étape 3 — Construire le manifest (sur le cluster, 1 fois)

```bash
ssh 192.168.200.49
tmux new -s av2

# Dans tmux :
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz

# IMPORTANT : on se place à la RACINE DU PROJET, pas csp_solver/experiments,
# pour que python -m csp_solver... trouve le package.
cd /home/COALA/ramaherisoa/projet

# Prépare les dossiers
mkdir -p /home/COALA/ramaherisoa/projet/_av2_run/{workers,logs}

# Génère le manifest (~30s)
python -m csp_solver.experiments.csp_viewer.analysis_v2.cluster.build_manifest \
  --db   /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db \
  --h    h6 h7 h8 h9 \
  --output /home/COALA/ramaherisoa/projet/_av2_run/manifest.jsonl \
  --slice-size 500
```

> Si tu as déjà fait l'erreur de te placer dans `csp_solver/experiments` et que tu
> as eu `ModuleNotFoundError: No module named 'csp_solver'`, c'est exactement ça :
> juste un `cd /home/COALA/ramaherisoa/projet` et tu peux relancer.

Tu verras une ligne par h indiquant le nb de sols et de slices. Total
attendu : quelque chose comme `~600-1500 slices`.

---

## Étape 4 — Lancer le dispatcher

Toujours dans le tmux (toujours depuis la racine projet) :

```bash
HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python -m csp_solver.experiments.csp_viewer.analysis_v2.cluster.dispatcher \
  --hosts "$HOSTS" \
  --manifest /home/COALA/ramaherisoa/projet/_av2_run/manifest.jsonl \
  --remote-db /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db \
  --remote-manifest /home/COALA/ramaherisoa/projet/_av2_run/manifest.jsonl \
  --remote-output-dir /home/COALA/ramaherisoa/projet/_av2_run/workers \
  --remote-cwd /home/COALA/ramaherisoa/projet \
  --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \
  --conda-env nonbenz \
  --local-logs-dir /home/COALA/ramaherisoa/projet/_av2_run/logs
```

> Note : `--remote-cwd` est désormais la **racine projet** (`/home/COALA/ramaherisoa/projet`),
> pas `csp_solver/experiments` (sinon les workers auraient le même `ModuleNotFoundError`).

Le dispatcher :
- partitionne les slices entre les 16 hosts (round-robin)
- lance UN worker par host (qui traite ses slices en série)
- attend la fin de tous les workers
- log par host dans `_av2_run/logs/lis-cluster-coala-XX.log`

**Estimation temps** : sur 4 sol/s par worker, 16 workers = ~64/s.
- h6 (2.6k sols) : ~40 s
- h7 (estim 15k) : ~4 min
- h8 (estim 50k) : ~13 min
- h9 (estim 200k) : ~50 min
- **Total estimé : 1h-1h30**

Si la connexion SSH du PC tombe, le dispatcher tourne en tmux,
détache avec `Ctrl+B D`, reprends avec `tmux attach -t av2`.

---

## Étape 5 — Finaliser (merge workers → db_v2.solution_descriptors)

Une fois le dispatcher terminé sans erreur (toujours depuis la racine projet) :

```bash
cd /home/COALA/ramaherisoa/projet

python -m csp_solver.experiments.csp_viewer.analysis_v2.cluster.finalize \
  --db /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db \
  --workers-dir /home/COALA/ramaherisoa/projet/_av2_run/workers \
  --delete-after-merge
```

Vérification :

```bash
sqlite3 /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db \
  "SELECT h, COUNT(*) FROM solution_descriptors GROUP BY h ORDER BY h"
```

Doit afficher h6, h7, h8, h9 avec leurs comptes (~total ~270k lignes attendu).

---

## Étape 6 — Rapatrier la DB sur le PC

```bash
# Sur Windows Git Bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/second try with scipt and CSP/csp_solver/experiments/csp_viewer"

scp 192.168.200.49:/home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v2.db db_v2.db
```

Ensuite tu peux lancer le serveur viewer en local, et on attaque les
analyses cross-data.

---

## En cas de problème

### Un worker échoue
Le log se trouve dans `_av2_run/logs/lis-cluster-coala-XX.log`. Le worker
écrit aussi son stderr. On peut relancer juste pour les slices manquantes :

```bash
# Re-générer un manifest avec uniquement les non-traités (par defaut)
python -m csp_solver.experiments.csp_viewer.analysis_v2.cluster.build_manifest \
  --db .../db_v2.db --h h6 h7 h8 h9 \
  --output .../manifest_retry.jsonl --slice-size 500

# (build_manifest skippe auto les sols deja calculees a la version courante)
```

Puis relancer le dispatcher avec `manifest_retry.jsonl`.

### Tu veux refaire TOUT (force recompute)

```bash
sqlite3 .../db_v2.db "DELETE FROM solution_descriptors"
# puis relancer Etape 3-5
```

### Vérifier l'avancement pendant le run

```bash
# Compte des workers terminés
ls /home/COALA/ramaherisoa/projet/_av2_run/workers/worker_*.db | wc -l

# Voir les logs en live
tail -f /home/COALA/ramaherisoa/projet/_av2_run/logs/lis-cluster-coala-49.log
```
