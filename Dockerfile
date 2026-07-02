# =====================================================================
#  Image Docker du designer (livrable chimistes).
#
#  Empaquette : Python + pycsp3 (Choco/ACE embarques, JRE requis) + xTB
#  (validation de planarite) + le serveur Flask (viewer/server.py, route
#  /designer). Demarre en mode --designer-only : DB designer vide/neuve,
#  PAS l'explorateur de corpus h3-h9 (qui demande une DB de plusieurs Go,
#  hors perimetre de ce livrable).
#
#  Build :
#      docker build -t csp-designer .
#  Run (voir aussi docker-compose.yml) :
#      docker run -p 8765:8765 -v csp_designer_data:/app/data csp-designer
#
#  Le volume de donnees est monte SOUS /app (racine du code, WORKDIR) et non
#  a la racine /data : le code du designer (api.py, runner.py, solutions_db.py,
#  build_db.py) calcule des chemins "relatifs a project_root" via
#  Path.relative_to(project_root) a plusieurs endroits (best_xyz_path,
#  ingestion DB, xyz_path des jobs...). Si le volume de donnees sortait de
#  project_root (ex. /data a la racine du conteneur), ces relative_to()
#  levent ValueError -> 500 sur /api/designer/jobs/<id>/solutions et le
#  viewer 3D ne charge plus rien. Garder le volume sous /app evite de
#  toucher a cette hypothese partagee par tout le code.
# =====================================================================

# ---------- Stage 1 : telechargement du binaire xTB ----------
FROM debian:bookworm-slim AS xtb-fetch

ARG XTB_VERSION=6.7.1
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /xtb-dl
RUN curl -fsSL -o xtb.tar.xz \
        "https://github.com/grimme-lab/xtb/releases/download/v${XTB_VERSION}/xtb-${XTB_VERSION}-linux-x86_64.tar.xz" \
    && tar -xJf xtb.tar.xz \
    && rm xtb.tar.xz

# ---------- Stage 2 : image finale ----------
FROM python:3.11-slim AS final

# JRE headless : requis par pycsp3 pour invoquer Choco (jar embarque dans
# pycsp3, mais l'execution java -cp ... necessite un JRE sur le systeme).
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Binaire xTB, copie depuis le stage de telechargement.
# L'archive officielle s'extrait dans un dossier nomme "xtb-dist/" (verifie
# sur la release 6.7.1) ; le glob xtb-* couvre ce nom et d'eventuelles
# variantes futures (ex. xtb-6.7.1/) sans casser le build si grimme-lab
# renomme le dossier interne.
COPY --from=xtb-fetch /xtb-dl/xtb-*/bin/xtb /usr/local/bin/xtb
RUN chmod +x /usr/local/bin/xtb

WORKDIR /app

# Dependances Python d'abord (cache Docker : rebuild rapide si seul le code change).
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# Code de l'application.
COPY csp_solver/ csp_solver/
COPY viewer/ viewer/

# Variables d'environnement par defaut (mode designer-only, pas de cluster SSH).
# Le volume /app/data reste SOUS project_root (/app) -- voir la note en tete
# de fichier sur Path.relative_to(project_root).
ENV DESIGNER_CLUSTER_ENABLED=0 \
    DESIGNER_OUTPUT_DIR=/app/data/output/designer_jobs \
    DESIGNER_DB_PATH=/app/data/designer.db \
    PYTHONUNBUFFERED=1

# Volume pour la persistance (DB + outputs des jobs designer).
VOLUME /app/data

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/designer', timeout=3)" || exit 1

# Verifie au demarrage que xtb et java sont bien accessibles (echec rapide
# et explicite si l'image est mal construite, plutot qu'une erreur cachee
# au premier clic "Validation xTB" du chimiste).
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "viewer/server.py", "--host", "0.0.0.0", "--port", "8765", "--designer-only"]
