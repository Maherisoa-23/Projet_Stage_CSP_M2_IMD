# Validation MMFF par sampling xTB

But : verifier que les sols declares `mmff_sure_plan` dans db_v4 sont vraiment
plans selon xTB. Sampling stratifie 500 par (h, config) = 6000 jobs.

## Etape 1 - Upload du nouveau code

Depuis Git Bash sur PC :
```bash
cd "/c/Projets/Projet_Stage_CSP_M2_IMD"
tar -czf - csp_solver/experiments_v3/validation \
  | ssh 192.168.200.49 "cd /home/COALA/ramaherisoa/projet && tar -xzf -"
```

## Etape 2 - tmux + build sample manifest

```bash
ssh 192.168.200.49
tmux new -s av3_val
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz
cd /home/COALA/ramaherisoa/projet

mkdir -p _ev3_val/{output,claims,logs}

python -m csp_solver.experiments_v3.validation.build_manifest \
  --db /home/COALA/ramaherisoa/projet/csp_solver/experiments/csp_viewer/db_v4.db \
  --n-per-bucket 500 \
  --output /home/COALA/ramaherisoa/projet/_ev3_val/manifest.jsonl

wc -l _ev3_val/manifest.jsonl  # attendu ~6000
```

## Etape 3 - Dispatcher

```bash
HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python csp_solver/experiments/cluster/dispatcher.py start \
  --mode ssh --hosts "$HOSTS" \
  --remote-cwd /home/COALA/ramaherisoa/projet \
  --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \
  --conda-env nonbenz \
  --worker-path csp_solver/experiments_v3/validation/worker.py \
  --manifest /home/COALA/ramaherisoa/projet/_ev3_val/manifest.jsonl \
  --output-root /home/COALA/ramaherisoa/projet/_ev3_val/output \
  --claims-dir /home/COALA/ramaherisoa/projet/_ev3_val/claims \
  --scratch-root /tmp \
  --concurrency 20 --timeout 600 \
  --state-dir /home/COALA/ramaherisoa/projet/_ev3_val/state
```

Detache : `Ctrl+B` puis `D`.

## Etape 4 - Suivi

```bash
# Count rapide
ls _ev3_val/output/*.json 2>/dev/null | wc -l
# Statuts
python -c "
import json
from pathlib import Path
from collections import Counter
files = list(Path('_ev3_val/output').glob('*.json'))
counts = Counter()
for f in files:
    try:
        d = json.loads(f.read_text())
        counts[d.get('status', '?')] += 1
    except: counts['parse_err'] += 1
print(f'{len(files)} files: {dict(counts)}')
"
```

## Etape 5 - Rapport

```bash
python -m csp_solver.experiments_v3.validation.aggregate \
  --output-root /home/COALA/ramaherisoa/projet/_ev3_val/output \
  --out /home/COALA/ramaherisoa/projet/_ev3_val/report.txt
```

Le rapport montre par (h, config) :
- N samples evalues
- nb planar / non_planar selon xTB
- precision MMFF = % reellement plan (CI95)

Si precision >= 95% -> MMFF est fiable, le 99.7% est valide.
Si precision 80-95% -> il faut nuancer le resultat.
Si precision < 80% -> MMFF s'est trompe massivement, serrer th_sure_plan.
