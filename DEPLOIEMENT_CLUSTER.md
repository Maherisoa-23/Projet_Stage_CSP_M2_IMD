# Déploiement du projet sur le cluster COALA

Ce document retrace, dans l'ordre, les étapes que j'ai suivies pour passer du
projet tournant en local (Windows, mon PC) à un projet exploité sur le cluster
COALA du LIS. Il sert à la fois de mémo personnel et de support si on me
demande "comment tu as fait".

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

## 12. Où on en est

**État actuel** : la relance des 50 jobs en timeout est en cours sur les
16 machines avec `--timeout 1200`. À surveiller via `dispatcher.py status`,
puis lancer `finalize.py` pour produire le `cluster_meta.json` final et le
`view.html` agrégé.

**Reste à faire** :
1. Récupérer les résultats h6 sur le PC local (commande `tar | ssh` inverse).
2. Lancer h7 (126 × 8 = 1008 jobs), h8 (376 × 8 = 3008), h9 (2418 × 8 = 19344).
3. Pour h9 : prévoir un timeout encore plus large pour `no-table` et surveiller
   le quota disque NFS (les outputs MD prennent de la place).

## Annexe — Commandes utiles à mémoriser

```bash
# Activer l'environnement conda dans une nouvelle session
eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)"
conda activate nonbenz

# Voir la charge des machines
cfree
cw
cwho

# Lister les workers actifs sur les 16 machines
for i in $(seq 49 64); do
  echo -n "coala-$i: "
  ssh -o BatchMode=yes lis-cluster-coala-$i 'pgrep -af worker.py | head -1'
done

# Vérifier le scratch local des 16 machines
for i in $(seq 49 64); do
  ssh -o BatchMode=yes lis-cluster-coala-$i 'ls /tmp/coala_* 2>&1 | head -1'
done
```
