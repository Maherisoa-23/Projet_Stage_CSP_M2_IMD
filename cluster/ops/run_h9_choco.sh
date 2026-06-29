#!/bin/bash
# Pipeline complet h9 "isolation C5" via CHOCO (pas ACE) :
#   1. enumeration COMPLETE de h9 config Cstr (structurel, sans table) --
#      Choco enumere chaque graphe en <1s (mesure : 0.8-0.9s/graphe), donc
#      les ~2418 graphes h9 sont traites en ~30-40 min (contre des jours
#      avec ACE -- cf. notes de session).
#   2. plafond a 200 sols/molecule (selection stratifiee n_pent/n_hept,
#      seed 42, reutilise cluster/ops/plafond_h9_C1.py tel quel).
#   3. dispatch xTB sur le cluster (infra existante _run_final dispatch).
#
# A LANCER UNIQUEMENT APRES la fin du run h3-h8 (tmux "notable"), pour ne
# pas faire concurrence aux workers xTB pendant l'enumeration (qui elle-
# meme n'a pas besoin des workers, mais le dispatch en phase 3 oui).
#
# Lancer en tmux : tmux new -d -s h9choco "bash ~/projet/run_h9_choco.sh"
set -u
source /home/COALA/ramaherisoa/miniforge3/etc/profile.d/conda.sh
conda activate nonbenz
cd ~/projet

DB=~/projet/h9_choco.db

echo "===================================="
echo "===  H9 CHOCO (Cstr) START  ========"
echo "===================================="
echo "$(date)"

# === Phase 1 : ENUMERATION COMPLETE (Choco, sans table) ===
echo "=== PHASE 1 : ENUM CHOCO $(date) ==="
python ~/projet/enumerate_h9_choco.py \
    --db "$DB" \
    --notes "h9 Cstr via Choco -- $(date)"
ENUM_RC=$?
echo "=== ENUM fini RC=$ENUM_RC at $(date) ==="
if [ $ENUM_RC -ne 0 ]; then echo "Enum echouee, abort."; exit 1; fi

RUN_ID=$(python -c "
import sqlite3
c = sqlite3.connect('$DB')
r = c.execute('SELECT MAX(run_id) FROM final_runs').fetchone()
print(r[0] if r and r[0] else 1)
")
echo "Run ID = $RUN_ID"

# === Phase 2 : PLAFOND 200 sols/molecule ===
echo "=== PHASE 2 : PLAFOND (200/mol) $(date) ==="
python ~/projet/plafond_h9_C1.py \
    --db "$DB" --run-id "$RUN_ID" \
    --size-h 9 --config Cstr --target 200 --seed 42 --apply
echo "=== plafond fini RC=$? $(date) ==="

# === Phase 3 : DISPATCH (xTB + planarite sur cluster) ===
echo "=== PHASE 3 : DISPATCH $(date) ==="
python -m csp_solver._run_final dispatch \
    --db "$DB" \
    --run-id "$RUN_ID" \
    --workers 49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64 \
    --batch-size 40 \
    --max-parallel-xtb 40 \
    --timeout-xtb 50000 \
    --ssh-timeout 18000 \
    --heartbeat 60
echo "=== DISPATCH fini RC=$? at $(date) ==="

echo "=== STATUS FINAL ==="
python -m csp_solver._run_final status --db "$DB" --run-id "$RUN_ID"
date +%s > ~/_h9_choco.done
echo "===  H9 CHOCO FINI $(date) ===="
