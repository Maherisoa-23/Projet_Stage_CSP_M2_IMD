# Déploiement du projet sur le cluster COALA

Ce document retrace, dans l'ordre, les étapes que j'ai suivies pour passer du
projet tournant en local (Windows, mon PC) à un projet exploité sur le cluster
COALA du LIS. Il sert à la fois de mémo personnel et de support.

---

## 1. Cible et contraintes

- **Cluster** : COALA du LIS, 64 machines Linux, accès via un *jump host*
  (saphir2, IP publique 139.124.22.4). Pas de SLURM, pas de file d'attente :
  on parle directement aux machines en SSH.
- **Disque partagé** : `/home/COALA/ramaherisoa/` est monté en NFS sur les 16
  machines de calcul → un fichier écrit ici depuis n'importe quelle machine
  est visible partout.
- **Comptes** : login `toky-nirina.ramaherisoa` sur saphir2,
  login `ramaherisoa` sur les machines du cluster (deux mots de passe
  distincts).
- **Choix** : on travaille uniquement sur les **Configs 5** (lis-cluster-coala-
  49 à 64). Pourquoi : 16 machines homogènes, 192 Go RAM, Ubuntu 22.04 récent,
  CPU identiques (Xeon Gold 5218R 20 cœurs) → reproductibilité bit-à-bit
  garantie entre les 16. Les Configs 1-4 (Ubuntu 18, Python 3.6, CPU
  hétérogènes) sont écartées.

## 2. Configuration SSH locale

Sur mon PC Windows, dans `C:\Users\win10\.ssh\config` :

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

`ProxyJump` automatise la double connexion : `ssh 192.168.200.58` ouvre une
session via saphir2 jusqu'à la machine cible. Le mot de passe final
(authentification sur la lame) ne transite pas en clair par saphir2 — la
deuxième session SSH est chiffrée de bout en bout.

Première connexion : `ssh 192.168.200.58` → tape successivement les deux
mots de passe.

## 3. Installation de l'environnement Python (Miniforge + Conda)

Le système n'avait pas `pip` ni `python3-venv` (et pas de droits root pour les
installer). Solution standard sur cluster sans root : **Miniforge**, un
mini-installeur Conda installé dans le home, donc visible depuis les 16
machines via NFS.

```bash
# Sur lis-cluster-coala-49
cd ~
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
# - accepter la licence
# - emplacement par défaut : ~/miniforge3
# - "modifier .bashrc ?" → NO  (on activera conda à la demande)
```

Activation manuelle dans une session :

```bash
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
```

Création de l'environnement projet en Python 3.14 (même version que mon PC
local pour la reproductibilité) :

```bash
conda create -n nonbenz -c conda-forge python=3.14 pip -y
conda activate nonbenz
```

## 4. Installation de xTB et des paquets Python

xTB n'est pas un paquet pip — c'est un binaire externe (Fortran). Heureusement
disponible sur conda-forge :

```bash
conda install -c conda-forge xtb -y
```

Vérification :

```bash
xtb --version | head -3   # doit afficher "xtb version 6.7.1"
```

Puis les 3 paquets Python du projet, aux versions exactes du venv local :

```bash
pip install lxml==6.0.4 networkx==3.6.1 pycsp3==2.5.1
```

## 5. Audit du système (avant de transférer le code)

Sur lis-cluster-coala-49 :

```bash
df -h /tmp /home
mount | grep -E "tmp|home"
free -h
nproc
```

Constats clés :
- **Pas de `/scratch`** dédié → on utilisera `/tmp` (NVMe local, ~9 Go libre)
  comme scratch pour les fichiers temporaires xTB.
- **/home/COALA est NFS** depuis lis-srv-coala : ne PAS y faire écrire xTB
  pendant les jobs (saturation réseau garantie).
- 192 Go de RAM, 40 threads logiques (20 cœurs physiques × SMT).

## 6. Transfert du code depuis Windows vers le cluster

`rsync` n'est pas installé sous Git Bash sur Windows. Solution alternative
qui n'utilise que les outils natifs : **`tar` piped through `ssh`**.

Depuis Git Bash, dans le dossier du projet :

```bash
tar -czf - \
  --exclude='venv' --exclude='.git' --exclude='.claude' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
  --exclude='csp_solver/output' --exclude='csp_solver/experiments/output' \
  --exclude='csp_solver/experiments/report' \
  --exclude='non_benzenoid_generator/output' \
  --exclude='optimisation_et_test_planarite' --exclude='pah-tools-master' \
  --exclude='generate_hep_v3.py' --exclude='implementation_csp' \
  --exclude='*.tex' \
  . | ssh 192.168.200.58 \
    "mkdir -p /home/COALA/ramaherisoa/projet && \
     tar -xzf - -C /home/COALA/ramaherisoa/projet"
```

Le pipe `|` envoie l'archive compressée directement sur stdin de la commande
distante. Aucun fichier intermédiaire sur disque.

## 7. Smoke test : 1 job sur 1 machine

Test isolé pour valider que la chaîne complète (CSP + reconstruction + xTB
MD + planarité) fonctionne sur le cluster avant de paralléliser. C'est l'unité
atomique du pipeline (`run_one_job.py`) :

```bash
cd /home/COALA/ramaherisoa/projet/csp_solver/experiments
mkdir -p /tmp/smoke_scratch
mkdir -p /home/COALA/ramaherisoa/projet/_smoke_output

time python run_one_job.py \
  --graph plane/benzdb/h3/1-3-4.graph \
  --config default \
  --output-root /home/COALA/ramaherisoa/projet/_smoke_output \
  --scratch-root /tmp/smoke_scratch \
  --timeout 300
```

Résultat : "Fin OK (11.7s)", `job_status.json` avec `status: "ok"`, scratch
nettoyé après le run. ✅

## 8. Mise en place de SSH par clés (pour les workers parallèles)

Le dispatcher lance des workers via SSH non-interactif sur les 16 machines :
impossible de taper 16 mots de passe. Il faut une **clé SSH** + activation
de `BatchMode`.

Comme `~/.ssh/` est partagé en NFS entre les 16 machines, on génère la clé
**une seule fois** sur la 49 et on s'auto-autorise — toutes les 16 machines
reconnaissent automatiquement la clé.

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

Pré-autoriser les fingerprints des 16 machines (évite le prompt
"continue connecting?") :

```bash
for i in $(seq 49 64); do
  ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
      lis-cluster-coala-$i hostname
done
```

Vérification finale :

```bash
ssh -o BatchMode=yes lis-cluster-coala-50 hostname    # → "lis-coala-cluster-50"
```

## 9. Test du dispatcher SSH sur 1 machine (h3 default)

Première validation du dispatcher en mode SSH (3 jobs h3, 1 host) :

```bash
mkdir -p /home/COALA/ramaherisoa/projet/_test_ssh/{output,claims,state}

python cluster/build_manifest.py plane/benzdb/h3 --configs default \
  --output /home/COALA/ramaherisoa/projet/_test_ssh/manifest.jsonl
# → 3 jobs ecrits

python cluster/dispatcher.py start --mode ssh \
  --hosts lis-cluster-coala-49 \
  --remote-cwd /home/COALA/ramaherisoa/projet/csp_solver/experiments \
  --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \
  --conda-env nonbenz \
  --manifest .../manifest.jsonl \
  --output-root .../output \
  --claims-dir .../claims \
  --scratch-root /tmp \
  --concurrency 2 --timeout 300 \
  --state-dir .../state
```

Suivi avec `dispatcher.py status` toutes les 10 s, puis `finalize.py` à la fin.

Résultat : 3/3 OK, 13 s wall-clock, `cluster_meta.json` propre. ✅

## 10. Test multi-machines (h3 × 8 configs = 24 jobs)

Même procédure mais avec les 16 hosts :

```bash
HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python cluster/dispatcher.py start --mode ssh \
  --hosts "$HOSTS" \
  ... \
  --concurrency 2 --timeout 300
```

Résultat : 24/24 OK en 63 s. Quelques machines reçoivent l'essentiel des jobs
(les premières prêtes vident le manifest avant que les autres soient activées)
— c'est attendu pour un manifest court. Sur les gros runs (h6+), la
distribution s'équilibre naturellement.

## 11. Run h6 (44 graphes × 8 configs = 352 jobs)

```bash
mkdir -p /home/COALA/ramaherisoa/projet/_h6_run/{output,claims,state}

python cluster/build_manifest.py plane/benzdb/h6 --configs all \
  --output /home/COALA/ramaherisoa/projet/_h6_run/manifest.jsonl
# → 352 jobs ecrits

HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python cluster/dispatcher.py start --mode ssh \
  --hosts "$HOSTS" \
  --manifest .../manifest.jsonl \
  --output-root .../output \
  --claims-dir .../claims \
  --scratch-root /tmp \
  --concurrency 4 --timeout 300 \
  --state-dir .../state
```

Résultat brut : **302 OK / 50 timeout / 0 failed** en ~6 min.

### Diagnostic des timeouts

Tous les timeouts sont concentrés sur les configs `no-table` (avec ou sans
`no-freeze`). Causalité : `no-table` désactive la table de voisinage, le CSP
génère beaucoup plus de solutions, certains jobs dépassent les 300 s.

| Config                               | OK   | Timeout |
|--------------------------------------|------|---------|
| no-freeze_no-table                   | 15   | **29**  |
| adj-57_no-freeze_no-table            | 36   | 8       |
| no-table                             | 36   | 8       |
| adj-57_no-table                      | 40   | 4       |
| no-freeze                            | 43   | 1       |
| autres (default, adj-57, etc.)       | 44   | 0       |

### Relance ciblée avec `recover.py`

`recover.py` génère un sous-manifest à partir des jobs en timeout, et avec
`--reset` supprime leurs `job_status.json` + claims pour qu'ils redeviennent
disponibles :

```bash
python cluster/recover.py \
  --manifest .../manifest.jsonl \
  --output-root .../output \
  --claims-dir .../claims \
  --status timeout --reset
# → manifest_retry.jsonl (50 jobs)
```

Puis on relance le dispatcher avec un timeout généreux :

```bash
python cluster/dispatcher.py start --mode ssh \
  --hosts "$HOSTS" \
  --manifest .../manifest_retry.jsonl \
  --output-root .../output \
  --claims-dir .../claims \
  --scratch-root /tmp \
  --concurrency 4 --timeout 1200 \
  --state-dir .../state
```

Avant la relance : on supprime `dispatcher_state.json` du run précédent
(sinon le démarrage peut afficher des "TIMEOUT host non joignable" liés à
l'ancien état).

```bash
rm /home/COALA/ramaherisoa/projet/_h6_run/state/dispatcher_state.json
```

## 12. Finalisation et récupération des résultats h6

Une fois `Done = 352/352` avec 0 timeout (après recover éventuel), on agrège :

```bash
python cluster/finalize.py /home/COALA/ramaherisoa/projet/_h6_run/output/h6 \
  --manifest /home/COALA/ramaherisoa/projet/_h6_run/manifest.jsonl
```

Cela produit dans `_h6_run/output/h6/` :
- `<config>/data.json` pour chaque config
- `cluster_meta.json` (résumé global du run)
- `view.html` (rapport agrégé)

**Récupération sur le PC Windows** (depuis Git Bash, dans le dossier du
projet ; on crée d'abord `cluster_results/` qui accueillera tous les niveaux) :

```bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/second try with scipt and CSP"
mkdir -p cluster_results
cd cluster_results

ssh 192.168.200.58 \
  "tar -czf - -C /home/COALA/ramaherisoa/projet/_h6_run/output h6" \
  | tar -xzf -
```

Logique : `tar | ssh` inverse du transfert d'aller. La machine distante crée
l'archive, l'envoie sur stdout, le PC l'extrait à la volée dans le cwd
(`cluster_results/`).

Ensuite `cluster_results/h6/view.html` ouvre le rapport dans un navigateur.

## 13. Lancer h7 / h8 / h9

### Sessions persistantes avec `tmux`

Avant de lancer un long run, on entre dans une session tmux côté cluster.
Si la connexion SSH du PC tombe, le dispatcher continue à tourner.

```bash
ssh 192.168.200.58
tmux new -s runs

# dans tmux :
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz
cd /home/COALA/ramaherisoa/projet/csp_solver/experiments
```

Détacher : `Ctrl+B` puis `D`. Reprendre plus tard : `tmux attach -t runs`.

### h7 (1 008 jobs)

```bash
mkdir -p /home/COALA/ramaherisoa/projet/_h7_run/{output,claims,state}

python cluster/build_manifest.py plane/benzdb/h7 --configs all \
  --output /home/COALA/ramaherisoa/projet/_h7_run/manifest.jsonl

HOSTS=$(seq 49 64 | sed 's/^/lis-cluster-coala-/' | paste -sd,)

python cluster/dispatcher.py start --mode ssh \
  --hosts "$HOSTS" \
  --remote-cwd /home/COALA/ramaherisoa/projet/csp_solver/experiments \
  --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \
  --conda-env nonbenz \
  --manifest /home/COALA/ramaherisoa/projet/_h7_run/manifest.jsonl \
  --output-root /home/COALA/ramaherisoa/projet/_h7_run/output \
  --claims-dir /home/COALA/ramaherisoa/projet/_h7_run/claims \
  --scratch-root /tmp \
  --concurrency 4 --timeout 1800 \
  --state-dir /home/COALA/ramaherisoa/projet/_h7_run/state
```

### h8 (3 008 jobs) et h9 (19 344 jobs)

Strictement le même pattern que h7, en remplaçant les chemins `_h7_run` par
`_h8_run` / `_h9_run`, le dossier source `plane/benzdb/h7` par `plane/benzdb/
h8` ou `h9`, et en augmentant `--timeout` :
- h8 : `--timeout 3600` (1 h)
- h9 : `--timeout 7200` (2 h) — molécules à 9 hexagones, MD plus longue.
  À lancer le soir, sera là le lendemain matin.

Avant h9 : vérifier l'espace NFS avec `df -h /home/COALA`. Compresser et
libérer les outputs des niveaux précédents si nécessaire :

```bash
tar -czf _h6_run.tar.gz _h6_run/output && rm -rf _h6_run/output
```

### Récupération de chaque niveau

Même schéma que h6 :

```bash
ssh 192.168.200.58 \
  "tar -czf - -C /home/COALA/ramaherisoa/projet/_h7_run/output h7" \
  | tar -xzf -
```

(idem pour h8, h9 — pense à `cd cluster_results/` avant)

## 14. Piège important : "TIMEOUT host non joignable" est cosmétique

Au démarrage du dispatcher, on voit parfois cette erreur sur certaines (ou
toutes) les lignes `[ssh#X] -> ...`. C'est trompeur : le worker a souvent
bien démarré via `nohup` côté distant, mais le dispatcher n'a pas reçu la
confirmation du PID dans son délai imparti.

**Procédure de vérification AVANT de relancer** (sinon on duplique les
workers) :

```bash
# Y a-t-il déjà des workers actifs ?
for i in $(seq 49 64); do
  ssh -o BatchMode=yes -o ConnectTimeout=5 lis-cluster-coala-$i \
    'pgrep -af worker.py | grep -v "bash -c" | head -1'
done
```

- Si la sortie liste des `python cluster/worker.py ...` → **NE PAS relancer**.
  Les workers tournent. Suivre avec `dispatcher.py status`.
- Si la sortie est vide → relance possible :
  ```bash
  rm -f /home/COALA/ramaherisoa/projet/_hN_run/state/dispatcher_state.json
  python cluster/dispatcher.py start --mode ssh ...   # même commande
  ```

## 15. Gestion des timeouts en cours de run (générique)

Si à la fin d'un run on a des `Timeout : X`, on relance ciblé :

```bash
python cluster/recover.py \
  --manifest /home/COALA/ramaherisoa/projet/_hN_run/manifest.jsonl \
  --output-root /home/COALA/ramaherisoa/projet/_hN_run/output \
  --claims-dir /home/COALA/ramaherisoa/projet/_hN_run/claims \
  --status timeout --reset
# → manifest_retry.jsonl (X jobs)

rm -f /home/COALA/ramaherisoa/projet/_hN_run/state/dispatcher_state.json

python cluster/dispatcher.py start --mode ssh \
  --hosts "$HOSTS" \
  ... \
  --manifest /home/COALA/ramaherisoa/projet/_hN_run/manifest_retry.jsonl \
  --timeout <doublé>    # ex. 1200 → 2400 → 3600
```

## 16. Où on en est

**État actuel** : h6, h7, h8 finalisés. h9 finalisé après détour technique
(cf. §17 ci-dessous).

## 17. h9 — viewer SQLite + découverte des « solutions géométriquement infaisables »

### Le problème : volume

h9 c'est ~2 419 mols × 8 configs ≈ 19 344 jobs CSP+xTB, et au total
**~1,5 M solutions individuelles**. Le viewer HTML monolithique utilisé pour
h3-h8 (un seul `view.html` qui charge tout `data.json` en mémoire JS) **fait
planter le navigateur** à cette échelle : ~600 MB de JSON pour la seule
config `no-freeze_no-table`.

### La solution : viewer SQLite + serveur Flask local

J'ai écrit un viewer dédié sous
[`csp_solver/experiments/h9_viewer/`](csp_solver/experiments/h9_viewer/) :

- **Backend** : SQLite (`h9.db`) indexant l'arborescence de `cluster_results/h9/`
  sans la modifier. Schéma dans `schema.sql`.
- **Builder** : `build_db.py` scanne en parallèle (multiprocessing) les
  ~19 k mols, calcule la planarité ACP de chaque `md_final_opt.xyz` et
  insère ~1,5 M lignes en quelques minutes (sur cluster ext4 ; sur NTFS
  Windows c'est 1-2 h, à éviter — préférer lancer le `build_db.py` côté
  cluster avec `--root _h9_run/output/h9` puis rapatrier `h9.db`).
- **Serveur** : `server.py` (Flask, écoute sur `127.0.0.1:8765`). API JSON
  paginée pour les molécules et les solutions, sert les xyz à la demande.
- **Frontend** : SPA en JS vanilla avec lazy-loading + loading screens.
  Aucune ressource externe, fonctionne offline.
- **MAJ incrémentale** : `update_db.py` rescanne un sous-ensemble de mols
  (utile si on modifie ciblément quelques résultats).

Lancer : `python csp_solver/experiments/h9_viewer/build_db.py` (une fois),
puis `python csp_solver/experiments/h9_viewer/server.py` et ouvrir
http://127.0.0.1:8765.

### La découverte : `n_solutions_csp ≠ n_md_outputs`, et c'est normal

En regardant un `job_status.json` h9 typique on voit par exemple
`n_solutions: 2122` mais `n_md_outputs: 1372` : 750 solutions CSP n'ont pas
de `md_final_opt.xyz`. Mon premier réflexe a été : « le walltime SLURM a
coupé la boucle MD avant la fin ». J'ai donc construit toute une
infrastructure pour relancer ces sols ciblément (build_partial_manifest +
worker_partial + run_partial_job) puis l'ai exécutée.

**Tous les sols ré-essayés ont échoué.** Le diagnostic en remontant
l'exception côté cluster a montré :

```
ValueError: Hexagone 4: impossible de creer un pentagone,
aucun sommet interieur libre. Pattern=(1, 1, 1, 1, 1, 0)
```

L'erreur vient de `csp_solver/reconstruction/topology.py::_apply_pentagon`,
qui refuse de placer un pentagone sur un hexagone dont 5 côtés sur 6 sont
déjà partagés avec des voisins (pas de sommet libre pour transformer le
6-cycle en 5-cycle).

**Conclusion** : ces 750 sols sont **CSP-valides mais géométriquement
infaisables**. Avec les flags `--no-freeze` et `--no-table`, le solveur
CSP accepte des assignations combinatoires que la reconstruction 3D ne
peut pas matérialiser. Le run cluster initial faisait déjà la bonne chose :
`main.py` essaie de reconstruire, attrape `ValueError`, et **passe au
sol suivant** sans rien écrire dans le sol_dir → le dossier reste vide.
Donc :

> **Un sol_dir vide après un run cluster ≠ un job interrompu.**
> C'est presque toujours une solution géométriquement inaccessible.

Sur h9 / `no-freeze_no-table` ça représente jusqu'à **~75 %** des sols CSP
sur certaines mols. Sur h6, la part est négligeable ; c'est pour ça qu'on
ne l'avait pas vu plus tôt.

### Ce que j'ai fait suite à cette découverte

1. **Supprimé toute l'infra de relance partielle** (`run_partial_job.py`,
   `cluster/build_partial_manifest.py`, `cluster/worker_partial.py`,
   `h9_viewer/complete_jobs.py`, `h9_viewer/export_missing.py`). Inutile
   puisque ces sols ne peuvent pas être réalisés.

2. **Étendu le schéma SQLite** avec deux compteurs supplémentaires sur
   chaque `(config, mol)` :
   - `n_geom_infeasible` : sols sans `source.xyz`
     (= `ValueError` pendant la reconstruction).
   - `n_xtb_failed` : sols avec `source.xyz` mais sans `md_final_opt.xyz`
     (xTB n'a pas convergé ; rare).
   
   Invariant (approximatif) :
   `n_solutions_csp ≈ n_md_completed + n_geom_infeasible + n_xtb_failed`.

3. **Adapté l'affichage du viewer** : la liste des molécules expose une
   colonne dédiée « Géom. ✗ » qui chiffre les sols inaccessibles, au lieu
   d'un badge orange « X/Y » ambigu qui suggérait à tort un travail
   inachevé. Le panneau d'une molécule détaille `CSP combinatoire`,
   `MD validées`, `Géom. infaisables`, `xTB échec`.

4. **Documenté la sémantique** dans le README du viewer h9
   ([`csp_solver/experiments/h9_viewer/README.md`](csp_solver/experiments/h9_viewer/README.md))
   et ajouté une note dans
   [`csp_solver/experiments/cluster/README.md`](csp_solver/experiments/cluster/README.md)
   (« si tu vois `n_solutions_csp > n_md_outputs`, ne tente pas de
   relancer les manquants — ils ne peuvent pas être réalisés »).

### À retenir pour la suite

- **Run cluster terminé = run cluster terminé.** L'écart
  `n_solutions_csp - n_md_outputs` n'est pas une dette de calcul, c'est
  une mesure intrinsèque de la fraction CSP-valide-mais-impossible.
- **Le viewer h9 est généralisable** : si jamais on attaque h10 ou plus
  large, la même architecture SQLite + Flask passe à l'échelle ; pas
  besoin de ré-inventer.
- **Build de la DB** : préférer le faire **côté cluster** (ext4 +
  multiprocessing rapide) puis rapatrier `h9.db`, plutôt que de scanner
  `cluster_results/h9/` depuis Windows (NTFS très lent sur les dossiers
  à milliers d'entrées).

## Annexe — Commandes utiles à mémoriser

### Activation et infos cluster

```bash
# Activer l'environnement conda dans une nouvelle session
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz

# Voir la charge des machines
cfree
cw
cwho
```

### Suivre l'avancement d'un run (dispatcher status)

```bash
# Remplacer hN par h6, h7, h8 ou h9
python cluster/dispatcher.py status \
  --output-root /home/COALA/ramaherisoa/projet/_hN_run/output \
  --manifest /home/COALA/ramaherisoa/projet/_hN_run/manifest.jsonl \
  --claims-dir /home/COALA/ramaherisoa/projet/_hN_run/claims \
  --concurrency 4
```

À relancer toutes les ~20-60 s pour voir l'avancement (Done X/Y).

### Diagnostiquer l'état des machines

```bash
# Lister les workers actifs sur les 16 machines
for i in $(seq 49 64); do
  echo -n "coala-$i: "
  ssh -o BatchMode=yes lis-cluster-coala-$i 'pgrep -af worker.py | head -1'
done

# Vue plus large (worker + main.py + run_one_job + xtb)
for i in $(seq 49 64); do
  echo -n "coala-$i: "
  ssh -o BatchMode=yes lis-cluster-coala-$i \
    'pgrep -af "csp_solver|run_one_job|worker.py|xtb" | grep -v "bash -c" | head -1'
done

# Vérifier le scratch local des 16 machines
for i in $(seq 49 64); do
  ssh -o BatchMode=yes lis-cluster-coala-$i 'ls /tmp/coala_* 2>&1 | head -1'
done
```

### Arrêt d'urgence (stop tout sur les 16 machines)

À utiliser quand on veut couper net un run pour pousser une nouvelle version
du code. **Important :** tuer dans l'ordre worker → run_one_job → main.py →
xtb. Les enfants peuvent survivre à un parent tué (ils deviennent orphelins
de init), donc il faut explicitement tous les viser. Souvent une seule passe
ne suffit pas car des nouveaux enfants peuvent spawner pendant le kill — on
boucle 3 fois.

```bash
for n in 1 2 3; do
  for i in $(seq 49 64); do
    ssh -o BatchMode=yes -o ConnectTimeout=5 lis-cluster-coala-$i \
      'pkill -9 -f "cluster/worker.py"; \
       pkill -9 -f "run_one_job.py"; \
       pkill -9 -f "csp_solver/main.py"; \
       pkill -9 -f "csp_solver/test.py"; \
       pkill -9 -f xtb' 2>/dev/null
  done
  sleep 5
done

# Cleanup scratch
for i in $(seq 49 64); do
  ssh -o BatchMode=yes lis-cluster-coala-$i 'rm -rf /tmp/coala_* 2>/dev/null'
done
```

### Push incrémental d'une poignée de fichiers (depuis Git Bash)

Pratique quand on a juste quelques fichiers modifiés à propager (vs un retransfert
complet du projet).

```bash
cd "/e/Stage AMU CSP IMD M2/Generation des molecules pour la table de voisinage/second try with scipt and CSP"

tar -czf - \
  csp_solver/reconstruction/assembler.py \
  csp_solver/experiments/cluster/worker.py \
  # ... autres fichiers ...
  | ssh 192.168.200.58 "tar -xzf - -C /home/COALA/ramaherisoa/projet"
```

### Choisir la concurrency

Chaque machine a 20 cœurs physiques (Xeon Gold 5218R) et 192 Go RAM. Avec
`OMP_NUM_THREADS=1`, 1 job xTB = 1 cœur.

- `--concurrency 4` : utilisation conservatrice (~20 % CPU), bon pour debug.
- `--concurrency 16` : recommandé en production. Marge OS, déterministe.
- `--concurrency 20` : saturation des cœurs physiques. Maximum sain.
- `--concurrency 40` : utilise le SMT/HT — **à éviter**, risque de divergence
  bit-à-bit à cause de la pression cache hyperthreadée.

Total slots = 16 machines × concurrency. À 20 → 320 slots simultanés.
