#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Integration du corpus dans l'application ==="
echo

echo "[1/6] Verification que Docker tourne..."
if ! docker info >/dev/null 2>&1; then
    echo "ERREUR : Docker ne repond pas. Lancez Docker Desktop (ou le daemon Docker) et reessayez."
    exit 1
fi

echo "[2/6] Verification que l'application est demarree..."
CONTAINER=$(docker compose ps --format "{{.Name}}" 2>/dev/null | head -1)

if [ -z "$CONTAINER" ]; then
    echo "L'application n'est pas demarree. Lancement..."
    docker compose up -d
    sleep 5
    CONTAINER=$(docker compose ps --format "{{.Name}}" 2>/dev/null | head -1)
fi

if [ -z "$CONTAINER" ]; then
    echo "ERREUR : impossible de determiner le nom du container. Verifiez 'docker compose ps' manuellement."
    exit 1
fi

echo "Container detecte : $CONTAINER"
echo

if [ ! -f "corpus_only_for_chimiste.db" ]; then
    echo "ERREUR : corpus_only_for_chimiste.db introuvable a cote de ce script."
    exit 1
fi

echo "[3/6] Copie des fichiers dans le container (peut prendre plusieurs minutes, ~11 Go)..."
docker cp merge_corpus.py "$CONTAINER:/tmp/merge_corpus.py"
docker cp corpus_only_for_chimiste.db "$CONTAINER:/tmp/corpus.db"

echo
echo "[4/6] Integration en cours (plusieurs minutes, plusieurs millions de lignes)..."
docker exec "$CONTAINER" python3 /tmp/merge_corpus.py --source /tmp/corpus.db

echo
echo "[5/6] Nettoyage des fichiers temporaires..."
docker exec "$CONTAINER" rm -f /tmp/corpus.db /tmp/merge_corpus.py

echo
echo "[6/6] Redemarrage de l'application..."
docker compose restart

echo
echo "=== TERMINE ==="
echo "Ouvrez http://localhost:8765/explorer dans votre navigateur pour verifier."
echo "Vos jobs existants dans /designer n'ont pas ete touches."
