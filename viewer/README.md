# viewer

Serveur Flask local pour explorer les datasets CSP, visualiser les molecules
en 3D (3Dmol.js), et concevoir interactivement de nouveaux benzenoides
(designer).

## Demarrage rapide

```bash
# Depuis la racine du repo
python server.py --db experiments/final/final_h3_h9.db --port 8765
# -> http://127.0.0.1:8765
```

Le wrapper `server.py` racine delegue a `viewer/server.py`.

## Structure

```
viewer/
  server.py           Serveur Flask + API (routes /api/datasets, /summary, /molecules, ...)
  build_db.py         Construction du db_all.db a partir d'outputs cluster
  ingest_xyz.py       Inserer/MAJ des fichiers XYZ dans la DB
  schema.sql          Schema canonique de la DB (configs, molecules, solutions, xyz_files)

  static/             Frontend SPA
    app.js              Navigation : dashboard -> config -> mol -> sol
    style.css           Styles
    config_descriptions.js  Descriptifs UI des configs (C1/C2/C3/Ctopo)

  templates/          Pages HTML (index, designer)

  molviz/             Visualisation 3D + analyse electronique
    api.py              Routes /api/mol3d, /kekule_list, /clar_list, /rbo
    bonds.py            Detection liaisons par distance + SSSR
    kekule.py           Enumeration structures de Kekule
    clar.py             Couvertures de Clar (Option A et B)
    rbo.py              Ring Bond Orders (Pauling)
    static/molviz.js    Modal 3D + overlays Kekule/Clar
    static/molviz.css

  designer/           Designer interactif de benzenoides
    api.py              Routes /api/designer/*
    runner.py           Lance un job CSP a la demande (local ou cluster)
    cluster_runner.py   Variante cluster (SSH + xtb distant)
    solutions_db.py     Stockage des sols designer
    jobs.py             Gestion des jobs (state machine)
    static/designer.js  Frontend canvas hex
    tests/              test_cluster_xtb, test_phase2_smoke (smoke tests)
    scripts/            cleanup_old_workdirs (purge workdirs)

  migrations/         Migrations de schema DB
    final_to_viewer.py  Convertit final_h3_h9.db (run schema) -> viewer schema
```

## API HTTP

| Route | But |
|---|---|
| `GET /` | UI principale (SPA) |
| `GET /designer` | Designer interactif |
| `GET /api/datasets` | Liste des h disponibles |
| `GET /api/summary?h=hN` | Stats par config (counts + median + max angle) |
| `GET /api/molecules?h=&config=` | Liste molecules d'une config |
| `GET /api/solutions?h=&config=&mol=` | Solutions d'une molecule |
| `GET /api/mol3d?path=...xyz` | Atoms + bonds + cycles + Kekule (matching unique) |
| `GET /api/kekule_list?path=...xyz` | Liste de structures de Kekule (cap par defaut 200) |
| `GET /api/clar_list?path=...xyz` | Couvertures de Clar (Option A + Option B) |
| `GET /api/rbo?path=...xyz` | Ring Bond Orders Pauling |
| `GET /api/designer/jobs/...` | API designer (creation, status, sols) |
| `GET /file?path=...` | Servir un XYZ (filesystem ou DB xyz_files VIEW) |

## Tests molviz (rapide)

```bash
python -m viewer.molviz.test_clar
python -m viewer.molviz.test_kekule_enum
python -m viewer.molviz.test_rbo
```

## Architecture notes

- **Frontend** : JS vanilla en IIFE (pas de bundler, pas de framework). Volontaire
  pour eviter une chaine de build dans un projet de stage.
- **Cache** : routes molviz utilisent `@lru_cache(maxsize=256)` cote serveur
  pour eviter de recalculer Kekule/Clar/RBO. Cache memoire process, perdu au restart.
- **Path resolution** : `_resolve_local_path` dans `server.py` gere les chemins
  cluster (`_hN_run/output/...`) et locaux (`cluster_results/hN/...`) de maniere
  transparente.

## Voir aussi

- `doc/ANALYSE_ELECTRONIQUE.md` : Kekule / Clar / RBO en detail
- `doc/DESIGNER_CLUSTER_DB.md` : mode cluster du designer
