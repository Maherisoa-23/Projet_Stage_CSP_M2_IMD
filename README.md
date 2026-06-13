# Generation de non-benzenoides plans par CSP

Projet de stage M2 IMD (AMU). Genere des molecules **non-benzenoides** (cycles
de tailles 5, 6, 7) sur des squelettes benzenoides et identifie celles dont
la structure 3D optimisee reste **plane**.

**Pipeline** :

```
Squelette benzenoide -> Solveur CSP (PyCSP3 + ACE)
                          | affectations 5/6/7 sur cycles
                          v
                     Reconstruction 3D
                          | geometrie XYZ
                          v
                     det-opt xTB (deterministe)
                          | XYZ optimise
                          v
                     Test planarite (PCA, seuil 10°)
                          v
                  PLAN | NON_PLAN | xTB_failed
```

---

## Demarrage rapide

```bash
# 1. Cloner et installer
git clone <repo>
cd Projet_Stage_CSP_M2_IMD
python -m venv venv
source venv/bin/activate   # (Linux/macOS) ou venv\Scripts\activate (Windows)
pip install -r requirements.txt

# 2. Pre-requis externes
#    - xtb (binaire >= 6.7) : https://github.com/grimme-lab/xtb
#    - ACE solver (jar)     : https://www.cril.univ-artois.fr/~lecoutre/

# 3. Lancer le viewer (DB pre-calculee fournie ou regenerable)
python server.py --db experiments/final/final_h3_h9.db --port 8765
# -> ouvrir http://127.0.0.1:8765
```

---

## Structure du repo

| Dossier | Contenu |
|---|---|
| **`csp_solver/`** | Solveur CSP (modele PyCSP3) + wrappers xTB |
| `csp_solver/main.py` | Point d'entree CLI (1 graph, dev/debug) |
| `csp_solver/final/` | **Run final cluster** (production h3-h9, 3 configs) |
| `csp_solver/analysis/` | Pipeline d'analyse post-run (features + Ctopo) |
| `csp_solver/xtb/det_opt.py` | Protocole det-opt (xtb deterministe) |
| **`viewer/`** | Serveur Flask + visualisation 3D + designer interactif |
| `viewer/server.py` | API Flask + UI navigation des datasets |
| `viewer/molviz/` | Rendu 3Dmol.js + Kekule/Clar/RBO |
| `viewer/designer/` | Designer de molecules + run CSP a la demande |
| `viewer/migrations/` | Migrations de schema DB |
| **`cluster/`** | Code cluster (deploiement, ops, dispatcher legacy) |
| `cluster/ops/` | Scripts ops (finalize_stuck, retry_failed, deploy) |
| **`experiments/`** | Outputs des runs cluster (largement gitignored) |
| `experiments/final/` | **Run final h3-h9** (DB + outputs, base du memoire) |
| **`scripts/figures/`** | Generation PDF figures pour le memoire |
| **`doc/`** | Documentation projet + memoire LaTeX |
| `doc/memoire.tex` | Memoire de stage |
| `doc/PIPELINE.md` | Architecture pipeline |
| `doc/experimentation.md` | Synthese resultats (4 configs) |
| `doc/experimentation_complete.md` | Journal detaille des experimentations |

Dossiers gitignored : `venv/`, `data/`, `divers/`, `tmp/`, `experiments/**/output/`,
`viewer/output/`, `doc/captures/`, `doc/motifs_bord_h8.{tex,pdf}`.

---

## 4 configurations CSP (C1, C2, C3, Ctopo)

Le run final cluster a teste 3 configurations CSP (`csp_solver/final/configs.py`).
La 4eme (Ctopo) a d'abord ete materialisee a posteriori dans la DB du viewer
(`csp_solver/analysis/materialize_ctopo.py`), puis re-implementee comme vraie
contrainte CSP solveur en Phase E (blacklist rayon-2 + pre-check n_peri,
cf. `csp_solver/utils/model.py`). Source de verite : `experiments/final/final_h3_h9.db`.

| Config | Description courte | h9 %PLAN |
|---|---|---:|
| **C1** | Baseline (table de voisinage seule) | 38.2 % |
| **C2** | Pb1 + adj_57 (Stone-Wales force) | 49.7 % |
| **C3** | C2 + tau_gb=0 (pas de 7-7 adjacents) | 60.1 % |
| **Ctopo** | Rayon-2 + topologie squelette (recommandation) | **71.4 %** (x18 plans) |

Voir [`doc/experimentation.md`](doc/experimentation.md) pour les chiffres complets
et la justification scientifique de Ctopo.

---

## Lancer un run CSP

**Local (1 graph, dev)** :
```bash
python -m csp_solver.main data/some.graph --enumerate-all
```

**Cluster (production h3-h9)** :
```bash
# 1. Init DB + enumere les CSP a faire
python -m csp_solver.final.run setup --db ~/final.db --sizes 3,4,5,6,7,8,9

# 2. Lance le dispatcher (orchestration SSH multi-workers)
python -m csp_solver.final.run dispatch --db ~/final.db --run-id 1 \
    --workers 49,50,51,52 --batch-size 40

# 3. Surveiller (depuis un autre terminal)
python -m csp_solver.final.run status --db ~/final.db
```

Variables d'environnement utiles :
- `CSP_CLUSTER_CONDA_INIT` : commande shell pour activer l'env conda cote workers
- `CSP_CLUSTER_PROJECT_PATH` : chemin du repo cote workers (defaut `~/projet`)

---

## Reproduire Ctopo apres un run

```bash
# 1. Migrer la DB du run final vers le schema viewer
python -m viewer.migrations.final_to_viewer

# 2. Calculer les features
python -m csp_solver.analysis.compute_adjacencies
python -m csp_solver.analysis.compute_combined_features 7
python -m csp_solver.analysis.compute_combined_features 8
python -m csp_solver.analysis.compute_combined_features 9

# 3. Materialiser Ctopo
python -m csp_solver.analysis.materialize_ctopo

# 4. Lancer le viewer
python server.py --db experiments/final/final_h3_h9.db
```

---

## Documents cles

- [`doc/PIPELINE.md`](doc/PIPELINE.md) - architecture du pipeline
- [`doc/CONTRAINTES.md`](doc/CONTRAINTES.md) - modele CSP detaille
- [`doc/ARCHITECTURE_FINAL_RUN.md`](doc/ARCHITECTURE_FINAL_RUN.md) - run cluster
- [`doc/DESIGNER_CLUSTER_DB.md`](doc/DESIGNER_CLUSTER_DB.md) - designer interactif
- [`doc/ANALYSE_ELECTRONIQUE.md`](doc/ANALYSE_ELECTRONIQUE.md) - Kekule/Clar/RBO
- [`doc/experimentation.md`](doc/experimentation.md) - **synthese resultats**
- [`doc/experimentation_complete.md`](doc/experimentation_complete.md) - journal detaille
- [`doc/memoire.pdf`](doc/memoire.pdf) - memoire de stage

---

## License

Voir [`LICENSE`](LICENSE).
