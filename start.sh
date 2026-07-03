#!/bin/sh
# Lance le designer (Mac/Linux). Double-clic ou `./start.sh` dans un terminal.
# Necessite Docker Desktop (Mac) ou Docker Engine (Linux) installe et demarre.

cd "$(dirname "$0")"

echo "=== Verification de Docker ==="
if ! command -v docker >/dev/null 2>&1; then
    echo
    echo "ERREUR : Docker n'est pas installe."
    echo "Installez Docker Desktop : https://www.docker.com/products/docker-desktop/"
    echo "puis relancez ce script."
    exit 1
fi

echo "=== Demarrage du designer (peut prendre plusieurs minutes la 1ere fois) ==="
docker compose up -d --build

echo
echo "=== Designer demarre ==="
echo "Ouverture du navigateur sur http://localhost:8765/"
sleep 2

if command -v open >/dev/null 2>&1; then
    open http://localhost:8765/        # macOS
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:8765/     # Linux
else
    echo "Ouvrez manuellement : http://localhost:8765/"
fi

echo
echo "Pour arreter : ./stop.sh ou 'docker compose down'"
