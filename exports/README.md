# Export de secours — solutions h3 à h9 (JSON Lines)

Export des données de solutions du projet, indépendant de l'application
(Docker/designer). À utiliser si l'app est indisponible ou pour du
traitement en masse (Python, pandas, jq, grep) sans dépendre du solveur
CSP ni de xTB.

## Fichiers

| Fichier | Lignes | Taille (.gz) |
|---|---|---|
| `h3.jsonl.gz` | 17 | 5.9 KB |
| `h4.jsonl.gz` | 72 | 62 KB |
| `h5.jsonl.gz` | 368 | 367 KB |
| `h6.jsonl.gz` | 2 475 | 2.8 MB |
| `h7.jsonl.gz` | 16 082 | 21 MB |
| `h8.jsonl.gz` | 116 604 | 166 MB |
| `h9.jsonl.gz` | 670 291 | 1.1 GB |
| **Total** | **805 909** | **~1.3 GB** |

Un fichier par taille `h` (nombre d'hexagones). Seules les solutions avec
statut `done` et géométrie xTB optimisée disponible sont incluses (les
solutions `skipped`, typiquement géométriquement infaisables sur h9, ne
sont pas exportées — elles n'ont pas de verdict ni de géométrie exploitable).

## Format : JSON Lines compressé (.jsonl.gz)

**Pas un JSON classique** (`[{...}, {...}]`). Chaque ligne du fichier
décompressé est un objet JSON complet et indépendant. Avantages :

- Streamable : pas besoin de charger tout le fichier en mémoire pour le lire
  (important pour h9, 670k lignes)
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
| `config` | str | Configuration CSP utilisée (`C1`, `C2`, `C3`, `Ctopo`) |
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

with gzip.open("h9.jsonl.gz", "rt", encoding="utf-8") as f:
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
with gzip.open("h9.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        name = f"{obj['config']}_{obj['graph_name']}_sol{obj['sol_index']}.xyz"
        (out / name).write_text(obj["xyz"], encoding="utf-8")
```

### Ligne de commande (jq)

```bash
# Compter les solutions PLAN dans h9
zcat h9.jsonl.gz | jq -r '.verdict' | sort | uniq -c

# Extraire toutes les config=C2, verdict=PLAN, avec leur energie
zcat h9.jsonl.gz | jq 'select(.config=="C2" and .verdict=="PLAN") | {graph_name, sol_index, energy_eh}'
```

### pandas (pour analyse tabulaire, sans les champs texte lourds)

```python
import gzip, json
import pandas as pd

rows = []
with gzip.open("h8.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        rows.append({k: v for k, v in obj.items() if k not in ("graph", "xyz", "csp_solution")})
df = pd.DataFrame(rows)
print(df.groupby("verdict").size())
```

## Régénérer cet export

```bash
python -m csp_solver.analysis.export_jsonl --out exports/
python -m csp_solver.analysis.export_jsonl --out exports/ --only-h 9   # une seule taille
```

Source : `experiments/final/final_h3_h9.db` (table `final_solutions`).
Généré le 2026-07-02, ~4min20 pour l'ensemble h3-h9.
