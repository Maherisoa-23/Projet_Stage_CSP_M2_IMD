# experiments_v3 — Mode d'emploi cluster

Pipeline distribué pour générer des solutions CSP avec :
- nouvelle **contrainte CSP Gauss-Bonnet locale** (`tau_gb`, `radius_gb`)
- nouveau **filtre post-CSP MMFF 3-tier** (sure_plan / gray / sure_non_plan)
- xTB conditionnel : tourne uniquement sur la zone grise MMFF

**Stratégie globale** : on **réutilise** l'infra cluster existante de
`experiments/cluster/` (dispatcher) ; on lui pointe sur notre worker_v3,
qui appelle notre run_one_job_v3, qui appelle notre main_v3, qui utilise
csp_model_v3 + v3_pipeline.

**Configs recommandées** (CSP-level) :
- `sym1_pb2_curv1` (recommandé par défaut) — combine sym=1, pb=2, tau_gb=1
- `curv1` — Gauss-Bonnet seul, baseline du nouveau
- `baseline_v3` — sans contrainte (référence)

Voir [configs.py](configs.py) pour la liste complète.

---

## Pré-requis cluster : installer RDKit

Le pipeline v3 nécessite RDKit (pour MMFF). Sur la frontale :

```bash
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz
pip install rdkit
python -c "from rdkit.Chem import AllChem; print('rdkit OK')"
```

---

## Étape 1 — Upload du nouveau code

Depuis Git Bash sur ton PC :

```bash
cd "/c/Projets/Projet_Stage_CSP_M2_IMD"

tar -czf - csp_solver/experiments_v3 \
  | ssh 192.168.200.49 \
    "cd /home/COALA/ramaherisoa/projet && tar -xzf -"
```

Vérification sur le cluster :

```bash
ls /home/COALA/ramaherisoa/projet/csp_solver/experiments_v3/
# doit lister : __init__.py CLUSTER_USAGE.md mmff_oracle.py
#   curvature_helper.py constraints/ csp_model.py configs.py main.py
#   v3_pipeline.py db_helpers.py run_one_job.py cluster/
#   validate_*.py (scripts de validation)

cd /home/COALA/ramaherisoa/projet
python -c "
from csp_solver.experiments_v3.csp_model import build_and_solve_v3
from csp_solver.experiments_v3.mmff_oracle import mmff_planarity
print('OK')
"
# doit afficher : OK
```

---

## Étape 2 — Construire le manifest

Choisis le `h` cible. Pour comparer plusieurs configs, mets-les ensemble.

```bash
ssh 192.168.200.49
tmux new -s av3_csp

# Dans tmux :
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz
cd /home/COALA/ramaherisoa/projet

mkdir -p _ev3_run/{workers,claims,state,logs}

# Manifest : config recommandee sur h7 = 144 graphes
# avec extras no-freeze + no-table (comme nos meilleurs runs h6)
python -m csp_solver.experiments_v3.cluster.build_manifest \
  /home/COALA/ramaherisoa/projet/csp_solver/experiments/plane/benzdb/h7 \
  --configs sym1_pb2_curv1 \
  --extra-flag no-freeze,no-table \
  --output /home/COALA/ramaherisoa/projet/_ev3_run/manifest.jsonl
```

Pour un benchmark multi-configs (baseline vs avec courbure) :

```bash
python -m csp_solver.experiments_v3.cluster.build_manifest \
  /home/COALA/ramaherisoa/projet/csp_solver/experiments/plane/benzdb/h7 \
  --configs baseline_v3,curv1,sym1_pb2_curv1 \
  --extra-flag no-freeze,no-table \
  --output /home/COALA/ramaherisoa/projet/_ev3_run/manifest.jsonl
```

---

## Étape 3 — Lancer le dispatcher (réutilise l'existant)

**Astuce clef** : le dispatcher existant `experiments/cluster/dispatcher.py`
accepte `--worker-path` → on lui pointe sur notre worker_v3.

```bash
HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python csp_solver/experiments/cluster/dispatcher.py start \
  --mode ssh --hosts "$HOSTS" \
  --remote-cwd /home/COALA/ramaherisoa/projet \
  --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \
  --conda-env nonbenz \
  --worker-path csp_solver/experiments_v3/cluster/worker.py \
  --manifest /home/COALA/ramaherisoa/projet/_ev3_run/manifest.jsonl \
  --output-root /home/COALA/ramaherisoa/projet/_ev3_run/output \
  --claims-dir /home/COALA/ramaherisoa/projet/_ev3_run/claims \
  --scratch-root /tmp \
  --concurrency 20 --timeout 20000 \
  --state-dir /home/COALA/ramaherisoa/projet/_ev3_run/state
```

Détache le tmux : `Ctrl+B` puis `D`.

---

## Étape 4 — Suivi pendant le run

Attention : `dispatcher.py status` prend `--output-root`, `--manifest`, `--claims-dir`
(PAS `--state-dir` qui est seulement pour `start` / `stop`).

```bash
python csp_solver/experiments/cluster/dispatcher.py status \
  --output-root /home/COALA/ramaherisoa/projet/_ev3_run/output \
  --manifest /home/COALA/ramaherisoa/projet/_ev3_run/manifest.jsonl \
  --claims-dir /home/COALA/ramaherisoa/projet/_ev3_run/claims

# Compter les job_status.json deja ecrits
find /home/COALA/ramaherisoa/projet/_ev3_run/output -name "job_status.json" | wc -l

# Compter les workers DBs deja crees
ls /home/COALA/ramaherisoa/projet/_ev3_run/output/worker_dbs/*.db 2>/dev/null | wc -l
```

---

## Étape 5 — Construire la db_v4.db (merge des worker DBs)

```bash
python -m csp_solver.experiments_v3.cluster.finalize \
  --workers-dir /home/COALA/ramaherisoa/projet/_ev3_run/output/worker_dbs \
  --db /home/COALA/ramaherisoa/projet/viewer/db_v4.db \
  --delete-after-merge
```

Le schéma de db_v4 est compatible avec csp_viewer existant (mêmes colonnes
+ extensions : `solutions.decision_path`, `solutions.mmff_angle_deg`,
`molecules.n_mmff_sure_plan/non_plan/gray`).

**Vérification rapide** :
```bash
python -c "
import sqlite3
c = sqlite3.connect('/home/COALA/ramaherisoa/projet/viewer/db_v4.db')

print('=== par config ===')
for r in c.execute(\"SELECT h, name, n_molecules, n_solutions, n_plans, n_non_plans FROM configs ORDER BY h, name\"):
    print(' ', r)

print()
print('=== decision_path (sample) ===')
for r in c.execute(\"SELECT decision_path, COUNT(*) FROM solutions GROUP BY decision_path ORDER BY 2 DESC LIMIT 12\"):
    print(' ', r)

print()
print('xyz_files :', c.execute('SELECT COUNT(*) FROM xyz_files').fetchone())
"
```

---

## Étape 6 — Rapatrier db_v4.db et comparer

Sur ton PC :

```bash
cd "/c/Projets/Projet_Stage_CSP_M2_IMD/viewer"

scp 192.168.200.49:/home/COALA/ramaherisoa/projet/viewer/db_v4.db db_v4.db
```

**Comparaison rapide v2 vs v3** :
```bash
./venv/Scripts/python.exe -c "
import sqlite3
for path, lbl in [
    ('viewer/db_v2.db', 'v2_baseline'),
    ('viewer/db_v4.db', 'v3_constrained'),
]:
    db = sqlite3.connect(path)
    print(f'--- {lbl} ---')
    for h in ('h6','h7','h8','h9'):
        plan = db.execute(\"SELECT COUNT(*) FROM solutions WHERE h=? AND verdict='plan'\", (h,)).fetchone()[0]
        non = db.execute(\"SELECT COUNT(*) FROM solutions WHERE h=? AND verdict='non_plan'\", (h,)).fetchone()[0]
        tot = plan + non
        if tot:
            print(f'  {h}: {plan}/{tot} = {100*plan/tot:.1f}% plan')
"
```

---

## En cas d'erreur

### Un worker plante systematiquement
Voir les logs : `/home/COALA/ramaherisoa/projet/_ev3_run/logs/lis-cluster-coala-XX.log`

### Test isolé d'un seul job (en local sur ton PC, sans cluster)
```bash
./venv/Scripts/python.exe -m csp_solver.experiments_v3.run_one_job \
  --graph csp_solver/experiments/plane/benzdb/h6/0-7-8-15-16-23.graph \
  --config sym1_pb2_curv1 \
  --output-root /tmp/ev3_test \
  --scratch-root /tmp \
  --no-freeze --no-table \
  --timeout 600
```

**Note** : ce test isole nécessite xTB dans le PATH. Sur Windows sans xTB,
les sols "gray" seront skip (warning), mais sure_plan / sure_non_plan
restent traités.

### Relancer juste les jobs échoués
Comme d'habitude :
```bash
python csp_solver/experiments/cluster/recover.py \
  --manifest .../_ev3_run/manifest.jsonl \
  --output-root .../_ev3_run/output \
  --claims-dir .../_ev3_run/claims \
  --status failed --reset
# -> manifest_retry.jsonl
```

### Test du modele CSP seulement (sans MMFF/xTB)
```bash
./venv/Scripts/python.exe -m csp_solver.experiments_v3.main \
  csp_solver/experiments/plane/benzdb/h6/0-7-8-15-16-23.graph \
  --config sym1_pb2_curv1 \
  --no-freeze --no-table
```

---

## Architecture

```
csp_solver/experiments_v3/
├── __init__.py
├── CLUSTER_USAGE.md              <- ce fichier
├── README.md                     (a creer si besoin)
├── mmff_oracle.py                MMFF planarity + xyz writer
├── curvature_helper.py           Gauss-Bonnet discret (sans PyCSP3)
├── constraints/
│   ├── __init__.py
│   └── local_curvature.py        Contrainte CSP PyCSP3
├── csp_model.py                  build_and_solve_v3 (+ Gauss-Bonnet)
├── configs.py                    presets CSP-level
├── main.py                       CLI (--config, --tau-gb, --th-sure-*)
├── v3_pipeline.py                reconstruction + MMFF 3-tier + xTB cond
├── db_helpers.py                 schema etendu + ingest_mol_dir_v3
├── run_one_job.py                pipeline 1 job (DB-only)
├── validate_mmff.py              (scripts de validation post-hoc)
├── validate_curvature.py
├── validate_pipeline.py
└── cluster/
    ├── __init__.py
    ├── build_manifest.py
    ├── worker.py
    └── finalize.py
```

## Gain attendu (mesure sur db_v2 ~111k mols, cf validate_pipeline.py)

| h  | speedup xTB | plans capturés | precision (kept) |
|----|------------:|---------------:|-----------------:|
| h6 | 2.75×       | 86.3%          | 84.2%            |
| h7 | 2.92×       | 79.4%          | 77.1%            |
| h8 | 3.23×       | 72.7%          | 69.4%            |
| h9 | 2.79×       | 76.8%          | 65.1%            |

Soit globalement **~2.5-3.2× moins d'appels xTB** pour ~80% des plans
préservés. Le gain est sur l'**efficacité** (plans générés par appel xTB)
qui passe de ~0.5 à ~1.2-1.8.
