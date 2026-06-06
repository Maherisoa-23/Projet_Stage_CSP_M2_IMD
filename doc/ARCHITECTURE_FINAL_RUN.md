# Architecture — Run final h3-h9 × 3 configs sur cluster

Document de design. À valider avant implémentation.

## 1. Objectif

Exécuter l'énumération CSP + validation xTB pour :
- 7 tailles : h3, h4, h5, h6, h7, h8, h9
- 3 configurations contraintes :
  - **C1 (Base)** : topologiquement faisable, K_sym ≥ 0, K_pb cardinaux, K_hb cardinaux, K_tot cardinaux ; **pas** de Pb1, **pas** de adj_57, **pas** de tau_gb ; symétrie C1/C3 activée
  - **C2 (Pb1 + adj_57)** : C1 + Pb1 + adj_57
  - **C3 (Pb1 + adj_57 + tau_gb=0)** : C2 + interdiction adjacence 7-7
- Pas de gel d'hexagone, pas de plafonnement, seed xTB fixée à 42
- Métriques enrichies : verdict planéité (angle PCA), énergie xTB, HOMO-LUMO, temps CPU, sextets Clar, RBO Pauling-Randić

→ 21 (taille, config) combinations, persistance en DB séparée.

## 2. Topologie

```
PC LOCAL (Windows, peut s'eteindre)
   |
   | scp/ssh ponctuels pour deploiement initial + monitoring + rapatriement final
   |
   v
=================================================================
CLUSTER (192.168.200.49 = frontale = master, 50-64 = workers)
=================================================================

                 +-------------------------------+
                 | MASTER (frontale 49, nohup)   |
                 |  _dispatcher.py               |
                 |  - lit DB Final               |
                 |  - lance CSP par (taille,cfg) |
                 |  - dispatch sols vers workers |
                 |  - ingere resultats           |
                 |  - retry max 2                |
                 |  - checkpoint dans DB         |
                 +-------------------------------+
                              |
                              | SSH pool (semaphore)
                              v
   +------+    +------+    +------+    +------+    +------+
   | 49   |    | 50   |    | 51   |    | ...  |    | 64   |
   |worker|    |worker|    |worker|    |      |    |worker|
   +------+    +------+    +------+    +------+    +------+

DB FINAL : ~/projet/final_h3_h9.db (sur frontale, NFS partage)
```

**Choix clé** : master sur cluster (pas en local), pour survivre à l'extinction du PC user.

## 3. Composants

### 3.1. `_dispatcher.py` (master, sur frontale 49)

Fichier : `~/projet/csp_solver/_dispatcher.py` (déployé via scp)

Responsabilités :
1. Crée/ouvre `~/projet/final_h3_h9.db`
2. Pour chaque (taille h, config) non encore traitée :
   - Lance CSP énumération : `python -m csp_solver.main --size h --preset cfgX --enumerate-only`
   - Récupère les N solutions (graph 2D + indices)
   - Insère N lignes dans `final_solutions` avec `status='pending'`
3. Boucle dispatch :
   - Pool de threads (max_concurrent depuis CLI, défaut **16**)
   - Pop une row `pending`, set `status='running'`, attribue à un worker machine
   - SSH `worker IP : python -m csp_solver._worker_xtb < input.json > output.json`
   - Au retour, update row avec métriques + `status='done'` ou `'failed'`
   - Si failed et `retry_count < 2` → re-set `pending` avec `retry_count += 1`
4. Périodiquement : écrit un heartbeat dans `final_runs.last_heartbeat`
5. Quand toutes les sols traitées : marque `state='completed'` dans `final_runs`

Lancement : `nohup python ~/projet/csp_solver/_dispatcher.py > ~/dispatcher.log 2>&1 &`

### 3.2. `_worker_xtb.py` (worker, invoqué via SSH)

Fichier : `~/projet/csp_solver/_worker_xtb.py`

Reçoit sur stdin (JSON) :
```json
{
  "sol_id": 12345,
  "size_h": 6,
  "config": "C2",
  "graph_content": "...",
  "sol_index": 3,
  "kekule_path_in": "...",
  "seed_md": 42,
  "timeout_xtb": 50000
}
```

Workflow :
1. Crée workdir temporaire : `/tmp/worker_<sol_id>_<pid>`
2. Reconstruit 3D depuis (graph + sol_index)
3. xTB MD courte + opt
4. Parse output : energie, HOMO-LUMO, temps CPU
5. Calcule planarité PCA (angle deg)
6. Calcule sextets Clar (sur graphe 2D)
7. Calcule RBO Pauling-Randić
8. Retourne JSON sur stdout :
```json
{
  "sol_id": 12345,
  "status": "done",
  "verdict": "PLAN" | "LIMITE" | "NON_PLAN",
  "angle_deg": 7.3,
  "energy_eh": -123.45,
  "homo_lumo_ev": 1.82,
  "cpu_time_s": 87.4,
  "wall_time_s": 65.2,
  "clar_sextets": 3,
  "rbo_pauling": 1.47,
  "xyz_optimized_gz_b64": "...",
  "hostname": "lis-cluster-coala-49"
}
```
9. Cleanup workdir `/tmp/worker_*`

### 3.3. Schéma DB `final_h3_h9.db`

```sql
CREATE TABLE final_runs (
  run_id          INTEGER PRIMARY KEY,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  state           TEXT NOT NULL DEFAULT 'running',  -- running, completed, aborted
  last_heartbeat  TEXT,
  config_json     TEXT,  -- seeds, max_concurrent, timeout, etc.
  notes           TEXT
);

CREATE TABLE final_solutions (
  sol_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id          INTEGER NOT NULL REFERENCES final_runs(run_id),
  size_h          INTEGER NOT NULL,
  config          TEXT NOT NULL,        -- 'C1', 'C2', 'C3'
  sol_index       INTEGER NOT NULL,     -- index dans la sortie CSP
  graph_content_gz BLOB NOT NULL,       -- graph d'entree (gzippe)
  csp_solution_json TEXT NOT NULL,      -- assignation CSP (vars/values)
  -- Status
  status          TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
  retry_count     INTEGER NOT NULL DEFAULT 0,
  hostname        TEXT,
  error_message   TEXT,
  -- Resultats xTB
  verdict         TEXT,                 -- PLAN, LIMITE, NON_PLAN
  angle_deg       REAL,
  energy_eh       REAL,
  homo_lumo_ev    REAL,
  cpu_time_s      REAL,
  wall_time_s     REAL,
  -- Resultats electroniques
  clar_sextets    INTEGER,
  rbo_pauling     REAL,
  -- XYZ optimise
  xyz_optimized_gz BLOB,
  -- Timestamps
  started_at      TEXT,
  finished_at     TEXT,
  UNIQUE(run_id, size_h, config, sol_index)
);

CREATE INDEX idx_final_sols_status ON final_solutions(status);
CREATE INDEX idx_final_sols_size_config ON final_solutions(size_h, config);
```

## 4. Flux d'execution complet

```
1. PREP (1 fois, depuis PC local)
   - scp _dispatcher.py + _worker_xtb.py vers cluster
   - scp csp_solver/data/table_voisinage.json (verifier que c'est la derniere version)
   - ssh frontale : verifier que xtb fonctionne (which xtb, xtb --version)

2. LANCEMENT (sur frontale 49)
   nohup python ~/projet/csp_solver/_dispatcher.py --db ~/projet/final_h3_h9.db \
                                                  --max-concurrent 16 \
                                                  --timeout-xtb 50000 \
                                                  --seed 42 \
                                                  --workers "49,50,51,...,64" \
       > ~/dispatcher.log 2>&1 &

3. SUIVI (depuis PC local)
   ssh frontale 'tail -f ~/dispatcher.log'
   ssh frontale 'sqlite3 ~/projet/final_h3_h9.db "SELECT status, COUNT(*) FROM final_solutions GROUP BY status"'

4. FIN (master ecrit final_runs.state = 'completed' + finished_at)
   - scp ~/projet/final_h3_h9.db vers PC local
   - analyse en local
```

## 5. Reprise sur panne

### 5.1. Reprise du master

Si master plante :
- Toutes les sols `running` au moment du crash → reset auto à `pending` (au demarrage du nouveau master)
- Sols `done` ou `failed (final)` → preservées
- Sols `pending` → reprise normale

Au lancement, le master :
```sql
UPDATE final_solutions SET status='pending', hostname=NULL
WHERE status='running' AND retry_count < 2;
```

### 5.2. Reprise du worker

Si SSH worker plante en cours :
- Exception cote master → catch → marquer la sol `pending` avec `retry_count += 1`
- Si `retry_count >= 2` → `failed` definitif

### 5.3. Reprise du run complet

Si on relance `_dispatcher.py` sur une DB existante :
- Le master detecte `final_runs` existant et `state='running'`
- Reprend uniquement les sols `pending`
- Si on veut relancer une config particuliere : SQL manuel
  `UPDATE final_solutions SET status='pending', retry_count=0 WHERE config='C1' AND size_h=8`

## 6. Granularite et perf

### Choix initial (simple)

- **Pool de 16 threads master** (1 sol par machine simultanee)
- **OMP_NUM_THREADS=40** par worker (toute la machine pour xTB)
- 16 sols en parallel max

### Si trop lent (optimisation v2)

- 1 SSH par machine = batch de 5-10 sols, lance avec `xargs -P 5` localement
- OMP_NUM_THREADS=8 par xTB → 5 instances de xTB par machine
- 16 × 5 = 80 sols en parallel

→ A decider apres test pilote h3.

## 7. Risques et garde-fous

| Risque | Mitigation |
|---|---|
| Master plante au milieu | DB checkpoint atomique, reprise via `--resume` |
| Worker hang (xTB qui boucle) | `timeout 50000s` sur la commande xTB |
| NFS lock conflict sur DB | PRAGMA busy_timeout=10000, WAL mode |
| Code pas synchro sur cluster | `_dispatcher.py` au demarrage vérifie le hash de `csp_solver/` |
| Quota disque NFS | `df` check au demarrage + tous les 100 sols |
| CSP enumeration explose en RAM | Pour h≥7 on streame plutot que load all en memoire |

## 8. Plan de test pilote (etape 7)

**Test pilote = h3 sur 3 configs avec dispatcher complet** :
- h3 a peu de sols (estimee < 100)
- Tourne en quelques minutes
- Valide : DB, dispatch, retry, ingestion, metriques Clar/RBO/HOMO-LUMO
- Si OK → lance h4..h9 pour les 3 configs

## 9. Decisions encore en suspens

Decisions a confirmer avant code :

- **DEC-1** : Master sur frontale 49 OK ? (sinon PC local + le user laisse PC allume)
- **DEC-2** : DB sur frontale (`~/projet/final_h3_h9.db`) OK ? Ou plutot un chemin dedie `~/final_run/` ?
- **DEC-3** : OMP_NUM_THREADS = 40 (1 sol/machine) ou 8 (5 sols/machine) en premier choix ?
- **DEC-4** : Clar/RBO : calcules dans le worker (cluster, parallele) ou en post-traitement (local, single thread) ?
  - Worker : parallel, mais double les chances de bug nouveau code en prod
  - Post-traitement : safe, mais sequentiel et passe le code sur 21000 sols apres coup
  - Reco : **post-traitement** pour la v1 (decouple risque). Si trop lent, on bouge au worker.

