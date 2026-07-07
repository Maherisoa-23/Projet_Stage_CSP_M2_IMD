# Export de secours — solutions h3 à h9 (JSON Lines)

Export des données de solutions du projet, indépendant de l'application
(Docker/designer). À utiliser si l'app est indisponible ou pour du
traitement en masse (Python, pandas, jq, grep) sans dépendre du solveur
CSP ni de xTB.

## Fichiers

Un fichier par **(taille `h`, config)** — pas un seul fichier par taille —
pour ne récupérer que la configuration qui intéresse sans télécharger les
autres (`Cstr`, la plus volumineuse, dépasse seule 2 Go sur h9).

| h | config | Lignes | Taille (.gz) |
|---|---|---|---|
| h3 | C1 | 7 | 5.6 KB |
| h3 | C2 | 5 | 4.0 KB |
| h3 | C3 | 5 | 4.0 KB |
| h3 | Cstr | 7 | 5.4 KB |
| h4 | C1 | 44 | 38 KB |
| h4 | C2 | 16 | 14 KB |
| h4 | C3 | 12 | 11 KB |
| h4 | Cstr | 51 | 43 KB |
| h5 | C1 | 278 | 278 KB |
| h5 | C2 | 62 | 62 KB |
| h5 | C3 | 28 | 28 KB |
| h5 | Cstr | 402 | 395 KB |
| h6 | C1 | 2 146 | 2.4 MB |
| h6 | C2 | 254 | 288 KB |
| h6 | C3 | 75 | 82 KB |
| h6 | Cstr | 3 556 | 3.9 MB |
| h7 | C1 | 15 004 | 19 MB |
| h7 | C2 | 900 | 1.1 MB |
| h7 | C3 | 178 | 221 KB |
| h7 | Cstr | 29 660 | 37 MB |
| h8 | C1 | 112 800 | 160 MB |
| h8 | C2 | 3 292 | 4.6 MB |
| h8 | C3 | 512 | 712 KB |
| h8 | Cstr | 261 260 | 367 MB |
| h9 | C1 | 646 319 | 1.03 GB |
| h9 | C2 | 21 127 | 33 MB |
| h9 | C3 | 2 845 | 4.4 MB |
| h9 | Cstr | 1 500 897 | **2.30 GB** |
| **Total** | | **2 601 742** | **~4.0 GB** |

Seules les solutions avec statut `done` et géométrie xTB optimisée
disponible sont incluses (les solutions `failed`/`skipped` — géométrie
impossible ou xTB en échec — n'ont pas de verdict ni de géométrie
exploitable, donc pas de ligne exportée).

### Config `Ctopo` absente de ces exports

`Ctopo` (config recommandée dans `doc/experimentation.md`) est calculée à
part par `csp_solver.analysis.materialize_ctopo` : c'est un filtre dérivé
des résultats `C1`, sans ligne propre dans `final_solutions` (donc sans
`graph_content_gz`/`xyz_optimized_gz` associés à exporter). Pour consulter
`Ctopo` hors-ligne, utiliser les fichiers `h*_C1.jsonl.gz` et appliquer le
même filtre topologique, ou passer par l'explorateur web (table `molecules`/
`solutions`, config `Ctopo`).

## Format : JSON Lines compressé (.jsonl.gz)

**Pas un JSON classique** (`[{...}, {...}]`). Chaque ligne du fichier
décompressé est un objet JSON complet et indépendant. Avantages :

- Streamable : pas besoin de charger tout le fichier en mémoire pour le lire
  (important pour `h9_Cstr`, 1.5M lignes)
- Filtrable en ligne de commande (`zcat` + `grep`/`jq`)
- Robuste aux gros volumes : un JSON array unique de plusieurs Go ne se
  parse pas raisonnablement d'un bloc

Chaque ligne a cette structure :

```json
{
  "size_h": 9,
  "config": "C1",
  "graph_name": "0-10-20-30-39-49-59-68-78",
  "sol_index": 329,
  "verdict": "PLAN",
  "angle_deg": 0.031,
  "energy_eh": -456.789,
  "homo_lumo_ev": 2.87,
  "max_dihedral_deg": 1.2,
  "csp_solution": {"0": 5, "1": 6, "2": 7, "...": "..."},
  "graph": "p DIMACS 60 78 9\ne 0_0 1_1\n...",
  "xyz": "60\n energy: -456.789 gnorm: 0.0001 xtb: 6.7.1\nC  ...\n"
}
```

### Champs

| Champ | Type | Sens |
|---|---|---|
| `size_h` | int | Nombre d'hexagones du benzénoïde d'origine |
| `config` | str | Configuration CSP utilisée (`C1`, `C2`, `C3`, `Cstr`) |
| `graph_name` | str | Identifiant du benzénoïde d'entrée (positions des hexagones) |
| `sol_index` | int | Index de la solution dans l'énumération CSP |
| `verdict` | str | `PLAN`, `NON_PLAN`, `LIMITE` (planarité selon le test PCA) |
| `angle_deg` | float | Angle d'écart au plan (°) |
| `energy_eh` | float | Énergie totale xTB (Hartree) |
| `homo_lumo_ev` | float | Gap HOMO-LUMO (eV) |
| `max_dihedral_deg` | float | Dièdre maximal observé (°) |
| `csp_solution` | dict | `{indice_hexagone: taille}` — la solution CSP brute (tailles 5/6/7 assignées) |
| `graph` | str | Fichier `.graph` DIMACS d'entrée (positions + hexagones), texte brut |
| `xyz` | str | Géométrie 3D optimisée par xTB, format `.xyz` standard, texte brut |

### Champs non inclus

`clar_sextets` et `rbo_pauling` existent dans la base source mais sont
vides sur l'ensemble de la DB actuelle (post-traitement Clar/RBO pas
encore exécuté sur ce run) — ils ne sont donc pas exportés. Voir
`csp_solver/analysis/postprocess_clar_rbo.py` si ce calcul est lancé plus tard.

## Comment lire ces fichiers

### Python

```python
import gzip, json

with gzip.open("h9_C1.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        if obj["verdict"] == "PLAN":
            print(obj["graph_name"], obj["sol_index"], obj["energy_eh"])
```

### Extraire tous les XYZ d'un fichier vers des fichiers séparés

```python
import gzip, json
from pathlib import Path

out = Path("xyz_extraits")
out.mkdir(exist_ok=True)
with gzip.open("h9_C1.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        name = f"{obj['config']}_{obj['graph_name']}_sol{obj['sol_index']}.xyz"
        (out / name).write_text(obj["xyz"], encoding="utf-8")
```

### Ligne de commande (jq)

```bash
# Compter les solutions PLAN dans h9 / C1
zcat h9_C1.jsonl.gz | jq -r '.verdict' | sort | uniq -c

# Extraire toutes les solutions PLAN de C2 avec leur energie
zcat h9_C2.jsonl.gz | jq 'select(.verdict=="PLAN") | {graph_name, sol_index, energy_eh}'
```

### pandas (pour analyse tabulaire, sans les champs texte lourds)

```python
import gzip, json
import pandas as pd

rows = []
with gzip.open("h8_C1.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        rows.append({k: v for k, v in obj.items() if k not in ("graph", "xyz", "csp_solution")})
df = pd.DataFrame(rows)
print(df.groupby("verdict").size())
```

## Régénérer cet export

```bash
python -m csp_solver.analysis.export_jsonl --out exports/
python -m csp_solver.analysis.export_jsonl --out exports/ --only-h 9                    # une seule taille, toutes ses configs
python -m csp_solver.analysis.export_jsonl --out exports/ --only-h 9 --only-config Cstr  # une seule taille + une seule config
```

Source : `experiments/final/final_h3_h9.db` (table `final_solutions`).
Régénéré le 2026-07-07 (ajout de la config `Cstr`, ~12 min pour l'ensemble
h3-h9 × 4 configs), décomposé par `(h, config)` depuis la version initiale
du 2026-07-02 (un seul fichier par `h`, sans `Cstr`).
