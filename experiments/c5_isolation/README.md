# Données « isolation de C5 » — run cluster COALA (juin 2026)

Ce dossier rassemble les bases SQLite produites sur le cluster COALA pour les
**2 nouvelles slides** isolant l'effet de la contrainte **C5 (table de voisinage)** :

- Slide 1 : « C structurel » vs « C structurel + C5 »
- Slide 2 : « C structurel + C6 » vs « C structurel + C6 + C5 »

Tableaux 3 lignes par taille h : (1) planes trouvées, (2) non-planes, (3) planes
manquées = planes(sans C5) − planes(avec C5). **Seuil de planéité : dièdre < 25°.**

---

## 1. D'où viennent les 4 configs des slides (rappel logique)

Le verdict xTB est **déterministe** en `(molécule, assignation de tailles)` — vérifié
empiriquement (579/579 angles identiques entre deux bases). Donc **une seule** config
est (re)calculée sur le cluster : `Cstr` = structurel seul, **sans** table (`no_table=True`,
`adj_57=False`). C'est le **sur-ensemble**. Les 3 autres se dérivent **sans recalcul** :

| Config slide            | Origine des solutions                              |
|-------------------------|----------------------------------------------------|
| C structurel            | **`Cstr`** (ce run cluster)                        |
| C structurel + C5       | **`C1`** (déjà dans `experiments/final/final_h3_h9.db`) |
| C structurel + C6       | `Cstr` filtré par le prédicat **adj_57**           |
| C structurel + C6 + C5  | `C1` filtré par le prédicat **adj_57**             |

---

## 2. Les bases produites

| Fichier                | Contenu                          | Tailles | Statut au dernier check |
|------------------------|----------------------------------|---------|-------------------------|
| `no_table_run.db`      | `Cstr` exhaustif                 | h3–h8   | **TERMINÉ** ✅           |
| `h9_choco_g1.db`       | `Cstr` h9 (graphes 0–461)        | h9      | terminé (reliquat mineur) |
| `h9_choco_g2.db`       | `Cstr` h9 (graphes 461–921)      | h9      | en cours                |
| `h9_choco_g3.db`       | `Cstr` h9 (graphes 921–1122)     | h9      | terminé ✅               |
| `h9_choco_g4.db`       | `Cstr` h9 (graphes 1122–2418)    | h9      | **en cours, lent** ⚠️    |

h9 est **plafonné à 200 solutions/molécule** (échantillon stratifié représentatif,
seed=42), réparti en 4 « shards » (g1–g4), chacun dans sa propre DB pour éviter la
contention SQLite croisée. Les lignes `status='skipped'` = surplus écarté par le
plafond, **jamais dispatché, inutile pour les résultats**.

---

## 3. Accès cluster

Connexion (clé `id_ed25519`, ProxyJump `saphir2` déjà configuré dans `~/.ssh/config`) :

```bash
ssh 192.168.200.49            # la frontale ; le dispatcher tourne ICI
source ~/miniforge3/etc/profile.d/conda.sh && conda activate nonbenz
cd ~/projet
```

Groupes de machines (workers), par IP (suffixe = numéro hôte + 9) :

| Groupe | Workers (IP suffixes)            | Cœurs/nœud | max-parallel-xtb conseillé |
|--------|----------------------------------|------------|----------------------------|
| g1     | 10–25 (Config1)                  | 8          | 8                          |
| g2     | 26–41 (Config2+3)                | 8          | 8                          |
| g3     | 42–48 (Config4, libre)           | 8          | 8                          |
| g4     | 65–73 (Config5)                  | 40         | voir §6 (contention)       |
| (h3-h8)| 49–64 (Config4+5, **libres** maintenant) | 8/40 | —                          |

> ⚠️ `.17`, `.18`, `.27` sont **injoignables** (machines down) — normal, à ignorer.

---

## 4. Vérifier l'avancement (= la commande « rapport »)

```bash
# h3-h8
python -c "import sqlite3; c=sqlite3.connect('no_table_run.db'); [print(r) for r in c.execute('SELECT size_h,status,COUNT(*) FROM final_solutions GROUP BY size_h,status ORDER BY size_h,status')]"

# un shard h9 (g1/g2/g3/g4)
python -c "import sqlite3; c=sqlite3.connect('h9_choco_g4.db'); [print(r) for r in c.execute(\"SELECT status,COUNT(*) FROM final_solutions WHERE run_id=1 GROUP BY status\")]"

tmux ls   # sessions de dispatch actives
```

Débit = relire `done` à 60 s d'intervalle. Sessions en cours : `notable` (h3-h8, fini),
`h9_g2`, `h9_g4_*`.

---

## 5. Reprendre un dispatch (résumé : reset orphelins → relancer)

À **chaque arrêt** d'un dispatch (Ctrl-C, crash, fin de session), des lignes restent
bloquées en `status='running'`. **Avant de relancer**, il faut les remettre en `pending` :

```bash
# 1) reset des orphelins
python -c "import sqlite3; c=sqlite3.connect('h9_choco_g4.db'); n=c.execute(\"UPDATE final_solutions SET status='pending' WHERE run_id=1 AND status='running'\").rowcount; c.commit(); print('reset',n)"

# 2) relancer le dispatch en tmux (adapter --db, --workers, --max-parallel-xtb)
tmux new -d -s h9_g4 "source ~/miniforge3/etc/profile.d/conda.sh && conda activate nonbenz && cd ~/projet && python -m csp_solver._run_final dispatch --db ~/projet/h9_choco_g4.db --run-id 1 --workers 65,66,67,68,69,70,71,72,73 --batch-size 40 --max-parallel-xtb 40 --timeout-xtb 50000 --ssh-timeout 18000 --heartbeat 60"
```

> **Gotcha clés SSH** : si un shard reste à 0 `done` avec des erreurs
> `Host key verification failed`, c'est que la **frontale** ne connaît pas les clés
> des workers. Corriger DEPUIS la frontale :
> ```bash
> for ip in $(seq 10 73); do ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 192.168.200.$ip 'echo OK' 2>/dev/null; done
> ```

---

## 6. ⚠️ Problème de contention sur `h9_choco_g4.db` (1.4 Go)

g4 est gros (1296 graphes, ~240k solutions + 2M skipped → DB de 1.4 Go). Sous forte
concurrence (32 workers), les écritures `done` se bloquent toutes sur
`database is locked` → **débit nul**. Constats : 9 workers ≈ 137/min ; 16 ≈ 93/min ;
32 ≈ 0. **Plus de workers = pire.**

**Correctif racine recommandé** (réduit la DB de 1.4 Go à ~200 Mo → écritures rapides) :

```bash
# arrêter g4, reset orphelins (cf §5), PUIS :
python -c "import sqlite3; c=sqlite3.connect('h9_choco_g4.db'); c.execute(\"DELETE FROM final_solutions WHERE status='skipped'\"); c.commit(); print('skipped supprimes'); c.execute('VACUUM'); print('vacuum ok')"
# relancer avec un nombre MODÉRÉ de workers (ex: les 9 de Config5 .65-.73, max-parallel 40)
```

Les `skipped` sont du surplus jamais utilisé : les supprimer n'a **aucun** impact
sur les résultats. À défaut de correctif, garder g4 à **≤ 9 workers**.

---

## 7. Rapatrier les bases en local

```bash
scp 192.168.200.49:projet/no_table_run.db   ./    # 933 Mo
scp 192.168.200.49:projet/h9_choco_g1.db    ./    # 524 Mo
scp 192.168.200.49:projet/h9_choco_g2.db    ./    # 476 Mo
scp 192.168.200.49:projet/h9_choco_g3.db    ./
scp 192.168.200.49:projet/h9_choco_g4.db    ./    # 1.4 Go (moins après VACUUM)
```

---

## 8. Étape suivante (LOCAL) : agrégation + slides

1. Pour chaque DB : compter, par taille h, les verdicts (`done` avec `angle_deg < 25`
   = plane, sinon non-plane). Pour `Cstr` (et `C1` de `final_h3_h9.db`), produire aussi
   la variante **filtrée adj_57** (= +C6).
2. Construire les 2 tableaux 3 lignes (planes / non-planes / planes manquées).
3. Slides : `doc/presentation/transparent_M2_IMD.tex` — déplacer « Comparaison des
   configurations » et « Bilan expérimental » en annexe (`\backupbegin`…`\backupend`),
   ajouter les 2 nouvelles slides. Recompiler (3 passes `pdflatex`), nettoyer les aux.

> Le script d'agrégation (`aggregate.py`) n'est **pas encore écrit** — c'est la
> prochaine tâche locale une fois les bases rapatriées.

---

*Dernière mise à jour : 2026-06-27 ~22h50. h3-h8 terminé et en cours de rapatriement ;
h9 g1/g3 finis, g2 en cours, g4 ralenti (voir §6).*
