@echo off
REM Arrete le designer (Windows). Les donnees restent sauvegardees.
cd /d "%~dp0"
docker compose down
echo.
echo Designer arrete. Vos molecules restent sauvegardees pour le prochain lancement.
pause
