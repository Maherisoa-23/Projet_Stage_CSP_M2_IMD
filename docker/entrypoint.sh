#!/bin/sh
# Point d'entree du conteneur : verifie que les dependances systeme critiques
# (xtb, java) sont accessibles avant de lancer le serveur. Echoue vite et
# clairement plutot que de laisser un chimiste decouvrir l'erreur seulement
# au moment de cliquer "Validation xTB" dans l'UI.
set -e

echo "=== Verification des dependances ==="

if ! command -v xtb >/dev/null 2>&1; then
    echo "ERREUR : binaire 'xtb' introuvable dans le PATH." >&2
    exit 1
fi
echo "xtb  : $(xtb --version 2>&1 | head -n 1 || echo present)"

if ! command -v java >/dev/null 2>&1; then
    echo "ERREUR : 'java' introuvable dans le PATH (requis par le solveur CSP Choco)." >&2
    exit 1
fi
echo "java : $(java -version 2>&1 | head -n 1)"

mkdir -p /app/data/output/designer_jobs
echo "data : /app/data (volume persistant)"
echo "==================================="

exec "$@"
