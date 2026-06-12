# csp_solver

Solveur CSP (PyCSP3 + ACE) pour generer des affectations 5/6/7 sur des
squelettes benzenoides, et wrappers xTB pour la validation 3D.

## 2 points d'entree

| Cas | Commande |
|---|---|
| **Debug local** (1 graph, 1 config) | `python -m csp_solver.main data/some.graph --enumerate-all` |
| **Production cluster** (run h3-h9, 3 configs) | `python -m csp_solver.final.run setup/dispatch/status ...` |

## Modules

```
csp_solver/
  main.py             Point d'entree CLI local (debug, 1 graph)
  sanity_benzenoid.py Sanity check : xtb sur benzenoide pur (baseline)
  config.py           Constantes globales (paths, seuils)
  presets.py          Catalogue des presets CSP (preset_name -> contraintes)

  utils/              Parsing, modele CSP, contraintes, validation
    parser.py            parse fichier .graph
    preprocessing.py     pre-traitement (frozen vertices, automorphismes)
    model.py             definition CSP (build_and_solve)
    table.py             table de voisinage
    validate.py          test planarite ACP (xyz -> angle deg)
    validation/          strategies multi-runs et det-opt

  xtb/                Wrappers xTB
    optimizer.py        xtb --opt avec perturbation z aleatoire (multi-runs)
    det_opt.py          xtb --opt avec perturbation z analytique (deterministe)
    md.py               (alias retro-compat -> det_opt)

  planarity/          Test de planarite par PCA

  reconstruction/     Geometrie 3D depuis (graph, solution CSP)

  final/              RUN FINAL CLUSTER (production, h3-h9 x 3 configs)
    run.py              CLI : setup / dispatch / status
    dispatcher.py       orchestration SSH multi-workers
    db.py               schema SQLite + helpers
    configs.py          definitions C1 / C2 / C3
    enumerate.py        wrapper CSP pour le run final
    worker.py           processus worker SSH (lance par dispatcher)
    xtb_metrics.py      parsing energy/HOMO-LUMO depuis stdout xtb

  analysis/           PIPELINE D'ANALYSE POST-RUN (features + Ctopo)
    compute_adjacencies.py        adj_55/57/77 + n_sum
    compute_combined_features.py  rayon-2 + topologie squelette
    extract_boundary_motifs.py    motifs de bord w=4/5
    materialize_ctopo.py          config Ctopo dans DB viewer
    postprocess_clar_rbo.py       annotations Clar/RBO

    exploration/                  scripts data-mining (chronologie scientifique)

  data/               Fichiers de donnees (table_voisinage.json)
```

## Voir aussi

- `doc/PIPELINE.md` : architecture du pipeline
- `doc/CONTRAINTES.md` : modele CSP detaille
- `doc/ARCHITECTURE_FINAL_RUN.md` : run cluster
- `doc/experimentation.md` : synthese des configs (C1, C2, C3, Ctopo)
