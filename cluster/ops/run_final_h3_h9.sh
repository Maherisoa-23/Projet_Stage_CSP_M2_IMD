#!/bin/bash
# Run final h3-h9 x C1,C2,C3 sur cluster.
# A lancer dans tmux : tmux new -d -s final_run "bash ~/run_final_h3_h9.sh"
# Survient a toute deconnexion SSH (tmux + nohup-like).

set -u
source /home/COALA/ramaherisoa/miniforge3/etc/profile.d/conda.sh
conda activate nonbenz
cd ~/projet

DB=~/projet/final_h3_h9.db

echo "===================================="
echo "===  RUN FINAL h3-h9 START  ========"
echo "===================================="
echo "$(date)"
echo ""

# === Phase 1 : SETUP (enum CSP + populate DB) ===
echo "=== PHASE 1 : SETUP $(date) ==="
python -m csp_solver._run_final setup \
    --db $DB \
    --sizes 3,4,5,6,7,8,9 \
    --configs C1,C2,C3 \
    --notes "run final h3-h9 x C1,C2,C3 -- $(date)"

SETUP_RC=$?
echo ""
echo "=== SETUP fini RC=$SETUP_RC at $(date) ==="
if [ $SETUP_RC -ne 0 ]; then
    echo "Setup a echoue, abort. Voir output ci-dessus."
    exit 1
fi

# Recupere le run_id le plus recent
RUN_ID=$(python -c "
import sqlite3
c = sqlite3.connect('$DB')
r = c.execute('SELECT MAX(run_id) FROM final_runs').fetchone()
print(r[0] if r and r[0] else 1)
")
echo ""
echo "Run ID = $RUN_ID"
echo ""

# === Phase 2 : DISPATCH (xTB + planarity sur cluster) ===
echo "=== PHASE 2 : DISPATCH $(date) ==="
python -m csp_solver._run_final dispatch \
    --db $DB \
    --run-id $RUN_ID \
    --workers 49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64 \
    --batch-size 40 \
    --max-parallel-xtb 40 \
    --timeout-xtb 50000 \
    --ssh-timeout 18000 \
    --heartbeat 60

DISPATCH_RC=$?
echo ""
echo "=== DISPATCH fini RC=$DISPATCH_RC at $(date) ==="
echo ""

# === Fin ===
echo "=== STATUS FINAL ==="
python -m csp_solver._run_final status --db $DB --run-id $RUN_ID

echo ""
echo "===================================="
echo "===  RUN FINAL FINI ================"
echo "===================================="
echo "$(date)"

# Marqueur de fin (pour notification eventuelle)
date +%s > ~/_run_final.done
