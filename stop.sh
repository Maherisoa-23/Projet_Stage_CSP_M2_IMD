#!/bin/sh
# Arrete le designer (Mac/Linux). Les donnees restent sauvegardees.
cd "$(dirname "$0")"
docker compose down
echo
echo "Designer arrete. Vos molecules restent sauvegardees pour le prochain lancement."
