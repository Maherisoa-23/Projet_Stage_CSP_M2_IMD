#!/bin/bash
# Cleanup ~/projet sur cluster (192.168.200.49).
# A GARDER : csp_solver/ requirements.txt .gitignore
# A SUPPRIMER : tout le reste (anciens runs, DB historiques, scripts diag)
#
# Lance en parallel les gros rm -rf pour maximiser le throughput NFS.

set -u
START=$(date +%s)
echo "=== CLEANUP START $(date) ==="
echo ""
echo "Avant cleanup (juste ls, pas de du) :"
ls -la ~/projet/ 2>/dev/null | head -30 || true
echo ""

cd ~/projet || { echo "ERR: ~/projet introuvable"; exit 1; }

# --- Gros dossiers en parallel (un rm par dossier en arriere-plan) ---
echo "Lancement rm parallels..."
rm -rf _h9_run                                  &  PID_H9=$!
rm -rf _h8_run                                  &  PID_H8=$!
rm -rf _ev2_run_legacy_20260522_1716            &  PID_EV2L=$!
rm -rf _h7_run                                  &  PID_H7=$!
rm -rf _h6_run                                  &  PID_H6=$!
rm -rf _ev2_run_failed_1825                     &  PID_EV2F=$!
rm -rf _av2_run _ev2_h689 _ev2_pbX _ev2_run _ev2_run_failed2_1914 _ev3_run _ev3_val non_benzenoid_generator  &  PID_REST=$!

# --- Petits fichiers en serie (tres rapide) ---
rm -f _check_files_sync.py _count_all_h6_h9.py _diag_empty_sol.py _diag_xtb_cluster.py _rebuild_cluster_db.py
rm -f _h9_xyz.db db_cluster.db
rm -f count_h6_h9.log count_results.json rebuild.log

# --- Attendre la fin de chaque rm parallel et logger ---
echo "Attente fin des rm..."
wait $PID_H9    && echo "[$(date +%H:%M:%S)] _h9_run                       OK"
wait $PID_H8    && echo "[$(date +%H:%M:%S)] _h8_run                       OK"
wait $PID_EV2L  && echo "[$(date +%H:%M:%S)] _ev2_run_legacy_20260522_1716 OK"
wait $PID_H7    && echo "[$(date +%H:%M:%S)] _h7_run                       OK"
wait $PID_H6    && echo "[$(date +%H:%M:%S)] _h6_run                       OK"
wait $PID_EV2F  && echo "[$(date +%H:%M:%S)] _ev2_run_failed_1825          OK"
wait $PID_REST  && echo "[$(date +%H:%M:%S)] _autres_vides+non_benzenoid_generator OK"

END=$(date +%s)
DURATION=$((END - START))
echo ""
echo "=== CLEANUP END $(date) (duree=${DURATION}s) ==="
echo ""
echo "=== Etat final ~/projet/ ==="
ls -la ~/projet/
echo ""
echo "=== Espace disque ==="
df -h ~
echo ""
echo "=== Marqueur fin ==="
date +%s > ~/_cleanup_projet.done
echo "Fichier marqueur cree : ~/_cleanup_projet.done"
