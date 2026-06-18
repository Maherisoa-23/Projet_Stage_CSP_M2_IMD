# Procedure : lancer le bench ACE vs Choco sur le cluster COALA

## Contexte

Le code du bench est commit sur `dev` (commit `48d57b3`). Le sandbox de
mon agent bloque les SSH directs vers les workers `192.168.200.49..64`,
donc tu dois lancer le dispatcher toi-meme.

11 956 instances a traiter (h3-h9 x 4 configs C1/C2/C3/Ctopo).
Estimation cluster : **4-8 heures**.

---

## Etape 1 : Pull le code sur le cluster

Sur ta machine locale :

```bash
ssh 192.168.200.49     # ou n'importe quel worker
cd ~/projet
git fetch origin
git checkout dev
git pull
conda activate nonbenz
```

## Etape 2 : Setup la DB (populate les pending)

Toujours sur le worker :

```bash
python -m csp_solver.final.bench_dispatcher setup \
    --db ~/solver_bench.db \
    --project-root ~/projet \
    --sizes 3,4,5,6,7,8,9 \
    --configs C1,C2,C3,Ctopo
```

Sortie attendue : **11 956 rows pending**, repartis comme :
- h3-h5 : 100 (deja teste en local)
- h6-h7 : 680
- h8 : 1 504
- h9 : 9 672

## Etape 3 : Lance le dispatcher en background

```bash
nohup python -m csp_solver.final.bench_dispatcher run \
    --db ~/solver_bench.db \
    --workers 49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64 \
    --batch-size 8 \
    --timeout-s 300 \
    --ssh-timeout 2000 \
    > ~/bench_dispatcher.log 2>&1 &
echo "PID = $!"
```

Le `nohup ... &` rend le dispatcher independant de ta session SSH : tu
peux te deconnecter, il continue.

**Note :** chaque worker (16 au total) fait des batches de 8 instances en
serie ; chaque instance teste ACE puis Choco avec un timeout de 300 s
par solveur. SSH timeout 2 000 s = 33 min par batch, permet d'absorber
1 ou 2 timeouts solveurs sans casser le batch.

## Etape 4 : Monitorer

```bash
# Suivi log temps-reel
tail -f ~/bench_dispatcher.log

# Snapshot stats (peut etre lance depuis n'importe ou)
python -m csp_solver.final.bench_dispatcher status --db ~/solver_bench.db
```

Le dispatcher imprime un HEARTBEAT toutes les 60 s avec les stats
globales. Tu peux verifier la progression a tout moment.

## Etape 5 : Quand fini

Le dispatcher s'arrete tout seul quand toutes les instances sont en
status `done` ou `failed`. Le log finit par `=== ALL WORKERS DONE ===`.

Transfere la DB resultat sur ta machine :

```bash
# Depuis ta machine locale
scp 192.168.200.49:~/solver_bench.db /c/Projets/Projet_Stage_CSP_M2_IMD/experiments/final/
```

Puis dis-moi "fini" -- je ferai l'analyse et le rapport
`doc/choco_vs_ace.md`.

---

## En cas de pepin

### Si le dispatcher crash : reprendre

Les rows `running` sont remises a `pending` au demarrage. Relance
exactement la meme commande etape 3.

### Si plein de `failed` apparaissent

Verifie le log : c'est probablement un soucis SSH ou conda. La table
`solver_bench.error_message` contient les messages. Pour repasser les
failed en pending :

```bash
sqlite3 ~/solver_bench.db "UPDATE solver_bench SET status='pending', retry_count=0 WHERE status='failed'"
```

### Si tu veux arreter proprement

Trouve le PID du dispatcher (afficher au lancement) et fais
`kill -INT <PID>`. Les workers terminent leur batch en cours puis
s'arretent. Les rows running sont laissees -- relance avec la meme
commande pour reprendre.

### Timeout solveur

Si une instance timeout des 2 solveurs (>= 300 s chacun), le row est
quand meme marque `done` avec `status_ace='timeout'` ou
`status_choco='timeout'`. C'est une info utile (instance hors-perimetre).
