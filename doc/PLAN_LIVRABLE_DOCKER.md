# Plan — Livrable Docker pour les chimistes

Objectif : empaqueter le **designer** (dessin de molécules 5/7 + génération CSP +
validation xTB + visualisation 3D / Kekulé / RBO / Clar / graphe dual) dans une
image Docker que les chimistes lancent en local, sans gérer les dépendances.

---

## 0. État des lieux (audité)

| Composant | Détail | Implication Docker |
|---|---|---|
| Python | 3.11+ | image base `python:3.11-slim` |
| Solveur CSP | **Choco** (Java) via pycsp3 | besoin d'un **JRE** dans l'image |
| pycsp3 | 2.5.1 (embarque les jars Choco/ACE) | `pip install`, jars inclus |
| xTB | binaire `>=6.7`, appelé par `subprocess(["xtb", ...])` (PATH) | **binaire xtb à embarquer** |
| networkx, numpy, lxml, flask | pip | simple |
| DB designer | tables `designer_jobs/solutions/xyz_files` **créées à la demande** | **DB vide au départ**, pas les 3.9 GB |
| DB exploration h3-h9 | `final_h3_h9.db` = **3.9 GB** | **EXCLUE du livrable designer** (option séparée) |

**Décision structurante** : le livrable est le **designer seul**. Il démarre sur
une DB vide et les chimistes créent leurs molécules. On n'embarque PAS les 3.9 GB
de résultats pré-calculés (c'est un autre usage : l'explorateur de corpus).

---

## 1. Périmètre du livrable

**Inclus :**
- Serveur Flask (`viewer/server.py`) + blueprint designer + blueprint molviz
- Solveur CSP (`csp_solver/`) avec Choco
- xTB pour la validation (méthode "Validation xTB")
- Visualisations : 3D, Kekulé/Radicalaires, RBO, Clar, graphe dual
- Les 2 modes : Skip (rapide) et Validation xTB
- DB vierge (tables designer auto-créées)

**Exclus :**
- L'explorateur de corpus h3-h9 (DB 3.9 GB) — usage différent, livrable séparé si besoin
- Le mode cluster SSH (inutile en conteneur local)
- Les scripts de génération de figures / mémoire (playwright)

---

## 2. Architecture de l'image

```
Image Docker (base: python:3.11-slim)
├── JRE headless (default-jre-headless)      ← pour Choco
├── xtb (binaire + libs)                      ← validation
├── Python deps (pip install requirements)    ← pycsp3, flask, networkx...
├── Code app (csp_solver/ + viewer/)          ← COPY
├── DB vide initialisée au 1er démarrage      ← volume nommé
└── EXPOSE 8765 ; CMD server.py --host 0.0.0.0
```

**Persistance** : un **volume Docker** monte `/data` pour la DB designer +
`viewer/output/` (xyz générés), pour que les molécules survivent à l'arrêt du
conteneur.

---

## 3. Étapes d'implémentation

### Étape 1 — Préparer le code pour le conteneur
- Vérifier que `server.py` accepte `--host 0.0.0.0` et `--db /data/designer.db`
- Path de sortie configurable (`viewer/output/` → `/data/output/`)
- Variable d'env pour désactiver le mode cluster (`DESIGNER_CLUSTER_ENABLED=0`)
- S'assurer qu'au 1er lancement avec DB absente, les tables designer se créent
  (déjà le cas via `CREATE TABLE IF NOT EXISTS`, à confirmer pour une DB neuve)

### Étape 2 — Sourcer le binaire xTB
- xTB officiel : release Linux statique (github grimme-lab/xtb)
- Le télécharger dans l'image (multi-stage build) et le mettre dans le PATH
- Tester `xtb --version` dans le conteneur

### Étape 3 — Écrire le Dockerfile
- Multi-stage : (a) stage builder qui télécharge/extrait xtb, (b) stage final
  slim qui copie xtb + installe JRE + pip deps + code
- Minimiser la taille (slim, `--no-cache-dir`, purge apt)
- `HEALTHCHECK` sur `http://localhost:8765`

### Étape 4 — docker-compose + script de lancement
- `docker-compose.yml` : service unique, volume `/data`, port 8765:8765
- Script `start.bat` (Windows) et `start.sh` (Mac/Linux) qui font
  `docker compose up` puis ouvrent le navigateur sur `localhost:8765`
- Pour le chimiste : double-clic sur le script

### Étape 5 — Tester le conteneur de bout en bout
- Build, run, ouvrir le designer
- Dessiner une molécule, générer en **Skip** → visualiser
- Générer en **Validation xTB** → vérifier que xTB tourne dans le conteneur
- Vérifier 3D / Kekulé / RBO / Clar / dual

### Étape 6 — Documentation utilisateur
- `README_CHIMISTES.md` : installer Docker Desktop, lancer le script, ce qu'on
  peut faire. Captures d'écran. Pas de jargon technique.

---

## 4. Points d'attention / risques

| Risque | Mitigation |
|---|---|
| **Taille image** (JRE + xtb peuvent peser) | multi-stage, base slim ; cible < 1.5 GB |
| **xTB licence/redistribution** | xTB est LGPL → redistribuable ; vérifier au packaging |
| **Java + Choco dans slim** | tester tôt (étape 1-2) que pycsp3 trouve le JRE |
| **Friction Docker Desktop** | script de lancement + doc avec captures ; envisager une vidéo courte |
| **Performance xTB en conteneur** | OK pour h≤8 ; signaler que h9 est plus lent |
| **Windows : chemins/volumes** | tester le volume Docker sur Windows (WSL2 backend) |

---

## 5. Évolutions possibles (hors périmètre initial)

- **Déploiement web** : la même image tourne sur un serveur (AMU/LIS) → option
  web hébergée sans re-packager. C'est l'avantage clé d'avoir choisi Docker.
- **Image "explorateur"** : variante avec la DB 3.9 GB montée en volume (pas dans
  l'image) pour ceux qui veulent explorer le corpus pré-calculé.
- **Image multi-arch** (amd64 + arm64 pour Mac M1/M2) si des chimistes sont sur Mac.

---

## 6. Livrables finaux

1. `Dockerfile` + `docker-compose.yml`
2. `start.bat` / `start.sh`
3. `README_CHIMISTES.md` (installation + usage)
4. Image publiée (Docker Hub privé, ou `.tar` via `docker save` pour transfert
   direct sans registry)
5. Note de version (ce que fait l'outil, limites connues : skip vs xTB, h9 lent)

---

## 7. Estimation

| Phase | Effort indicatif |
|---|---|
| Étapes 1-2 (préparer code + xtb) | ~0.5 j |
| Étape 3 (Dockerfile) | ~0.5 j |
| Étape 4 (compose + scripts) | ~0.25 j |
| Étape 5 (tests bout en bout) | ~0.5 j |
| Étape 6 (doc chimistes) | ~0.5 j |
| **Total** | **~2-2.5 j** |

Le gros du risque est concentré sur les étapes 1-2 (JRE + xtb qui cohabitent et
fonctionnent dans le slim). À valider en premier par un POC minimal.
