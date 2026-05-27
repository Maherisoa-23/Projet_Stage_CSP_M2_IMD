# experiments_v2 — Phase expérimentale CSP avec contraintes additionnelles

Package isolé qui ajoute au modèle CSP existant **4 nouvelles contraintes
optionnelles** dérivées de l'analyse statistique de `analysis_v2/` sur les
890 270 solutions h6-h9.

## Pourquoi ?

L'analyse a montré deux lois empiriques fortes :

1. **Symétrie 5/7** : `|n_pent − n_hept| ≤ 1` → %plan = 25-43% ;
   `|n_pent − n_hept| ≥ 2` → %plan = 0-7%
2. **Pentagones en bord** : 0 pent en bord = 59% plan ; 5 pent en bord = 2% plan

→ En contraignant le solveur, on devrait **monter le %plan global**
(estimation : 27% → 50-65% sur h9) sans modifier le pipeline xTB/MD.

## Contraintes ajoutées

| Flag CLI | Sigle | Sémantique | Défaut quand actif |
|---|---|---|---|
| `--sym K` | C-SYM | `|n_pent − n_hept| ≤ K` | K = 1 |
| `--pb K` | C-PB | nb de v tels que x[v]=5 ET v ∈ boundary ≤ K | K = 2 |
| `--hb K` | C-HB | nb de v tels que x[v]=7 ET v ∈ boundary ≤ K | K = 3 |
| `--tot K` | C-TOT | nb de v tels que x[v] ∈ {5,7} ≤ K | K dépend du h |

Toutes désactivées par défaut. Activables individuellement ou en combinaison.

## Layout

```
experiments_v2/
├── README.md                  (ce fichier)
├── __init__.py
├── boundary_helper.py         détection des hex de bord du benzénoïde d'entrée
├── constraints/
│   ├── __init__.py
│   ├── symmetry.py           C-SYM
│   ├── boundary_caps.py      C-PB, C-HB
│   └── total_caps.py         C-TOT
├── csp_model.py              build_and_solve_v2 (CSP enrichi)
├── main.py                   entry CLI (--sym, --pb, --hb, --tot, --validate)
├── configs.py                5 configs prédéfinies pour batch
├── run_one_job.py            wrapper CSP + reconstruction + validation
└── cluster/
    ├── __init__.py
    ├── build_manifest.py
    ├── worker.py
    ├── finalize.py
    └── dispatcher.py
```

## Garanties anti-régression

- **Aucune modification** des fichiers de `csp_solver/`, `experiments/`,
  `csp_viewer/`, `analysis_v2/`, `molviz/`
- **Réutilise** `utils.parser`, `utils.preprocessing`, `utils.model`,
  `reconstruction.*`, `utils.validation.*` en imports purs
- Nouvelle DB de sortie : `db_v3.db` (séparée de `db_v2.db` qui reste
  intacte pour comparaison)

## Plan de validation

1. **Local** : `python -m csp_solver.experiments_v2.main file.graph --sym 1 --pb 2 --validate`
   sur 1 mol h7 pilote → vérifier que le %plan monte
2. **Cluster** : lance les 5 configs sur tout h7 (~ 14k sols) → mesurer
3. **Cluster** : si OK, scale h6+h7+h8+h9 → nouveau db_v3.db
4. **Compare** : analysis_v2 sur db_v3 vs db_v2 (rapport `rapport_compare.html`)
