#!/bin/bash
# Deploiement code + graphs vers 192.168.200.49 (frontale cluster).
# A lancer depuis la racine du projet local.

set -e

CLUSTER=192.168.200.49
PROJECT_ROOT_REMOTE=~/projet

echo "=== Deploiement code csp_solver/ vers $CLUSTER:$PROJECT_ROOT_REMOTE ==="
# Sync csp_solver/ (overwrite mais preserve les autres fichiers)
scp -r csp_solver $CLUSTER:$PROJECT_ROOT_REMOTE/
echo "  -> csp_solver/ OK"

echo ""
echo "=== Deploiement data/ (h3-h5) ==="
scp -r data $CLUSTER:$PROJECT_ROOT_REMOTE/
echo "  -> data/ OK"

echo ""
echo "=== Deploiement experiments/v1/plane/benzdb/ (h6-h9) ==="
ssh $CLUSTER "mkdir -p $PROJECT_ROOT_REMOTE/experiments/v1/plane"
scp -r experiments/v1/plane/benzdb $CLUSTER:$PROJECT_ROOT_REMOTE/experiments/v1/plane/
echo "  -> benzdb/ OK"

echo ""
echo "=== Verification cote cluster ==="
ssh $CLUSTER "
  echo 'csp_solver/ files:' \$(find $PROJECT_ROOT_REMOTE/csp_solver -maxdepth 2 -name '*.py' | wc -l)
  echo 'data/h3 :' \$(ls $PROJECT_ROOT_REMOTE/data/h3/*.graph 2>/dev/null | wc -l) 'graphs'
  echo 'data/h4 :' \$(ls $PROJECT_ROOT_REMOTE/data/h4/*.graph 2>/dev/null | wc -l) 'graphs'
  echo 'data/h5 :' \$(ls $PROJECT_ROOT_REMOTE/data/h5/*.graph 2>/dev/null | wc -l) 'graphs'
  echo 'benzdb/h6 :' \$(ls $PROJECT_ROOT_REMOTE/experiments/v1/plane/benzdb/h6/*.graph 2>/dev/null | wc -l) 'graphs'
  echo 'benzdb/h7 :' \$(ls $PROJECT_ROOT_REMOTE/experiments/v1/plane/benzdb/h7/*.graph 2>/dev/null | wc -l) 'graphs'
  echo 'benzdb/h8 :' \$(ls $PROJECT_ROOT_REMOTE/experiments/v1/plane/benzdb/h8/*.graph 2>/dev/null | wc -l) 'graphs'
  echo 'benzdb/h9 :' \$(ls $PROJECT_ROOT_REMOTE/experiments/v1/plane/benzdb/h9/*.graph 2>/dev/null | wc -l) 'graphs'
"
echo "=== Deploiement OK ==="
