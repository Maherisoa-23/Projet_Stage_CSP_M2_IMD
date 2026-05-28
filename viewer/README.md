# Viewer CSP — explorateur SQLite + Flask multi-datasets

Viewer unifié pour explorer **tous les datasets h3 → h9** dans une seule
base SQLite (`db_all.db`). Architecture pensée pour passer à l'échelle
(h9 ≈ 1,5 M solutions) sans casser le navigateur, et pour brancher des
analyses futures (Kekulé, Clar, NICS, …) via des tables annexes liées
par `(h, config, mol, sol_idx)`.

- **Backend** : SQLite + serveur Flask local.
- **Frontend** : SPA en JS vanilla, lazy-loading par requête API,
  sélecteur de dataset, pagination, filtres, loading screens.
- **Données brutes** : restent dans `cluster_results/h{N}/` ou
  `csp_solver/experiments/output/h{N}/` ; on n'y touche pas, on indexe.

## Structure

```
csp_solver/experiments/csp_viewer/
├── schema.sql           # schéma SQLite (PK = (h, config, mol))
├── build_db.py          # construit/met à jour db_all.db
├── update_db.py         # rescan ciblé d'un sous-ensemble de mols
├── server.py            # serveur Flask (API JSON + page)
├── templates/index.html # SPA
├── static/style.css
└── static/app.js
```

## Usage

### 1. Construire la base

Depuis la racine du projet, en une commande qui ramasse tout ce qui est
disponible localement :

```powershell
python csp_solver/experiments/csp_viewer/build_db.py --auto-detect
```

Ou explicitement :

```powershell
python csp_solver/experiments/csp_viewer/build_db.py --h h3,h4,h5,h6,h7,h8,h9
```

Options principales :
- `--h h3,h4,...`        : liste de datasets à traiter (ou `--auto-detect`).
- `--root-pattern PAT`   : motif d'emplacement, par exemple
                            `'cluster_results/{h}'`. Par défaut, le script
                            essaie `cluster_results/{h}` puis
                            `csp_solver/experiments/output/{h}`.
- `--db chemin/db.db`    : où écrire (défaut `db_all.db` à côté du script).
- `--append`             : mode incrémental — ne rebuild **que** les
                            datasets ciblés sans toucher au reste.
- `--processes K`        : workers parallèles (défaut CPU - 1).
- `--limit N`            : ne traite que N (config, mol) par dataset (debug).

Workflow recommandé pour h6-h9 (gros volumes, NTFS lent) :

```bash
# 1. Build sur cluster (ext4 + 30 cores ≈ 5 min)
ssh 192.168.200.58
cd /home/COALA/ramaherisoa/projet
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz
python csp_solver/experiments/csp_viewer/build_db.py \
    --h h6,h7,h8,h9 \
    --root-pattern '_{h}_run/output/{h}' \
    --db /tmp/db_partial.db \
    --processes 30
exit

# 2. Rapatrier la portion h6-h9
scp 192.168.200.58:/tmp/db_partial.db csp_solver/experiments/csp_viewer/db_all.db

# 3. Compléter localement avec h3-h5 (rapide)
python csp_solver/experiments/csp_viewer/build_db.py --h h3,h4,h5 --append
```

Pour h3-h5 only (ou tout en local si tu acceptes l'attente) :

```powershell
python csp_solver/experiments/csp_viewer/build_db.py --auto-detect
```

### 2. Lancer le serveur

```powershell
python csp_solver/experiments/csp_viewer/server.py
```

Puis http://127.0.0.1:8765 dans le navigateur.

Options :
- `--db chemin`         (défaut `db_all.db` à côté du script).
- `--host`, `--port`    (défaut `127.0.0.1:8765`).
- `--debug`             mode dev Flask (auto-reload).

### 3. Naviguer

- **Sélecteur de dataset** dans le header → bascule h3 ↔ h4 ↔ … ↔ h9.
- **Dashboard** : cartes par configuration avec compteurs (validées /
  géom. infaisables / plans / non plans).
- Cliquer une carte → liste des molécules paginée. Recherche par nom,
  tri par plans / sols / angle min.
- Cliquer une molécule → liste des solutions, filtre par défaut
  « plans uniquement », tri par angle croissant. Liens directs vers les
  xyz (`source.xyz` et `md_final_opt.xyz`) servis par le serveur.

## Endpoints API

- `GET /api/datasets`                                       → liste des h disponibles.
- `GET /api/summary?h=hN`                                   → stats par config (filtre h).
- `GET /api/molecules?h=&config=&search=&page=&size=&sort=` → mols paginées.
- `GET /api/solutions?h=&config=&mol=&filter=&page=&size=&sort=` → sols paginées.
- `GET /api/sol/<id>`                                       → détails d'une solution.
- `GET /file?path=<chemin relatif>`                         → xyz/json/inp/log depuis
  le project root (vérifie path traversal et extension).

## Sémantique des compteurs

Pour chaque `(h, config, mol)`, trois compteurs co-existent :

- **`n_solutions_csp`** : nombre de solutions trouvées par le CSP
  (énumération combinatoire pure, sans contrainte 3D).
- **`n_md_completed`** : sols dont la reconstruction 3D **et** la
  validation xTB ont réussi → pris en compte dans `n_plans` / `n_non_plans`.
- **`n_geom_infeasible`** : sols **CSP-valides mais géométriquement
  inaccessibles**. La reconstruction lève `ValueError` (typiquement :
  pentagone/heptagone demandé sur un hexagone trop contraint, pattern
  `(1,1,1,1,1,0)`). Le sol_dir est créé sur disque mais reste **vide**
  (pas de `source.xyz`). C'est le comportement de `main.py` du run
  cluster — pas un timeout, pas un bug, juste une impossibilité
  topologique.
- **`n_xtb_failed`** : sols dont la reconstruction a réussi (source.xyz
  présent) mais xTB n'a pas convergé. Très rare en pratique sur h6-h8,
  un peu plus fréquent sur h9 (structures très tendues).

L'invariant est :

```
n_solutions_csp ≈ n_md_completed + n_geom_infeasible + n_xtb_failed
```

**Important pour h9** : avec les flags `no-freeze` et `no-table`, le CSP
accepte une part importante de solutions géométriquement infaisables —
jusqu'à ~75% sur certaines mols. Ce **n'est pas un manque** ; ces sols
ne sont juste pas physiquement réalisables.

## MAJ incrémentale via `update_db.py`

Si tu modifies ciblement quelques mols (ex. re-téléchargement partiel),
pas besoin de rebuild :

```powershell
# Une mol précise
python csp_solver/experiments/csp_viewer/update_db.py --h h9 --config X --mol Y

# Tout un dataset
python csp_solver/experiments/csp_viewer/update_db.py --h h7 --all

# Tout (équivalent build_db --append, mais ré-itère mol par mol)
python csp_solver/experiments/csp_viewer/update_db.py --all
```

Le script supprime les anciennes lignes `solutions` ciblées, re-scanne le
disque, réinsère, et recalcule les stats agrégées. Idempotent.

## Notes techniques

- **Re-build complet** : `build_db.py` sans `--append` efface la DB
  existante. Avec `--append`, seuls les datasets cibles sont écrasés.
- **PK et index** : `(h, config, mol)` partout. Index supplémentaires
  sur `(h, config, mol, planar)` et `(h, config, mol, angle_deg)` pour
  les pages paginées avec tri par angle. Une requête typique répond en
  quelques ms.
- **Sécurité** : `127.0.0.1` only par défaut. Ne pas exposer sans auth.
- **Performance NTFS** : un build complet h3-h9 sur Windows prend des
  heures. Préférer construire sur cluster (ext4 + multiprocessing) puis
  rapatrier la DB.

## Évolutions prévues

- Visualisation 3D des géométries (py3Dmol côté client) — viewer pop-up
  au clic sur une solution.
- Tables annexes pour propriétés topologiques :
  - `kekule_structures(h, config, mol, sol_idx, structure_idx, ...)`
  - `clar_indices(h, config, mol, sol_idx, ring_idx, sextet, ...)`
  - `nics_values(h, config, mol, sol_idx, ring_idx, nics_zz, ...)`
  Calculées par scripts dédiés (topologiques rapides ou via xTB/DFT
  selon la grandeur), insérées via `INSERT OR REPLACE` pour rester
  idempotentes.
- Vue de comparaison cross-dataset (h × config × propriété) sur la même
  page.
