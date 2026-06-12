# Designer : exécution xTB sur cluster + persistance DB

Ce document décrit la fonctionnalité ajoutée au **designer** (interface de
dessin de benzénoïdes + lancement de jobs CSP/xTB) lors des sessions du
30 mai 2026. Deux capacités principales :

1. **Mode cluster optionnel** : une case à cocher "Exécuter sur cluster
   (xTB distant)" qui déporte tout le calcul xTB (CSP + reconstruction +
   MD + opt + planarité) sur la frontale 192.168.200.49 au lieu du PC
   local. Beaucoup plus rapide pour h≥5.
2. **Persistance DB des résultats** : plus de fichiers XYZ qui s'accumulent
   sur le disque. Après un job réussi, le workdir local est supprimé et
   tout (XYZ gzippés, métriques, bloc original) est accessible depuis la
   DB sqlite via les routes existantes (`/api/mol3d`, `/file`,
   `/api/designer/jobs/<id>/solutions`).

Le document suit l'ordre d'utilisation : préparation (SSH, sync code),
activation, exécution d'un job, vérification, dépannage.

---

## Table des matières

1. [Contexte et motivation](#1-contexte-et-motivation)
2. [Architecture en bref](#2-architecture-en-bref)
3. [Mise en place SSH sans mot de passe](#3-mise-en-place-ssh-sans-mot-de-passe)
4. [Synchronisation du code vers le cluster](#4-synchronisation-du-code-vers-le-cluster)
5. [Activation côté serveur](#5-activation-côté-serveur)
6. [Pipeline d'un job designer](#6-pipeline-dun-job-designer)
7. [Persistance DB et auto-cleanup du workdir](#7-persistance-db-et-auto-cleanup-du-workdir)
8. [Dépannage](#8-dépannage)
9. [Historique des commits](#9-historique-des-commits)

---

## 1. Contexte et motivation

Le designer a été conçu comme un outil de **démonstration** : on dessine
un benzénoïde, on choisit un preset CSP, on lance, on regarde les
solutions générées avec leur verdict PLAN/NON PLAN après optimisation
xTB. C'est utilisé rarement, mais le pipeline de validation
(reconstruction 3D + MD courte + opt xTB + test de planarité) prend
**plusieurs minutes par solution** sur un PC, ce qui devient bloquant
dès qu'on dépasse h=5 avec quelques solutions à valider.

Deux problèmes à résoudre :

- **Vitesse** : envoyer le calcul xTB sur le cluster pour les molécules
  plus grosses, sans pour autant casser le mode local rapide pour les
  petits cas et les démos.
- **Hygiène disque** : un job avec 10-20 solutions produit des centaines
  de fichiers `.xyz`, `.json`, `.inp` dans `viewer/output/designer_jobs/`,
  qui s'accumulent et alourdissent les sauvegardes, le git, l'antivirus,
  et finissent par poser des problèmes de **long path Windows**.

La solution retenue : **DB-first** (tout en sqlite gzippé) avec un **toggle
cluster** dans l'UI. Le mode local par défaut reste rapide et n'a pas
besoin de SSH ; le mode cluster est opt-in et désactivable globalement.

---

## 2. Architecture en bref

### Tables DB utilisées

```
designer_jobs        (existait deja) : metadata du job
                                       (state, progress, summary_json, config_json...)
designer_solutions   (NOUVEAU)       : 1 ligne par solution
                                       (sol_idx, sizes, verdict, angle_deg, ...)
xyz_files            (reutilisee)    : 1 ligne par fichier XYZ
                                       (rel_path PK, content_gz BLOB)
```

`xyz_files` est la même table que celle utilisée par le viewer principal
pour les molécules h6-h9. Cela permet à `/api/mol3d?path=xxx.xyz` de
résoudre automatiquement un XYZ designer : il essaie d'abord le
filesystem, puis le BLOB gzippé en DB.

### Aiguillage local vs cluster

```
POST /api/designer/run avec config.cluster=True/False
        |
        v
runner.run_job(...)
        |
        +--- config.cluster=False ---> subprocess local : csp_solver/main.py
        |                              + _compute_solutions_planarity
        |                              + solutions_db.ingest_local_job
        |
        +--- config.cluster=True ----> cluster_runner.run_job_cluster
        |    (DESIGNER_CLUSTER_ENABLED=1)
        |                              | check_cluster_alive (SSH + conda + path)
        |                              | _test_original_benzenoid (local, rapide)
        |                              | mkdir distant + scp upload graph
        |                              | ssh + python -m csp_solver.main (subprocess)
        |                              | stream stdout pour stages
        |                              | scp -r download des sol_*/
        |                              | _compute_solutions_planarity (local)
        |                              | solutions_db.ingest_local_job
        |
        +--- config.cluster=True ----> echec explicite
             (DESIGNER_CLUSTER_ENABLED!=1)  "Mode cluster demande mais
                                            DESIGNER_CLUSTER_ENABLED n'est
                                            pas 1."
```

Le toggle global `DESIGNER_CLUSTER_ENABLED` (variable d'environnement
côté serveur) sert d'**interrupteur principal** : sans cette variable,
la case à cocher est même cachée dans l'UI (le frontend lit le flag via
`/api/designer/configs`), et un POST forçant `cluster=true` échoue avec
un message explicite (pas de fallback silencieux).

---

## 3. Mise en place SSH sans mot de passe

Le cluster est accessible via un *jump host* (saphir2). La configuration
SSH locale était déjà en place avant cette session — cf
[`doc/doc from commit/DEPLOIEMENT_CLUSTER.md`](doc%20from%20commit/DEPLOIEMENT_CLUSTER.md)
pour le contexte initial. Le contenu de `~/.ssh/config` est :

```
Host saphir2
  HostName 139.124.22.4
  ForwardAgent yes
  User toky-nirina.ramaherisoa

Host 192.168.200.*
  ForwardAgent yes
  ProxyJump saphir2
  User ramaherisoa
```

Cela suffit pour qu'un `ssh 192.168.200.49` traverse automatiquement
saphir2. Mais sans clé SSH, chaque connexion demande deux mots de passe
(un pour saphir2, un pour le cluster), ce qui est incompatible avec un
runner Python qui lance des `subprocess.Popen(["ssh", ...])` en boucle.

On installe donc une **clé SSH ed25519** sur le PC, déposée à la fois sur
saphir2 et sur la machine cluster cible.

### Étape 1 : générer la clé locale

Une fois pour toutes, sur le PC Windows :

```powershell
ssh-keygen -t ed25519 -C "designer-cluster-toky@$env:COMPUTERNAME" `
    -f "$HOME\.ssh\id_ed25519" -N '""'
```

Le `-N ""` produit une clé **sans passphrase**, ce qui est suffisant
pour la phase de test. Pour durcir : générer avec passphrase et
configurer `ssh-agent` en service Windows pour qu'il charge la clé une
fois au démarrage.

### Étape 2 : déposer la clé sur saphir2

Sur Windows (cmd.exe — PowerShell échoue à cause de l'interpolation
`$(...)`) :

```cmd
cmd /c type "%USERPROFILE%\.ssh\id_ed25519.pub" | ssh saphir2 ^
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo OK"
```

Cette commande demande **une fois** le mot de passe saphir2, dépose la
clé publique, sort `OK`. Test :

```cmd
ssh saphir2 "echo SSH SAPHIR2 OK"
```

Doit afficher `SSH SAPHIR2 OK` sans demander de mot de passe.

### Étape 3 : déposer la clé sur le cluster interne

```cmd
cmd /c type "%USERPROFILE%\.ssh\id_ed25519.pub" | ssh 192.168.200.49 ^
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo OK"
```

Demande **une fois** le mot de passe cluster (`ramaherisoa`). La
traversée par saphir2 est désormais silencieuse grâce à la clé qu'on a
déposée à l'étape 2.

### Étape 4 : valider que tout est prêt

```cmd
ssh 192.168.200.49 "eval \"$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)\" && conda activate nonbenz && which xtb && python --version"
```

Doit afficher le chemin de `xtb` et la version Python, sans aucun mot
de passe.

> **Note PowerShell** : si on lance ce genre de commande dans PowerShell
> au lieu de cmd, il faut **encadrer la commande SSH par des
> single-quotes** pour éviter que PowerShell n'interprète localement
> `$(...)`. Le subprocess Python du runner cluster n'a pas ce souci :
> il passe la commande directement à `ssh.exe` sans passer par
> PowerShell.

---

## 4. Synchronisation du code vers le cluster

Le cluster doit avoir une copie à jour de `csp_solver/` dans
`~/projet/csp_solver/` (chemin codé en dur dans `cluster_runner.py`
sous la constante `CLUSTER_PROJECT_PATH`). Quand on modifie le code
local, on resync avant d'utiliser le mode cluster :

```powershell
scp -r "C:\Projets\Projet_Stage_CSP_M2_IMD\csp_solver" 192.168.200.49:~/projet/
```

Cette copie inclut les `__pycache__` (inoffensif). Pour un transfert
plus rapide, on peut faire un `tar | ssh` (cf
[`doc/doc from commit/DEPLOIEMENT_CLUSTER.md`](doc%20from%20commit/DEPLOIEMENT_CLUSTER.md)).

Le pre-flight `check_cluster_alive()` (dans `cluster_runner.py`) vérifie
automatiquement que le code est bien là avec `test -d
{CLUSTER_PROJECT_PATH}/csp_solver`. Si ce test échoue, le job est
marqué `failed` avec un message clair :

```
Cluster indisponible : CLUSTER_PROJECT_PATH=~/projet/csp_solver
introuvable (sync le code avec scp/rsync)
```

---

## 5. Activation côté serveur

Avant de lancer le serveur, exporter la variable d'environnement qui
active globalement le mode cluster :

### PowerShell

```powershell
$env:DESIGNER_CLUSTER_ENABLED = "1"
python server.py --db experiments\v1\db_v2.db --port 8767
```

### cmd.exe

```cmd
set DESIGNER_CLUSTER_ENABLED=1
python server.py --db experiments\v1\db_v2.db --port 8767
```

Une fois le serveur démarré, ouvrir `http://127.0.0.1:8767/designer`
dans le navigateur. Le panneau de configuration CSP doit afficher en
bas une nouvelle case à cocher :

```
[ ] Executer sur cluster (xTB distant)
    Si active, le calcul xTB tourne sur la frontale du cluster
    au lieu de votre PC. Beaucoup plus rapide pour h>=5. ...
```

Si la case n'apparaît pas, c'est que `DESIGNER_CLUSTER_ENABLED` n'est
pas vue par le serveur — la condition est `os.getenv("DESIGNER_CLUSTER_ENABLED", "0") == "1"`.

Pour **désactiver la fonctionnalité**, il suffit de relancer le serveur
sans cette variable d'environnement. La case disparaît de l'UI et le
code cluster n'est même pas chargé.

---

## 6. Pipeline d'un job designer

### Mode local (case décochée)

```
1. POST /api/designer/run
       |  body : { graph_content, config: { preset, validate, ... cluster=False } }
       v
2. runner.run_job(db_path, job_id, project_root) (dans un thread daemon)
       |
       v
3. _test_original_benzenoid(graph, output_dir, project_root)
       |    -> ecrit output_dir/original/original_opt.xyz et planarity.json
       |
       v
4. subprocess.Popen([python, csp_solver/main.py, graph, --validate, --preset, ...])
       |    stdout streame -> parse _STAGE_MARKERS -> update progress
       |    main.py ecrit output_dir/sol_*/source.xyz, md_validation/, ...
       v
5. _compute_solutions_planarity(output_dir, project_root)
       |    -> ecrit sol_dir/planarity.json pour chaque sol_X
       v
6. _count_outputs(output_dir)  <-- captures les counts AVANT cleanup
       v
7. solutions_db.ingest_local_job(...)
       |    a) ingere tous les xyz en table xyz_files (gzippes)
       |    b) ingere chaque sol en designer_solutions
       |    c) ingere le bloc original (xyz + metriques)
       |    d) commit la transaction
       |    e) si n_failed==0 ET pas DESIGNER_KEEP_WORKDIR=1 :
       |          shutil.rmtree(output_dir)
       v
8. jobs.update_job(state="success", summary={
        n_sol_dirs, n_with_xyz, n_with_md,   <-- captures avant cleanup
        n_ingested_db, n_failed_db,
        ingest_complete=True, workdir_deleted=True,
        original={ planar, angle_deg, ... }
   })
```

### Mode cluster (case cochée + `DESIGNER_CLUSTER_ENABLED=1`)

```
1. POST /api/designer/run   (config.cluster=True)
       v
2. runner.run_job -> aiguillage -> cluster_runner.run_job_cluster
       v
3. check_cluster_alive() :
       - ssh + which xtb + which python
       - test -d {CLUSTER_PROJECT_PATH}/csp_solver
       - recupere $HOME du cluster
       -> retourne (True, remote_home)
       v
4. _test_original_benzenoid(graph, output_dir_local, project_root)
       (s'execute en LOCAL, ~5-15s, alimente le bloc original)
       v
5. _ssh "mkdir -p {remote_home}/_designer_cluster_jobs/{job_id}/output"
       v
6. scp graph_local -> 192.168.200.49:{remote_root}/input.graph
       v
7. _build_remote_command -> ssh "{conda init} && cd ~/projet
                              && python -m csp_solver.main {remote_graph} --validate ..."
       Popen stdout stream -> parse stages "cluster_csp", "cluster_md", ...
       v
8. scp -r 192.168.200.49:{remote_output}/ -> output_dir_local.parent
       _merge_scp_output : deplace le contenu vers output_dir_local
       v
9. _compute_solutions_planarity(output_dir_local, project_root) (en LOCAL)
       v
10. solutions_db.ingest_local_job(...)   (idem que mode local)
       v
11. finally : _ssh "rm -rf {remote_root}"  (cleanup garanti même en cas d'echec)
       v
12. jobs.update_job(state="success", summary={..., cluster=True, cluster_host=..., ...})
```

Le `try/finally` autour de toute la logique du `run_job_cluster` garantit
que le **workdir distant est toujours nettoyé**, même si une étape
intermédiaire plante. Pas de garbage qui s'accumule sur le quota
cluster.

### Vue UI à la fin du job

Une modale s'affiche dans le designer avec :

- 4 compteurs : Solutions trouvees, avec source.xyz, validees MD, duree
- Une liste compacte des sols avec verdict (badge couleur) + bouton "3D"
  par ligne (ouvre molviz dans une sous-modale)
- Un bouton "Ouvrir dans le viewer principal" qui ouvre une page
  complète `?job=<id>` (bookmark-able) avec :
  - Statut + compteurs détaillés + configuration en pills
  - Bloc benzénoïde d'entrée (planarité de la molécule tout-hexagones)
  - Tableau complet des solutions avec filtres/tri

---

## 7. Persistance DB et auto-cleanup du workdir

### Le principe

Après un job réussi, **tout** est dans la DB :

- Les XYZ (source.xyz, md_final_opt.xyz, original_opt.xyz) en BLOB gzippé
  dans `xyz_files`, accessibles via `/api/mol3d?path=...` et `/file?path=...`
- Les métriques de chaque sol (sol_idx, sizes, planar, angle_deg, rmsd,
  height, md_verdict, n_attempts) dans `designer_solutions`
- Le bloc original (xyz_path, planar, angle_deg, ...) dans
  `summary_json["original"]` de la row `designer_jobs`

Le **workdir local est supprimé** (`shutil.rmtree(output_dir)`) à la
fin de `ingest_local_job` si `n_failed == 0`. C'est ce qui rend la
migration DB "complète" : plus aucun fichier résiduel après un job.

### Le toggle de debug

Pour garder les fichiers (utile pour inspecter manuellement un job
problématique) :

```powershell
$env:DESIGNER_CLUSTER_ENABLED = "1"
$env:DESIGNER_KEEP_WORKDIR = "1"
python server.py --db ... --port ...
```

Avec ce flag, `workdir_deleted=False` dans le summary et les fichiers
restent sur le fs. L'ingestion DB se fait quand même.

### Garanties de robustesse

Suite à un audit adversarial du code, plusieurs garde-fous ont été
ajoutés :

- **Atomicité** : toute l'ingestion d'un job tient dans **une seule**
  transaction sqlite. Si la connexion plante au milieu, rien n'est
  commit (pas de demi-ingestion). Si une sol particulière échoue (XYZ
  illisible par ex), elle est sautée et `n_failed` est incrémenté, mais
  les autres sont commit à la fin.
- **Flag `ingest_complete`** : l'API ne lit la DB **que si**
  `summary.ingest_complete == True`. Sinon fallback fs. Évite de servir
  un job partiellement ingéré.
- **`PRAGMA busy_timeout = 5000`** : sur Windows les locks sqlite sont
  stricts ; le timeout permet de survivre à une requête API
  concurrente pendant que le runner écrit.
- **Fermeture explicite des connexions** : `conn.close()` dans un
  `finally` (helper `_open_conn`), évite les fuites de handles sur
  Windows.

### Script de nettoyage one-shot

Pour les jobs antérieurs à l'auto-cleanup (qui ont leurs résultats à
la fois en DB et sur fs), un script :

```cmd
python tmp\cleanup_old_designer_workdirs.py --db experiments\v1\db_v2.db
```

Par défaut **dry-run** (liste ce qui serait supprimé). Pour appliquer :
ajouter `--apply`. Le script ne touche **que** les jobs dont
`summary.ingest_complete == True` (donc déjà en DB), et avec un
garde-fou de chemin (doit contenir `designer_jobs`).

---

## 8. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| Erreur au démarrage du serveur | Schéma SQL ou import | Lire la console Flask, regarder le traceback |
| Case "Exécuter sur cluster" invisible | `DESIGNER_CLUSTER_ENABLED` non défini ou différent de `"1"` | Vérifier `echo $env:DESIGNER_CLUSTER_ENABLED` dans le terminal du serveur ; relancer après `$env:DESIGNER_CLUSTER_ENABLED = "1"` |
| Job cluster failed avec "Cluster indisponible : Timeout >30s" | Réseau coupé, VPN tombé, cluster down | Tester manuellement `ssh 192.168.200.49 hostname` |
| Job cluster failed avec "CLUSTER_PROJECT_PATH... introuvable" | Code pas synchronisé sur le cluster | `scp -r csp_solver 192.168.200.49:~/projet/` |
| Job hang en `cluster_check` | SSH demande un mot de passe à cause d'une clé non installée | Refaire les étapes 2-3 de la section 3 |
| Compteurs "Solutions trouvees" à 0 dans la modale | (Devrait être réglé) ; sinon, cache navigateur | `Ctrl+F5` pour forcer le reload du JS |
| Bouton "Ouvrir dans le viewer principal" grisé | Pas de solutions ingérées (`n_ingested_db == 0` ET `n_sol_dirs == 0`) | Normal si le job n'a pas produit de sol. Sinon, regarder `error` dans le job |
| Page `?job=<id>` vide | DB sans la row, ou URL mal formée | Vérifier en SQL : `SELECT * FROM designer_jobs WHERE job_id='...'` |
| Workdir orphelin sur le cluster | (Devrait pas arriver) | `ssh 192.168.200.49 "ls -la ~/_designer_cluster_jobs/"` puis `rm -rf` manuel |
| 3D ne s'affiche pas | XYZ pas en DB et pas sur fs | Vérifier `SELECT rel_path FROM xyz_files WHERE rel_path LIKE '%<job_id>%'` |

### Logs utiles

- **Serveur Flask** : stdout/stderr du terminal qui a lancé `server.py`
- **subprocess xTB** : capturé dans `summary.stdout_tail[-50:]` du job
- **Job en DB** : `sqlite3 db_v2.db "SELECT state, error, summary_json FROM designer_jobs WHERE job_id='...'"`
- **Workdir cluster avant cleanup** : ajouter `DESIGNER_KEEP_WORKDIR=1` côté serveur pour conserver

---

## 9. Historique des commits

Les modifications ont été déployées en plusieurs commits sur la branche
`dev`, dans cet ordre :

| Commit | Sujet |
|---|---|
| `e383fde` | Phase 2 : exécution xTB optionnelle sur cluster + persistance DB initiale |
| `66694ee` | Fixes critiques de l'audit adversarial (atomicité, busy_timeout, cleanup remote, validation `CLUSTER_PROJECT_PATH`) |
| `e52ce89` | Finalisation migration DB : workdir auto-supprimé, bloc original en DB, script cleanup one-shot |
| `bd73787` | Fix compteurs UI (capturer `_count_outputs` avant rmtree) + tentative de réaffectation du bouton "Ouvrir dans le viewer principal" |
| `2639128` | Rollback de la réaffectation du bouton — il ouvre à nouveau la page `?job=<id>` du viewer principal |

### Fichiers principaux

- `viewer/designer/solutions_db.py` (nouveau) — schémas + ingestion + lecture DB
- `viewer/designer/cluster_runner.py` (nouveau) — runner SSH isolé
- `viewer/designer/runner.py` — aiguillage local/cluster + ingestion DB
- `viewer/designer/api.py` — exposition `cluster_enabled` dans `/configs`,
  branche DB de `/solutions`, helpers `_build_sol_dict_from_db` etc.
- `viewer/designer/static/designer.js` — case à cocher conditionnelle,
  liste compacte des sols, bouton viewer principal
- `viewer/designer/tests/test_cluster_xtb.py` — test SSH+xtb end-to-end (validation phase 1)
- `viewer/designer/tests/test_phase2_smoke.py` — 7 smoke tests
- `viewer/designer/scripts/cleanup_old_workdirs.py` — purge one-shot des anciens workdirs
