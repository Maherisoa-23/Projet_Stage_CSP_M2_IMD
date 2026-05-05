# Cluster orchestration

Outils pour distribuer le pipeline CSP+MD sur le cluster COALA (16 lames
`lis-cluster-coala-49..64`, sans SLURM, NFS partage `/home/COALA/...`).

## Vue d'ensemble

```
NFS partage
+-- manifest_h6.jsonl                             # liste des jobs (1 par ligne)
+-- claims/                                       # locks atomiques par job
|   +-- h6_default_0-5-6-11-12.lock
|   +-- ...
+-- output/h6/<config>/<mol>/                     # resultats finals
    +-- job_status.json                           # signal de fin
    +-- <mol>_original.xyz, *_opt.xyz
    +-- solutions/sol_*/source.xyz, md_validation/
```

## Composants

| Fichier | Role |
|---------|------|
| [build_manifest.py](build_manifest.py) | Genere le manifest JSONL pour un dataset hX |
| [worker.py](worker.py) | Tourne sur 1 machine, pull-based, lance jusqu'a N jobs en parallele |
| [recover_stale.py](recover_stale.py) | Libere les locks orphelins (worker mort) |
| `../run_one_job.py` | Execute UN seul (graph, config) en scratch local |

## Workflow type (h6, depuis saphir2 ou un noeud du cluster)

```bash
# 1. Activation env (a chaque session SSH)
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz

# 2. Generer le manifest (1 fois, sur 1 machine)
cd /home/COALA/ramaherisoa/projet/csp_solver/experiments
python cluster/build_manifest.py plane/benzdb/h6 --output manifest_h6.jsonl
# -> 44 graphes x 8 configs = 352 jobs

# 3. (optionnel) menage des locks orphelins d'un run precedent
python cluster/recover_stale.py \
    --claims-dir cluster_state/claims \
    --output-root output \
    --max-age-min 30

# 4. Lancer 1 worker sur chaque machine (a faire sur les 16 machines)
#    Etape automatisee par dispatcher.py (etape 4 du projet)
ssh lis-cluster-coala-49 "cd /home/.../experiments && \
    eval \"\$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)\" && \
    conda activate nonbenz && \
    nohup python cluster/worker.py \
        --manifest manifest_h6.jsonl \
        --output-root output \
        --claims-dir cluster_state/claims \
        --scratch-root /tmp \
        --concurrency 20 \
        > /tmp/worker_h6.log 2>&1 &"
# (repeter pour 50, 51, ..., 64)

# 5. Surveiller
ls cluster_state/claims/ | wc -l                      # jobs en cours / faits
find output/h6 -name job_status.json | wc -l          # jobs termines

# 6. Quand tout est termine -> finalize.py (etape 4 du projet)
```

## Coordination sans SLURM

**Manifest = source de verite** des jobs a faire.

**Claim = creation atomique** d'un fichier `claims/<job_id>.lock` via
`O_CREAT|O_EXCL`, garanti atomique sur NFS v3+. Si 2 workers tentent
simultanement, l'OS garantit qu'**un seul reussit**.

**Done = presence** de `output/h/config/mol/job_status.json`. Ecrit par
`run_one_job.py` a la fin (succes OU echec). Tant qu'il n'existe pas,
le job est considere comme "a faire".

**Reprise** : il suffit de relancer les workers. Ils sautent automatiquement
les jobs `done` et tentent les autres. Pas besoin de logique de retry
explicite cote worker.

**Locks orphelins** : si un worker meurt en cours de job, son lock reste
mais aucun `job_status.json` n'est ecrit. `recover_stale.py` detecte ce
cas (lock vieux + pas de status) et libere le lock pour qu'un autre
worker reprenne.

## Granularite

1 job = 1 (graph, config). C'est `run_one_job.py` qui :
- copie le `.graph` dans le scratch local du noeud (`/tmp/...`)
- lance test.py + main.py --validate --method md (toutes les solutions
  CSP de cette molecule, en sequentiel dans CE job)
- copie le resultat scratch -> NFS en bloc a la fin
- ecrit `job_status.json`

**Avantage NFS** : 0 octet ecrit sur le NFS pendant l'execution xTB
(qui dure ~5 min en moyenne par job pour h6). La copie finale fait
~50 KB en une seule transaction.

## Configuration

Variables d'env honorees (les workers les heritent et les forcent
single-thread pour empecher les sur-souscriptions de coeurs) :
- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `OPENBLAS_NUM_THREADS=1`
- `NUMEXPR_NUM_THREADS=1`

Sur Precision 7920 (20 coeurs physiques + 20 SMT) :
- `--concurrency 20` recommande (1 job xTB par coeur physique)
- 16 machines x 20 = **320 jobs xTB en parallele** sur le cluster
- **Ne PAS pousser a 40** : SMT introduit des micro-variations selon la
  pression cache, casserait la reproductibilite.

## Ressources COALA (audite sur lis-cluster-coala-49)

| Ressource | Valeur | Note |
|-----------|--------|------|
| CPU | 2x Xeon Gold 5218R, 20 coeurs physiques | 40 logiques (SMT). On utilise les 20 physiques. |
| RAM | 187 Gi | xTB ~500 MB/job pic, 0 risque OOM a 20 jobs |
| `/tmp` | NVMe local, **9 Go libre**, 1777 | scratch local (non NFS). Surveiller `df -h /tmp` si jobs intensifs. |
| `/scratch` | **n'existe pas** | -> on utilise `/tmp` |
| `/dev/shm` | tmpfs RAM ~95 Gi | option si I/O `/tmp` sature (overkill pour MD 1 ps) |
| `/home/COALA/...` | NFSv4 partage | output final ; ecriture atomique requise (cf atomic_io.py) |
| `$TMPDIR` | non defini | tempfile.gettempdir() retombe sur `/tmp` automatiquement |
| xTB | 6.7.1 | OK pour `--md`, `--opt`, GFN2-xTB |
| Python | 3.14.4 (env conda `nonbenz`) | aligne PC local |

**Nettoyage scratch** : worker.py au demarrage scanne `/tmp/coala_*` et supprime
ceux dont mtime > 60 min. Garde les autres (job en cours d'autres workers).

**Atomicite NFS** : `cluster/atomic_io.py::write_atomic_json()` est utilise par
`run_one_job.py` (job_status.json) et `finalize.py` (cluster_meta.json). Pattern
write tmp + os.replace, atomique sur NFSv4 sans flock.

## Format manifest (JSONL)

```json
{"job_id": "h6_default_0-5-6-11-12", "graph": "/abs/path/h6/0-5-6-11-12.graph", "h": "h6", "config": "default", "mol": "0-5-6-11-12"}
{"job_id": "h6_no-freeze_0-5-6-11-12", ...}
```

Le `job_id` est **stable** entre relances : il sert de cle pour les locks
et permet la reprise.

## Format job_status.json (ecrit par run_one_job.py)

```json
{
  "job_id": "h6_default_0-5-6-11-12_<pid>_<ts>",
  "config": "default",
  "h": "h6",
  "mol": "0-5-6-11-12",
  "host": "lis-cluster-coala-49",
  "status": "ok",
  "n_solutions": 7,
  "n_md_outputs": 7,
  "duration_sec": 312.5,
  "started_at": "2026-05-15T22:14:03",
  "ended_at": "2026-05-15T22:19:15"
}
```

`status` peut valoir : `ok`, `failed`, `timeout`, `running` (transitoire,
ne devrait pas persister).
