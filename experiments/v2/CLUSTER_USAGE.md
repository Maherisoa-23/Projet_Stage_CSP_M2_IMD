# experiments_v2 — Mode d'emploi cluster

Pipeline distribué pour générer des solutions CSP avec les nouvelles
contraintes (sym1, pb2, sym1_pb2, all_strict) + reconstruction +
validation MD/xTB, sur les 16 machines COALA.

**Stratégie globale** : on **réutilise** l'infra cluster existante de
`experiments/cluster/` (dispatcher), on lui pointe sur notre worker_v2
qui appelle notre run_one_job_v2 qui appelle notre main_v2 qui utilise
notre csp_model_v2. Toute l'orchestration SSH/claims/timeout reste celle
qui a déjà fait ses preuves.

---

## Étape 1 — Upload du nouveau code

Depuis Git Bash sur ton PC :

```bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/Projet_Stage_CSP_M2_IMD"

tar -czf - csp_solver/experiments_v2 \
  | ssh 192.168.200.49 \
    "cd /home/COALA/ramaherisoa/projet && tar -xzf -"
```

Vérification sur le cluster :

```bash
ls /home/COALA/ramaherisoa/projet/csp_solver/experiments_v2/
# doit lister : __init__.py README.md boundary_helper.py constraints/
#   csp_model.py main.py configs.py run_one_job.py cluster/ CLUSTER_USAGE.md

cd /home/COALA/ramaherisoa/projet
python -c "from csp_solver.experiments_v2.csp_model import build_and_solve_v2; print('OK')"
# doit afficher : OK
```

---

## Étape 2 — Construire le manifest

Choisis le `h` cible (h7 conseillé pour validation rapide, h6+h7+h8+h9
pour run final).

```bash
ssh 192.168.200.49
tmux new -s av2_csp

# Dans tmux :
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz
cd /home/COALA/ramaherisoa/projet

mkdir -p _ev2_run/{workers,claims,state,logs}

# Manifest : 5 configs x 144 mols h7 = 720 jobs (~3-4h sur cluster)
# Avec extras no-freeze + no-table (comme nos meilleurs runs h6)
python -m csp_solver.experiments_v2.cluster.build_manifest \
  /home/COALA/ramaherisoa/projet/csp_solver/experiments/plane/benzdb/h7 \
  --configs all \
  --extra-flag no-freeze,no-table \
  --output /home/COALA/ramaherisoa/projet/_ev2_run/manifest.jsonl
```

Note : `--extra-flag` propage `--no-freeze --no-table` à TOUTES les
configs v2. Adapte selon tes besoins (vide = configs v2 seules, sans
extras CSP).

---

## Étape 3 — Lancer le dispatcher (réutilise l'existant)

**Astuce clef** : le dispatcher existant `experiments/cluster/dispatcher.py`
accepte `--worker-path` → on lui pointe sur notre worker_v2.

```bash
HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python csp_solver/experiments/cluster/dispatcher.py start \
  --mode ssh --hosts "$HOSTS" \
  --remote-cwd /home/COALA/ramaherisoa/projet \
  --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \
  --conda-env nonbenz \
  --worker-path csp_solver/experiments_v2/cluster/worker.py \
  --manifest /home/COALA/ramaherisoa/projet/_ev2_run/manifest.jsonl \
  --output-root /home/COALA/ramaherisoa/projet/_ev2_run/output \
  --claims-dir /home/COALA/ramaherisoa/projet/_ev2_run/claims \
  --scratch-root /tmp \
  --concurrency 4 --timeout 1800 \
  --state-dir /home/COALA/ramaherisoa/projet/_ev2_run/state
```

Détache le tmux : `Ctrl+B` puis `D`. Le batch tourne (~3-4h).

---

## Étape 4 — Suivi pendant le run

```bash
# Etat du dispatcher (status global)
python csp_solver/experiments/cluster/dispatcher.py status \
  --state-dir /home/COALA/ramaherisoa/projet/_ev2_run/state

# Compter les job_status.json deja écrits
find /home/COALA/ramaherisoa/projet/_ev2_run/output -name "job_status.json" | wc -l
```

---

## Étape 5 — Construire la nouvelle DB (mode DB-only, mai 2026)

Depuis mai 2026, `run_one_job_v2` n'écrit PAS de xyz sur le NFS. À la
place, chaque job produit `output_root/worker_dbs/<h>__<config>__<mol>.db`
contenant **molecules + solutions + xyz_files (BLOB gzip) + configs** dans
un schéma identique à `db_v2`. Le NFS reçoit donc :
- 1 petit `job_status.json` par job (pour `is_done()` du worker)
- 1 sqlite par job dans `worker_dbs/`

Pour fabriquer la `db_v3.db` finale, on **merge** ces worker DBs (pas
besoin de `build_db.py` ni de `ingest_xyz.py`) :

```bash
python -m csp_solver.experiments_v2.cluster.finalize \
  --workers-dir /home/COALA/ramaherisoa/projet/_ev2_run/output/worker_dbs \
  --db /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v3.db \
  --delete-after-merge
```

- `--delete-after-merge` supprime les worker DBs après merge réussi
  (économie d'espace NFS).
- Idempotent : peut être relancé sans risque (`INSERT OR REPLACE` sur
  PK composées).

À la fin, `db_v3.db` contient tout : pas d'étape `ingest_xyz` séparée,
pas de fichiers xyz éparpillés sur le NFS.

**(Optionnel) Vérification rapide** :
```bash
python -c "
import sqlite3
c = sqlite3.connect('/home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v3.db')
for r in c.execute(\"SELECT h, config, COUNT(*) FROM molecules GROUP BY h, config\"):
    print(r)
for r in c.execute(\"SELECT h, verdict, COUNT(*) FROM solutions GROUP BY h, verdict\"):
    print(r)
print('xyz_files :', c.execute('SELECT COUNT(*) FROM xyz_files').fetchone())
"
```

---

## Étape 6 — Rapatrier db_v3.db et comparer

Sur ton PC :

```bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/Projet_Stage_CSP_M2_IMD/csp_solver/experiments/csp_viewer"

scp 192.168.200.49:/home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v3.db db_v3.db
```

Puis lance le batch analysis_v2 sur db_v3 :

```bash
cd "../../.."  # racine projet
./venv/Scripts/python.exe -u -m csp_solver.experiments.csp_viewer.analysis_v2.cluster.build_manifest \
  --db csp_solver/experiments/csp_viewer/db_v3.db \
  --h h7 \
  --output _av2_v3/manifest.jsonl
# ... (cf analysis_v2/CLUSTER_USAGE.md)
```

Le rapport `rapport_h7.html` côté v3 te montrera le **nouveau %plan**.

**Comparaison rapide** :
```bash
./venv/Scripts/python.exe -c "
import sqlite3
v2 = sqlite3.connect('csp_solver/experiments/csp_viewer/db_v2.db')
v3 = sqlite3.connect('csp_solver/experiments/csp_viewer/db_v3.db')
for db, lbl in [(v2,'v2_baseline'),(v3,'v3_constrained')]:
    r = db.execute(\"SELECT verdict, COUNT(*) FROM solutions WHERE h='h7' GROUP BY verdict\").fetchall()
    print(lbl, ':', dict(r))
"
```

Le ratio plan/non_plan de v3 devrait être nettement meilleur que v2.

---

## En cas d'erreur

### Un worker plante systematiquement
Voir les logs : `/home/COALA/ramaherisoa/projet/_ev2_run/logs/lis-cluster-coala-XX.log`

### Test isolé d'un seul job
Sur ton PC ou sur cluster :
```bash
python -m csp_solver.experiments_v2.run_one_job \
  --graph plane/benzdb/h7/0-7-8-15-16-23-24.graph \
  --config sym1_pb2 \
  --output-root /tmp/ev2_test \
  --scratch-root /tmp \
  --no-freeze --no-table \
  --timeout 600
```

### Relancer juste les jobs échoués
Comme d'habitude (cf DEPLOIEMENT_CLUSTER.md §15) :
```bash
python csp_solver/experiments/cluster/recover.py \
  --manifest .../_ev2_run/manifest.jsonl \
  --output-root .../_ev2_run/output \
  --claims-dir .../_ev2_run/claims \
  --status failed --reset
# -> manifest_retry.jsonl
```
