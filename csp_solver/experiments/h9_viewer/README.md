# Viewer h9 — explorateur SQLite + Flask

Viewer dédié au cas h9 (~1,5 M solutions, trop volumineux pour le viewer
HTML monolithique des autres tailles). Architecture :

- **Backend** : SQLite (h9.db) + serveur Flask local.
- **Frontend** : page unique avec routing JS, lazy-loading par requête API,
  pagination, filtres (plans / non plans / toutes), loading screens.
- **Données brutes** : restent dans `cluster_results/h9/` ; on n'y touche pas,
  on indexe seulement.

## Structure

```
csp_solver/experiments/h9_viewer/
├── schema.sql           # schéma SQLite
├── build_db.py          # construit h9.db depuis cluster_results/h9
├── update_db.py         # MAJ incrémentale (re-scan d'un sous-ensemble de mols)
├── server.py            # serveur Flask (API JSON + page)
├── templates/index.html # SPA
├── static/style.css
└── static/app.js
```

## Usage

### 1. Construire la base (une fois)

Depuis la racine du projet :

```powershell
python csp_solver/experiments/h9_viewer/build_db.py
```

Options :
- `--root cluster_results/h9` : où chercher les jobs (par défaut).
- `--db <chemin>` : où écrire la base (défaut `h9.db` à côté du script).
- `--limit N` : ne traite que N (config, mol) — tests rapides.
- `--processes K` : nombre de workers (défaut = CPU - 1).

Le scan calcule la planarité ACP de chaque `md_final_opt.xyz` et insère
~1,5 M lignes. Compter ~10–30 minutes selon la machine.

### 2. Lancer le serveur

```powershell
python csp_solver/experiments/h9_viewer/server.py
```

Puis ouvrir http://127.0.0.1:8765 dans le navigateur.

Options :
- `--db <chemin>` (défaut `h9.db` à côté du script).
- `--host`, `--port` (défaut `127.0.0.1:8765`).
- `--debug` : mode dev Flask (auto-reload).

### 3. Naviguer

- **Dashboard** : 8 cartes config avec compteurs et % de plans.
- Cliquer une carte → liste des molécules de la config (paginée 50/page).
  Filtre par nom, tri par plans/sols/angle min.
- Cliquer une molécule → liste des solutions, filtre par défaut « plans
  uniquement », tri par angle croissant. Liens directs vers les xyz
  (`source.xyz` et `md_final_opt.xyz`) servis par le serveur.

## Endpoints API

- `GET /api/summary` → stats par config + total mols uniques.
- `GET /api/molecules?config=&search=&page=&size=&sort=` → mols paginées.
- `GET /api/solutions?config=&mol=&filter=&page=&size=&sort=` → sols paginées.
- `GET /api/sol/<id>` → détails d'une solution.
- `GET /file?path=<chemin relatif>` → sert un xyz/json/inp depuis le project
  root (vérifie les bornes pour éviter le path traversal).

## Notes

- **Re-build** : la DB est réécrite à chaque build (le fichier est supprimé
  puis recréé). Idempotent.
- **Sécurité** : le serveur écoute sur `127.0.0.1` uniquement par défaut.
  Ne pas l'exposer sans authentification.
- **Performance** : indexes sur `(config, mol)` et `(config, mol, planar)`.
  Pour les requêtes de pagination + tri par angle, l'index `(config, mol,
  angle)` couvre le cas. Une requête typique répond en quelques ms.

## Sémantique des compteurs

Pour chaque (config, mol), trois compteurs co-existent :

- **`n_solutions_csp`** : nombre de solutions trouvées par le CSP (énumération
  combinatoire pure, sans contrainte 3D).
- **`n_md_completed`** : sols dont la reconstruction 3D **et** la validation
  xTB ont réussi → pris en compte dans `n_plans` / `n_non_plans`.
- **`n_geom_infeasible`** : sols **CSP-valides mais géométriquement
  inaccessibles**. La reconstruction lève `ValueError` (typiquement :
  pentagone/heptagone demandé sur un hexagone trop contraint, pattern
  `(1,1,1,1,1,0)`). Le sol_dir est créé sur disque mais reste **vide**
  (pas de `source.xyz`). C'est le comportement de `main.py` du run cluster
  initial — pas un timeout, pas un bug, juste une impossibilité topologique.
- **`n_xtb_failed`** : sols dont la reconstruction a réussi (source.xyz
  présent) mais xTB n'a pas convergé. Très rare en pratique sur h6-h8,
  un peu plus fréquent sur h9 (structures très tendues).

L'invariant est :
```
n_solutions_csp ≈ n_md_completed + n_geom_infeasible + n_xtb_failed
```

(approximatif car `n_solutions_csp` peut différer si le job cluster a été
relancé partiellement.)

**Important pour h9** : avec les flags `no-freeze` et `no-table`, le CSP
accepte une part importante de solutions géométriquement infaisables.
Sur h9 / `no-freeze_no-table`, on peut avoir jusqu'à ~75% de
`n_geom_infeasible` sur certaines mols. Ce **n'est pas un manque** ; ces
sols ne sont juste pas physiquement réalisables.

## MAJ incrémentale via `update_db.py`

Si tu re-télécharges une partie de `cluster_results/h9/` (ex. correction
ciblée d'une molécule), pas besoin de re-builder toute la base. Cible
uniquement les mols touchées :

```powershell
# Une mol précise
python csp_solver/experiments/h9_viewer/update_db.py --config X --mol Y

# Toutes les mols (équivalent build_db, plus lent)
python csp_solver/experiments/h9_viewer/update_db.py --all
```

Le script supprime les anciennes lignes `solutions` pour la (config, mol),
re-scanne le disque, réinsère, et recalcule les stats agrégées de la config.
Idempotent.

## Limitations

- Pas de visualisation 3D des molécules (à brancher si besoin via py3Dmol
  côté client).
- Pas de comparaison croisée entre configs sur la même page (drill-down
  par config seulement). Possible à ajouter via une vue dédiée.
- DB recréée à chaque build : pour incrémental, ajouter un mode `--update`
  basé sur les timestamps `job_status.json`.
