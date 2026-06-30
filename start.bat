@echo off
REM Lance le designer (Windows). Double-clic sur ce fichier suffit.
REM Necessite Docker Desktop installe et demarre.

cd /d "%~dp0"

echo === Verification de Docker ===
docker --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERREUR : Docker n'est pas installe ou n'est pas demarre.
    echo Installez Docker Desktop : https://www.docker.com/products/docker-desktop/
    echo puis relancez ce script.
    pause
    exit /b 1
)

echo === Demarrage du designer (peut prendre plusieurs minutes la 1ere fois) ===
docker compose up -d --build

if errorlevel 1 (
    echo.
    echo ERREUR au demarrage. Voir les messages ci-dessus.
    pause
    exit /b 1
)

echo.
echo === Designer demarre ===
echo Ouverture du navigateur sur http://localhost:8765/designer
timeout /t 2 >nul
start http://localhost:8765/designer

echo.
echo Pour arreter : executez stop.bat ou "docker compose down"
pause
