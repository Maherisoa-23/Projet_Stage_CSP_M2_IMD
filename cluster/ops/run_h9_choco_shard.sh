#!/bin/bash
# Variante "shardee" de run_h9_choco.sh : traite une PLAGE de graphes h9
# (par indice, sur la liste triee) dans sa PROPRE DB, dispatchee sur SON
# PROPRE groupe de machines. Permet d'utiliser plusieurs groupes du cluster
# (Config 1, 2+3, 4, 5) EN PARALLELE, chacun ecrivant dans un fichier SQLite
# distinct -- donc AUCUNE contention croisee entre groupes (SQLite verrouille
# par fichier). On ne recombine que les COMPTEURS finaux (plan/non-plan),
# pas les lignes elles-memes -- pas besoin d'une DB unifiee.
#
# Usage :
#   bash run_h9_choco_shard.sh <label> <start_idx> <end_idx> <db_path> <workers_csv> <max_parallel_xtb>
#
# max_parallel_xtb DOIT correspondre au nb de coeurs/noeud du groupe (8 pour
# Config1/2/3/4, 40 pour Config5) -- xtb est mono-thread (OMP_NUM_THREADS=1),
# un de plus que le nb de coeurs ne ferait que swapper sans gagner de temps.
#
# Exemple (groupe Config1, graphes [1511:1813), 8 coeurs/noeud) :
#   bash run_h9_choco_shard.sh g1 1511 1813 ~/projet/h9_choco_g1.db \
#       10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25 8
#
# Lancer en tmux : tmux new -d -s h9_g1 "bash ~/projet/run_h9_choco_shard.sh g1 1511 1813 ~/projet/h9_choco_g1.db 10,...,25 8"
set -u
source /home/COALA/ramaherisoa/miniforge3/etc/profile.d/conda.sh
conda activate nonbenz
cd ~/projet

LABEL="${1:?label requis (ex: g0,g1,g2,g3)}"
START="${2:?start_idx requis}"
END="${3:?end_idx requis}"
DB="${4:?chemin db requis}"
WORKERS="${5:?liste workers CSV requise}"
MAXPAR="${6:?max-parallel-xtb requis (8 pour Config1/2/3/4, 40 pour Config5)}"

echo "===================================="
echo "===  H9 CHOCO SHARD [$LABEL] START  "
echo "===  graphes [$START:$END)  db=$DB"
echo "===  workers=$WORKERS"
echo "===================================="
echo "$(date)"

# === Phase 1 : ENUMERATION (Choco, sans table) -- shard uniquement ===
echo "=== [$LABEL] PHASE 1 : ENUM CHOCO $(date) ==="
python ~/projet/enumerate_h9_choco.py \
    --db "$DB" \
    --start-idx "$START" --end-idx "$END" \
    --notes "h9 Cstr via Choco -- shard $LABEL [$START:$END) -- $(date)"
ENUM_RC=$?
echo "=== [$LABEL] ENUM fini RC=$ENUM_RC at $(date) ==="
if [ $ENUM_RC -ne 0 ]; then echo "[$LABEL] Enum echouee, abort."; exit 1; fi

RUN_ID=$(python -c "
import sqlite3
c = sqlite3.connect('$DB')
r = c.execute('SELECT MAX(run_id) FROM final_runs').fetchone()
print(r[0] if r and r[0] else 1)
")
echo "[$LABEL] Run ID = $RUN_ID"

# === Phase 2 : PLAFOND 200 sols/molecule (sur ce shard seulement) ===
echo "=== [$LABEL] PHASE 2 : PLAFOND (200/mol) $(date) ==="
python ~/projet/plafond_h9_C1.py \
    --db "$DB" --run-id "$RUN_ID" \
    --size-h 9 --config Cstr --target 200 --seed 42 --apply
echo "=== [$LABEL] plafond fini RC=$? $(date) ==="

# === Phase 3 : DISPATCH (xTB sur le groupe de machines assigne) ===
echo "=== [$LABEL] PHASE 3 : DISPATCH $(date) ==="
python -m csp_solver._run_final dispatch \
    --db "$DB" \
    --run-id "$RUN_ID" \
    --workers "$WORKERS" \
    --batch-size 40 \
    --max-parallel-xtb "$MAXPAR" \
    --timeout-xtb 50000 \
    --ssh-timeout 18000 \
    --heartbeat 60
echo "=== [$LABEL] DISPATCH fini RC=$? at $(date) ==="

echo "=== [$LABEL] STATUS FINAL ==="
python -m csp_solver._run_final status --db "$DB" --run-id "$RUN_ID"
date +%s > ~/_h9_choco_${LABEL}.done
echo "===  H9 CHOCO SHARD [$LABEL] FINI $(date) ===="
