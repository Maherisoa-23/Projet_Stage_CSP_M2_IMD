@echo off
setlocal enabledelayedexpansion

echo === Integration du corpus dans l'application ===
echo.
echo IMPORTANT : ce script attend un fichier corpus_only_for_chimiste.db
echo a cote de lui ^(recu separement, ex. cle USB -- trop volumineux pour
echo GitHub^). Si ce fichier n'est pas encore present dans ce dossier,
echo copiez-le d'abord, puis relancez ce script.
echo.
pause

cd /d "%~dp0"

echo [1/6] Verification que Docker tourne...
docker info >nul 2>&1
if errorlevel 1 (
    echo ERREUR : Docker Desktop ne repond pas. Lancez Docker Desktop et reessayez.
    pause
    exit /b 1
)

echo [2/6] Verification que l'application est demarree...
docker compose ps --format "{{.Name}}" > "%TEMP%\container_name.txt" 2>nul
set /p CONTAINER=<"%TEMP%\container_name.txt"
del "%TEMP%\container_name.txt" >nul 2>&1

if "%CONTAINER%"=="" (
    echo L'application n'est pas demarree. Lancement...
    docker compose up -d
    if errorlevel 1 (
        echo ERREUR : impossible de demarrer l'application ^(docker compose up -d^).
        pause
        exit /b 1
    )
    timeout /t 5 >nul
    docker compose ps --format "{{.Name}}" > "%TEMP%\container_name.txt" 2>nul
    set /p CONTAINER=<"%TEMP%\container_name.txt"
    del "%TEMP%\container_name.txt" >nul 2>&1
)

if "%CONTAINER%"=="" (
    echo ERREUR : impossible de determiner le nom du container. Verifiez "docker compose ps" manuellement.
    pause
    exit /b 1
)

echo Container detecte : %CONTAINER%
echo.

if not exist "corpus_only_for_chimiste.db" (
    echo ERREUR : corpus_only_for_chimiste.db introuvable a cote de ce script.
    pause
    exit /b 1
)

echo [3/6] Copie des fichiers dans le container ^(peut prendre plusieurs minutes, ~11 Go^)...
docker cp merge_corpus.py %CONTAINER%:/tmp/merge_corpus.py
if errorlevel 1 goto :error
docker cp corpus_only_for_chimiste.db %CONTAINER%:/tmp/corpus.db
if errorlevel 1 goto :error

echo.
echo [4/6] Integration en cours ^(plusieurs minutes, plusieurs millions de lignes^)...
docker exec %CONTAINER% python3 /tmp/merge_corpus.py --source /tmp/corpus.db
if errorlevel 1 goto :error

echo.
echo [5/6] Nettoyage des fichiers temporaires...
docker exec %CONTAINER% rm -f /tmp/corpus.db /tmp/merge_corpus.py

echo.
echo [6/6] Redemarrage de l'application...
docker compose restart

echo.
echo === TERMINE ===
echo Ouvrez http://localhost:8765/explorer dans votre navigateur pour verifier.
echo Vos jobs existants dans /designer n'ont pas ete touches.
pause
exit /b 0

:error
echo.
echo ERREUR pendant l'integration. Notez le message ci-dessus et contactez
echo la personne qui vous a remis cette cle USB avant de recommencer.
pause
exit /b 1
