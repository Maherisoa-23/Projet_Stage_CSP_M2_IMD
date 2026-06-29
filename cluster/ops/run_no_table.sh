#!/bin/bash
# Run "isolation C5" : config Cstr (no_table=True, adj_57=False) h3-h9.
# h9 plafonne a 200 sols/molecule (selection stratifiee n_pent/n_hept, seed 42).
#
# Les 3 autres configs des slides se derivent en analyse (sans run) :
#   C struct+C5 = C1 (base finale) ; +C6 = filtre adj_57 ; +C6+C5 = C1 filtre adj_57.
#
# Lancer en tmux : tmux new -d -s notable "bash ~/run_no_table.sh"
set -u
source /home/COALA/ramaherisoa/miniforge3/etc/profile.d/conda.sh
conda activate nonbenz
cd ~/projet

DB=~/projet/no_table_run.db
SIZES="${1:-3,4,5,6,7,8}"   # h9 traite a part (enumeration lourde)

echo "===================================="
echo "===  RUN NO-TABLE (Cstr) START  ===="
echo "===  sizes=$SIZES"
echo "===================================="
echo "$(date)"

# === Phase 1 : SETUP (enum CSP Cstr + populate DB) ===
echo "=== PHASE 1 : SETUP $(date) ==="
python -m csp_solver._run_final setup \
    --db "$DB" \
    --sizes "$SIZES" \
    --configs Cstr \
    --notes "isolation C5 -- Cstr no_table -- $(date)"
SETUP_RC=$?
echo "=== SETUP fini RC=$SETUP_RC at $(date) ==="
if [ $SETUP_RC -ne 0 ]; then echo "Setup echoue, abort."; exit 1; fi

RUN_ID=$(python -c "
import sqlite3
c = sqlite3.connect('$DB')
r = c.execute('SELECT MAX(run_id) FROM final_runs').fetchone()
print(r[0] if r and r[0] else 1)
")
echo "Run ID = $RUN_ID"

# === Phase 1b : plafond h9 a 200 sols/molecule (si h9 present) ===
if echo ",$SIZES," | grep -q ",9,"; then
  echo "=== PLAFOND h9 Cstr (200/mol) $(date) ==="
  python ~/projet/plafond_h9_C1.py \
      --db "$DB" --run-id "$RUN_ID" \
      --size-h 9 --config Cstr --target 200 --seed 42 --apply
  echo "=== plafond fini RC=$? $(date) ==="
fi

# === Phase 2 : DISPATCH (xTB + planarite sur cluster) ===
echo "=== PHASE 2 : DISPATCH $(date) ==="
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
date +%s > ~/_no_table.done
echo "===  RUN NO-TABLE FINI $(date) ===="
