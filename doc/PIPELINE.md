# Pipeline complet : de la saisie utilisateur au verdict PLAN/NON PLAN

Ce document trace **étape par étape**, sans rien sauter, le parcours d'un job
depuis le moment où l'utilisateur dessine ou importe un benzénoïde dans le
designer, jusqu'à l'affichage du verdict final (PLAN / NON PLAN / MD échec)
et à la persistance des résultats en DB.

L'objectif est d'avoir un document de référence qui explique le **rôle**,
les **entrées/sorties** et la **transformation mathématique ou algorithmique**
de chaque étape, de manière à pouvoir le réutiliser pour le mémoire de stage.

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Étape 0 — Saisie utilisateur](#étape-0--saisie-utilisateur)
3. [Étape 1 — Sérialisation en format `.graph`](#étape-1--sérialisation-en-format-graph)
4. [Étape 2 — Création du job en DB et lancement du runner](#étape-2--création-du-job-en-db-et-lancement-du-runner)
5. [Étape 3 — Parsing du `.graph` en `BenzenoidGraph`](#étape-3--parsing-du-graph-en-benzenoidgraph)
6. [Étape 4 — Prétraitement (gel, tables, symétries)](#étape-4--prétraitement-gel-tables-symétries)
7. [Étape 5 — Test xTB du benzénoïde d'entrée (bloc "original")](#étape-5--test-xtb-du-benzénoïde-dentrée-bloc-original)
8. [Étape 6 — Construction du modèle CSP](#étape-6--construction-du-modèle-csp)
9. [Étape 7 — Résolution avec ACE](#étape-7--résolution-avec-ace)
10. [Étape 8 — Post-filtre tout-hexagones](#étape-8--post-filtre-tout-hexagones)
11. [Étape 9 — Reconstruction 3D de chaque solution](#étape-9--reconstruction-3d-de-chaque-solution)
12. [Étape 10 — Validation xTB (par stratégie)](#étape-10--validation-xtb-par-stratégie)
13. [Étape 11 — Test de planarité ACP](#étape-11--test-de-planarité-acp)
14. [Étape 12 — Verdict global](#étape-12--verdict-global)
15. [Étape 13 — Ingestion DB et nettoyage du workdir](#étape-13--ingestion-db-et-nettoyage-du-workdir)
16. [Étape 14 — Affichage des résultats à l'utilisateur](#étape-14--affichage-des-résultats-à-lutilisateur)

---

## 1. Vue d'ensemble

```
[UI designer] ----> POST /api/designer/run
                            |
                            v
                   [DB] designer_jobs : state=pending
                            |
                            v
                   start_job_thread() (daemon)
                            |
                            v
                   runner.run_job(...)
                            |
        +-------------------+--------------------+
        |                                        |
    LOCAL (cluster=False)                CLUSTER (cluster=True)
        |                                        |
        v                                        v
   csp_solver.main                          cluster_runner.run_job_cluster
   (subprocess Python local)                (SSH vers 192.168.200.49)
        |                                        |
        +---- Parse .graph -> BenzenoidGraph ----+
        +---- Preprocessing (gel, tables, sym)  -+
        +---- Test xTB original (local)         -+
        +---- Construction modele CSP (PyCSP3)  -+
        +---- Resolution ACE (subprocess java)  -+
        +---- Post-filtre tout-hexagones        -+
        +---- Pour chaque solution :            -+
                Reconstruction 3D
                xTB MD + opt
                Planarite ACP
                Verdict
        |                                        |
        v                                        v
   _compute_solutions_planarity() (local)
        |
        v
   solutions_db.ingest_local_job() : xyz_files + designer_solutions
        |
        v
   shutil.rmtree(output_dir) si ingest_complete
        |
        v
   [DB] designer_jobs : state=success, summary={...}
        |
        v
   [UI] modale resultats + page /?job=<id>
```

Le pipeline est **séquentiel** par job (les étapes s'enchaînent pour
un job donné). Le mode cluster ne change pas la nature des étapes : il
les exécute juste sur une autre machine, sauf le test xTB original
et la planarité finale qui restent locaux pour homogénéiser.

---

## Étape 0 — Saisie utilisateur

L'utilisateur a deux façons d'entrer un benzénoïde dans le designer :

**(a) Dessin libre sur le canvas hexagonal** : il clique sur des cases
d'une grille de coordonnées axiales (q, r). Chaque case sélectionnée
devient un hexagone du squelette. La grille hexagonale utilise les
coordonnées axiales standard où deux hexagones sont adjacents si la
différence (Δq, Δr) ∈ {(1,0), (-1,0), (0,1), (0,-1), (1,-1), (-1,1)}.

**(b) Import d'un template `.graph`** : depuis le menu déroulant, on
charge un benzénoïde de [`csp_solver/data/`](../csp_solver/data/) (ex.
`1.graph`, `5.graph`). L'endpoint `/api/designer/templates/<name>` lit
le fichier, parse les hexagones via `graph_io.parse_graph_to_hexes()`,
et renvoie au frontend la liste des `{q, r}` qui sont alors affichés
sur le canvas (l'utilisateur peut continuer à éditer s'il veut).

Le frontend maintient un `Set<{q, r}>` représentant les hexagones
actuellement sélectionnés. L'état est aussi reconstruit en temps réel
sous forme de structure de graphe (sommets = hexagones, arêtes = paires
adjacentes) pour afficher les compteurs `n_hex`, `n_carbons`,
`n_bonds` dans le header.

### Choix du preset CSP et options

À droite du canvas, un panneau de config permet de choisir :

- **Preset CSP** : `pb1_adj57` (défaut, recommandé), `pb1`, `baseline`,
  `sym1`, etc. — cf [`csp_solver/presets.py`](../csp_solver/presets.py)
  pour la liste complète.
- **Validation xTB (MD + opt)** : activée par défaut. Sans elle, le
  solveur s'arrête après la résolution CSP et ne valide pas
  géométriquement.
- **Désactiver le gel b(v)>=2** : laisse libres les hexagones à 2 blocs
  d'arêtes libres séparés.
- **Désactiver la table de voisinage** : retire C3, ce qui multiplie le
  nombre de solutions mais beaucoup deviennent géométriquement
  infaisables.
- **Inclure le benzénoïde original** : conserve la solution
  tout-hexagones dans la liste (filtrée par défaut).
- **Nombre d'optimisations xTB** (ignoré en mode MD).
- **Stratégie de validation** : `md` (défaut), `multi-runs`, `z-perturb`.
- **Exécuter sur cluster** (visible si `DESIGNER_CLUSTER_ENABLED=1`
  côté serveur).

Quand l'utilisateur clique sur **Lancer la génération**, le frontend
construit un POST :

```json
POST /api/designer/run
{
  "hexes": [{"q": 0, "r": 0}, {"q": 1, "r": 0}, ...],
  "config": {
    "preset": "pb1_adj57",
    "validate": true,
    "method": "md",
    "cluster": false,
    "count_hexagon": false,
    ...
  }
}
```

---

## Étape 1 — Sérialisation en format `.graph`

Côté backend ([`viewer/designer/api.py:api_run`](../viewer/designer/api.py)),
on convertit la liste `[{q, r}]` en contenu **DIMACS-style** que le
parseur du solveur sait lire :

```
p DIMACS <nC> <nE> <nH>
e <q1>_<r1> <q2>_<r2>
...
h <q1>_<r1> <q2>_<r2> ... <q6>_<r6>
...
```

- `p DIMACS nC nE nH` : ligne d'en-tête, indique nC carbones, nE arêtes
  carbone-carbone, nH hexagones.
- Lignes `e a b` : arête carbone-carbone (a, b sont des coordonnées de
  sommets du **graphe dual** des arêtes carbone-carbone).
- Lignes `h c1 c2 c3 c4 c5 c6` : un hexagone listant ses 6 sommets en
  ordre cyclique.

Ce contenu est stocké tel quel dans `designer_jobs.graph_content` lors
de la création du job. Le solveur le lira plus tard. La conversion
hexagones → DIMACS est faite par
[`viewer/designer/graph_io.py:hexes_to_graph_content`](../viewer/designer/graph_io.py).

Si l'utilisateur a au lieu de cela importé un `.graph` directement
(via le bouton "Importer .graph"), `graph_content` est juste le contenu
brut du fichier.

---

## Étape 2 — Création du job en DB et lancement du runner

L'endpoint `api_run` exécute en séquence ([`viewer/designer/api.py`](../viewer/designer/api.py)) :

1. **Validation rapide** : si pas d'hexagones et pas de `graph_content`,
   400. Si le contenu .graph ne se parse pas, 400.
2. **Création de l'entrée DB** : `jobs.create_job(db_path, graph_content,
   config, output_dir)` génère un UUID court (8 hex) et INSERT une row
   dans `designer_jobs` avec `state='pending'`.
3. **Création du dossier de sortie** :
   `viewer/output/designer_jobs/<job_id>/` (vide pour l'instant).
4. **Lancement du thread daemon** :
   `runner.start_job_thread(db_path, job_id, project_root)` démarre un
   thread Python qui appelle `runner.run_job(...)` en arrière-plan.
   L'endpoint renvoie immédiatement `202 Accepted` avec le `job_id`.

Le frontend poll ensuite `/api/designer/jobs/<id>` toutes les 1-2s pour
afficher la progression.

### Aiguillage local vs cluster

Au tout début de `runner.run_job` ([`viewer/designer/runner.py`](../viewer/designer/runner.py)) :

```python
if config.get("cluster"):
    if os.getenv("DESIGNER_CLUSTER_ENABLED", "0") == "1":
        from . import cluster_runner
        return cluster_runner.run_job_cluster(db_path, job_id, project_root)
    # Mode strict : pas de fallback silencieux
    jobs.update_job(... state='failed', error='...DESIGNER_CLUSTER_ENABLED...')
    return
# Sinon : mode local (subprocess csp_solver.main sur la machine du serveur)
```

Le reste de ce document décrit ce que fait `csp_solver/main.py` (le
subprocess réel) puis le post-traitement effectué par le runner après
la fin du subprocess.

---

## Étape 3 — Parsing du `.graph` en `BenzenoidGraph`

`csp_solver/main.py` lance d'abord
[`csp_solver/utils/parser.py:parse(filepath)`](../csp_solver/utils/parser.py).
Le parser lit ligne par ligne le `.graph` et construit un objet
`BenzenoidGraph` qui contient :

- `h` : nombre d'hexagones
- `hexagons` : `list[list[node_id]]` — pour chaque hexagone, la liste
  ordonnée de ses 6 sommets carbone.
- `nodes` : `set[node_id]` — l'ensemble des sommets carbone.
- `edges` : `set[frozenset({a, b})]` — les arêtes carbone-carbone.
- `dual` : le **graphe dual hexagonal**, c'est-à-dire le graphe où
  chaque sommet est un hexagone et où deux hexagones sont reliés par
  une arête s'ils partagent une arête carbone-carbone. C'est un
  `networkx.Graph`.

Méthodes utiles ensuite :

- `graph.neighbors(v)` : voisins de l'hexagone v dans le dual.
- `graph.degree(v)` : nombre de voisins de v dans le dual.
  Un hexagone interne typique a `degree = 6` ; un hexagone de bord a
  `degree < 6`.

Le `BenzenoidGraph` est l'**unique structure** transmise à toutes les
étapes suivantes.

---

## Étape 4 — Prétraitement (gel, tables, symétries)

[`csp_solver/utils/preprocessing.py:preprocess(graph, freeze_b2=True)`](../csp_solver/utils/preprocessing.py)
calcule trois choses essentielles pour la résolution CSP.

### 4.1 Calcul des hexagones gelés

Un hexagone est **gelé** (forcé à taille 6, donc reste un hexagone)
selon deux règles cumulatives :

- **Règle deg=6** : tout hexagone de degré 6 dans le dual est gelé.
  Justification : un hexagone entouré de 6 voisins n'a aucune arête
  carbone-carbone libre, donc pas de "place" pour faire un pent ou un
  hept en redessinant. Géométriquement infaisable.
- **Règle b(v)≥2** : si on désactive avec `--no-freeze`, on désactive
  cette règle. Sinon (défaut) : tout hexagone dont les arêtes libres
  (= arêtes qui ne sont pas partagées avec un voisin) se répartissent
  en **deux blocs séparés** est gelé. La raison est topologique : pour
  redessiner un hexagone en pent/hept, il faut pouvoir contracter/dilater
  un bloc d'arêtes contiguës ; deux blocs séparés ne se transforment
  pas l'un en l'autre.

Le résultat est `frozen = sorted list of int` et `free = sorted list of
int`, complémentaires dans `[0, h-1]`.

### 4.2 Domaines des variables

```python
domains = {
    v: [6] if v in frozen else [5, 6, 7] for v in range(h)
}
```

Cela définit, pour chaque variable du CSP, l'ensemble des valeurs
possibles.

### 4.3 Génération des tables de voisinage

Pour chaque hexagone libre `v`, on calcule la **table extensionnelle**
`tables[v] = list[tuple]` qui énumère tous les tuples
`(taille_v, taille_voisin_1, ..., taille_voisin_k)` chimiquement
plausibles. La table est lue depuis
[`csp_solver/data/table_voisinage.json`](../csp_solver/data/table_voisinage.json),
qui a été construite à partir de l'observation des benzénoïdes
existants + raffinements manuels (cf [`feedback_chimiste`](../doc/doc%20from%20commit/notes_chimie_delocalisation.md)).

Chaque tuple représente "un hexagone de taille X entouré de voisins de
tailles Y1...Yk est admissible" et tient compte de la **disposition
géométrique** des voisins (l'ordre cyclique dans le dual).

### 4.4 Générateurs du groupe d'automorphismes du dual

`Aut(G_D)` est calculé via networkx
(`nx.algorithms.isomorphism.GraphMatcher`). On extrait un ensemble
**générateur** : un petit ensemble de permutations
`π : range(h) -> range(h)` tel que toutes les autres symétries de
`Aut(G_D)` sont des compositions des `π_i`. Ces générateurs serviront
à la contrainte de rupture de symétrie.

### Output

`preprocess` retourne :

```python
{
    'frozen': [...],
    'free': [...],
    'domains': {v: [...]},
    'tables': {v: [(...), ...]},
    'generators': [π_1, π_2, ...],
}
```

---

## Étape 5 — Test xTB du benzénoïde d'entrée (bloc "original")

Indépendamment du CSP, avant ou pendant le job, on calcule **la planarité
du benzénoïde d'entrée tout-hexagones** : c'est la molécule de référence
sans aucune substitution pent/hept.

[`viewer/designer/runner.py:_test_original_benzenoid`](../viewer/designer/runner.py) fait :

1. Charge `BenzenoidGraph` depuis le `.graph`.
2. Construit la "solution" `{v: 6 for v in range(h)}` (tout-hexagones).
3. Appelle `reconstruct_molecule(graph, solution_all_6)` qui produit
   une `MolecularGraph` 3D (carbones + hydrogènes, coordonnées xyz).
4. Exporte en `original/original.xyz`.
5. Lance `xtb original.xyz --opt tight` → produit `original_opt.xyz`.
6. Lit les coordonnées optimisées et calcule la planarité par ACP
   (cf étape 11).
7. Écrit `original/planarity.json` :

```json
{
  "success": true,
  "planar": true,
  "angle_deg": 0.135,
  "rmsd": 0.009,
  "height": 0.032,
  "threshold_deg": 10.0,
  "xyz_path": "viewer/output/designer_jobs/.../original/original_opt.xyz"
}
```

C'est ce bloc qui s'affiche dans la modale résultats sous "Benzenoide
d'entrée" et qui permet de **comparer** la planarité de l'original
avec celle des substitutions. En mode cluster, ce test est volontairement
fait **en local** (rapide, ~5-15s) pour homogénéiser l'expérience UI.

---

## Étape 6 — Construction du modèle CSP

[`csp_solver/utils/model.py:build_and_solve(graph, preprocessed, ...)`](../csp_solver/utils/model.py)
utilise **PyCSP3** pour construire le modèle, puis appelle **ACE** comme
solveur externe.

### 6.1 Variables

```python
x = VarArray(size=h, dom=lambda i: domains[i])
```

- `x[i]` représente la taille du cycle qui remplace l'hexagone `i`.
- Domaine : `{6}` si gelé, sinon `{5, 6, 7}`.

### 6.2 Contraintes structurelles (toujours actives)

**Contrainte C1 — Conservation du carbone**

```python
satisfy(Sum(x) == 6 * h)
```

Justification : un pent (-1 C) doit être compensé par un hept (+1 C)
pour conserver le nombre total de carbones du benzénoïde d'origine.
Algébriquement : `Σ x[v] = 6h` ⟺ `n_pent = n_hept` (donc déjà une
symétrie 5/7 forcée par le squelette).

**Contrainte C3 — Voisinage admissible (tables extensionnelles)**

```python
for v in free:
    scope = [x[v]] + [x[u] for u in graph.neighbors(v)]
    satisfy(scope in tables[v])
```

Chaque hexagone libre + ses voisins doit avoir un tuple de tailles qui
figure dans sa table pré-calculée. C'est le cœur du filtrage géométrique.

**Rupture de symétrie**

Pour chaque générateur `π` de `Aut(G_D)` :

```python
permuted = [x[π[i]] for i in range(h)]
satisfy(LexIncreasing(x, permuted))
```

Cela impose un ordre lex-leader sur les orbites du groupe, ce qui
élimine les solutions équivalentes par symétrie.

### 6.3 Contraintes additionnelles (optionnelles)

Selon le preset choisi ou les flags individuels :

- `--adj-57` (C5) : pour chaque `v`, si `x[v]=5` alors au moins un
  voisin vaut 7, et vice-versa (motif Stone-Wales).
- `--sym K` (C-SYM) : `|n_pent - n_hept| ≤ K`.
- `--pb K` (C-PB) : `nb_pent_au_bord ≤ K` (bord = degré dual < 6).
- `--hb K` (C-HB) : `nb_hept_au_bord ≤ K`.
- `--tot K` (C-TOT) : `nb_pent + nb_hept ≤ K`.
- `--tau-gb K --radius-gb r` (C-LC) : Gauss-Bonnet local. Pour chaque
  hexagone `h0`, dans le disque dual de rayon `r` autour de `h0`,
  `|#pent - #hept| ≤ K`.

Cf [`doc/doc from commit/implementation_csp/`](doc%20from%20commit/implementation_csp/)
pour les détails mathématiques de chacune.

### 6.4 Génération du XCSP3

```python
xml_path = str(Path.cwd() / "model.xml")
compile(filename=xml_path)
```

PyCSP3 sérialise le modèle au format XCSP3 (XML). Le fichier est
temporaire et supprimé à la fin.

---

## Étape 7 — Résolution avec ACE

ACE (Abscon Constraint Engine) est un solveur Java externe distribué
avec pycsp3. On l'appelle directement par subprocess (plus fiable que
le mécanisme interne de pycsp3 qui interfère avec `sys.argv`) :

```python
cmd = ["java", "-jar", ace_jar, xml_path]
if enumerate_all:
    cmd.extend(["-s=all", "-xe"])
result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
```

`-s=all` demande **toutes** les solutions ; `-xe` les format en XML
inline.

### 7.1 Parsing de la sortie d'ACE

```
<instantiation id='sol1' type='solution'> <list> x[] </list>
  <values> 5 6 7 6 6 6 </values>
</instantiation>
```

[`csp_solver/utils/model.py:_parse_ace_output`](../csp_solver/utils/model.py)
extrait toutes les balises `<values>` par regex, parse les entiers,
et reconstruit pour chaque solution un dict `{i: taille}`. Les valeurs
au-delà de l'index `h` correspondent à des variables auxiliaires
(`aux_gb`, etc.) introduites par les contraintes Gauss-Bonnet ou Reif et
sont ignorées.

Le format compact `6x4` (= "6 6 6 6") est aussi géré.

---

## Étape 8 — Post-filtre tout-hexagones

Par défaut, la solution triviale tout-hexagones (le benzénoïde
d'origine) est **exclue** de la liste — l'objectif du solveur est
d'énumérer les **substitutions non-benzénoïdes** :

```python
if not count_hexagon and solutions_list:
    solutions_list = [s for s in solutions_list
                      if not all(v == 6 for v in s.values())]
```

L'option `--count-hexagon` (case "Inclure le benzénoïde original" dans
l'UI) désactive ce filtre. Architecturalement, c'est un **post-filtre**
plutôt qu'une contrainte CSP `Sum(x[v] != 6) ≥ 1`, car celle-ci
deviendrait infaisable si tous les sommets sont gelés à `{6}`, ce qui
serait gênant à gérer.

À ce stade, on a `solutions_list = [dict[int, int], ...]`, une liste de
configurations `{hexagone: taille}` qui satisfont toutes les contraintes
CSP.

---

## Étape 9 — Reconstruction 3D de chaque solution

Pour chaque solution, on construit une **molécule réelle** en 3D
(carbones + hydrogènes, avec coordonnées xyz cohérentes) qu'on pourra
optimiser par xTB. C'est fait par
[`csp_solver/reconstruction/pipeline.py:reconstruct_molecule(graph, solution)`](../csp_solver/reconstruction/pipeline.py)
qui orchestre plusieurs sous-étapes.

### 9.1 Géométrie idéale par cycle

Pour chaque hexagone `v` du squelette, on connaît sa **taille cible**
`solution[v] ∈ {5, 6, 7}`. On construit une **géométrie idéale plane**
du cycle correspondant :

- Cycle régulier de `n` sommets dans un plan, longueur d'arête CC = 1.4 Å.
- Le centre est positionné par
  [`csp_solver/reconstruction/assembler.py`](../csp_solver/reconstruction/assembler.py),
  qui propage les positions à partir d'un cycle de référence en
  respectant les arêtes partagées entre cycles voisins.

### 9.2 Assemblage du squelette carbone

L'assembleur fait un parcours BFS du dual à partir d'un hexagone
"ancré" (généralement le 0) :

1. Place le cycle ancré en géométrie idéale dans le plan z=0.
2. Pour chaque hexagone voisin déjà non placé, calcule les positions
   des deux carbones partagés avec un cycle déjà placé (ils héritent),
   puis place les autres carbones du nouveau cycle pour qu'il soit
   plan et régulier, **du bon côté** (pour ne pas se replier).

Les contraintes topologiques garantissent qu'à la fin tous les carbones
sont placés. Les positions sont stockées dans une structure
`MolecularGraph` (atoms = list[Atom(x, y, z, sym='C')]; bonds =
list[(i, j)]).

### 9.3 Placement des hydrogènes

Pour chaque carbone qui n'a que 2 voisins carbone (donc en bord), on
calcule la position du H à attacher en utilisant
[`csp_solver/primitives/valence.py:ValenceSolver`](../csp_solver/primitives/valence.py) :

- Soit `c` le carbone de bord, avec voisins carbone `c1, c2`.
- Position du H = `c + d_CH * normalize(c - (c1+c2)/2)`
  où `d_CH = 1.088 Å` (longueur CH standard).

Le H est ajouté à la `MolecularGraph` avec sym='H'.

### 9.4 Export au format `.xyz`

[`csp_solver/reconstruction/assembler.py:export_xyz`](../csp_solver/reconstruction/assembler.py)
écrit un fichier ASCII :

```
<n_atoms>
<comment line>
<symbol>  <x>  <y>  <z>
<symbol>  <x>  <y>  <z>
...
```

Chaque solution produit `output_dir/sol_<idx>_<sizes>/source.xyz`.

Note : cette géométrie est **plane par construction** (les cycles sont
plans et l'assemblage les emboîte dans un même plan). C'est xTB qui va
révéler si la molécule est vraiment plane à l'équilibre énergétique.

---

## Étape 10 — Validation xTB (par stratégie)

L'utilisateur choisit une stratégie de validation parmi trois :

### 10.1 Stratégie `md` (défaut, recommandée)

[`csp_solver/utils/validation/md.py`](../csp_solver/utils/validation/md.py)
+ [`csp_solver/xtb/md.py`](../csp_solver/xtb/md.py).

C'est le protocole **MD + opt** validé par les chimistes :

1. **Dynamique moléculaire courte** (`xtb input.xyz --md`) :
   - Température 300 K, durée ~0.5-1 ps, niveau GFN2-xTB
   - But : **secouer** la molécule pour la sortir d'un minimum plat
     parasite si elle est dans une fausse zone d'équilibre planaire.
   - Le fichier de trajectoire `md_traj.xyz` est écrit.
2. **Filtrage anti-éjection** : si une fragmentation est détectée
   (atomes qui s'éloignent de >30 Å), la MD est rejetée et on réessaie
   (jusqu'à un certain nombre de tentatives).
3. **Optimisation à partir de la dernière frame** : `xtb md_final.xyz
   --opt tight`. Produit `md_final_opt.xyz` qui est la géométrie d'équilibre.
4. Toutes les infos (success, n_attempts, converged) sont écrites dans
   `md_validation/md_meta.json`.

Cette stratégie est **déterministe** par défaut (single-thread). On
peut autoriser le multi-thread avec `--md-no-deterministic` mais
les runs ne sont alors plus byte-reproductibles.

### 10.2 Stratégie `multi-runs`

[`csp_solver/utils/validation/multi_runs.py`](../csp_solver/utils/validation/multi_runs.py).

Plus ancienne : on lance N optimisations indépendantes
(`xtb source.xyz --opt tight`) avec une petite **perturbation aléatoire
en z** à chaque run (seed varié). On considère la sol planar si
**au moins une** des N opt converge vers une géométrie plane.

`--n-runs N` contrôle N. Moins robuste que MD car les opt restent
souvent piégées dans le minimum plat de départ.

### 10.3 Stratégie `z-perturb`

Variante déterministe de multi-runs : la perturbation est calculée
par hachage du contenu du XYZ (donc reproductible bit-à-bit).

### 10.4 Sortie commune

Quelle que soit la stratégie, la sortie est `md_final_opt.xyz` (ou
équivalent) : un XYZ optimisé que l'étape suivante va analyser pour
décider si la molécule est plane.

---

## Étape 11 — Test de planarité ACP

[`csp_solver/planarity/pca.py`](../csp_solver/planarity/pca.py).

Une fois la géométrie xTB-optimisée, on teste sa planarité par
**Analyse en Composantes Principales (ACP)** sur les coordonnées des
carbones :

### 11.1 Calcul du plan moyen

Soit `C = [c_1, ..., c_n]` les positions 3D des carbones (n = nb de C).

1. **Centrer** : `C' = C - mean(C)`.
2. **Matrice de covariance** : `M = C'^T · C' / n` (matrice 3×3).
3. **Diagonaliser** : valeurs propres `λ_1 ≥ λ_2 ≥ λ_3`, vecteurs
   propres `v_1, v_2, v_3`.
4. Le **plan moyen** est le plan engendré par `v_1, v_2` ; `v_3` est sa
   normale (axe perpendiculaire au plan).

### 11.2 Métriques calculées

- `angle_deg` : angle (en degrés) entre `v_3` et l'axe Z global. Si
  `v_3 ≈ Ẑ`, la molécule est dans le plan XY → planaire. Sinon elle
  est inclinée.
- `rmsd_plane` : root-mean-square des distances signées des carbones au
  plan moyen. Mesure à quel point la molécule "épaissit" le plan.
- `height` : amplitude (max - min) des distances signées au plan.
  Mesure l'épaisseur globale.
- `max_angle_deg` : pour chaque triangle de carbones consécutifs dans
  un cycle, angle entre la normale au triangle et `v_3`. Mesure les
  **bossages locaux** (utile pour détecter une planarité "presque"
  mais avec une déformation localisée).

### 11.3 Critère de décision

```python
def is_planar(metrics, threshold_deg=10.0):
    return metrics["max_angle_deg"] <= threshold_deg
```

Le seuil **10°** est le critère validé par le chimiste
([`reference_chimiste`](../doc/doc%20from%20commit/notes_chimie_delocalisation.md)) :
une molécule est considérée plane si tous ses cycles locaux dévient de
moins de 10° du plan moyen ACP.

Le résultat est sérialisé en `sol_dir/planarity.json` par
`_compute_solutions_planarity` :

```json
{
  "success": true,
  "planar": false,
  "angle_deg": 23.45,
  "rmsd": 0.42,
  "height": 1.18,
  "threshold_deg": 10.0
}
```

---

## Étape 12 — Verdict global

Le verdict global d'une solution est calculé côté API
([`viewer/designer/api.py:_compute_verdict`](../viewer/designer/api.py)) en
combinant le statut MD et la planarité :

```python
def _compute_verdict(md_verdict, planar):
    if md_verdict == "md_failed":
        return "md_failed"
    if planar is True:
        return "plan"
    if planar is False:
        return "non_plan"
    return "unknown"
```

- **`md_failed`** : la MD ou l'opt n'a pas convergé. La géométrie n'est
  pas exploitable, on ne peut rien dire de la planarité.
- **`plan`** : MD ok + ACP donne `max_angle_deg ≤ 10°`. La molécule
  est plane à l'équilibre.
- **`non_plan`** : MD ok + ACP donne `max_angle_deg > 10°`. La molécule
  est gondolée ou tordue.
- **`unknown`** : MD ok mais planarité non calculée (cas rare, ex.
  fichier corrompu).

Le frontend traduit ce verdict en badge coloré dans la liste des
solutions.

---

## Étape 13 — Ingestion DB et nettoyage du workdir

À la fin du subprocess `csp_solver.main` (ou du rapatriement scp pour
le mode cluster), le runner appelle
[`solutions_db.ingest_local_job(...)`](../viewer/designer/solutions_db.py) :

### 13.1 Capture des compteurs fs (avant suppression)

```python
outputs = _count_outputs(output_dir)
# {'n_sol_dirs': ..., 'n_with_xyz': ..., 'n_with_md': ...}
```

Capturé **avant** l'ingestion qui va supprimer le workdir.

### 13.2 Transaction unique

```python
with _open_conn(db_path) as conn:  # busy_timeout=5000
    for sol_dir in sorted(output_dir.glob("sol_*")):
        # Ingere source.xyz et md_final_opt.xyz en xyz_files (BLOB gzip)
        # Lit md_meta.json et planarity.json
        # INSERT dans designer_solutions
    # Ingere le bloc original (output_dir/original/) en xyz_files
    # + retourne le dict 'original' pour summary
    conn.commit()
```

Toute l'ingestion d'un job tient dans **une seule** transaction sqlite.
Atomicité garantie.

### 13.3 Suppression du workdir

```python
if n_failed == 0 and not os.getenv("DESIGNER_KEEP_WORKDIR"):
    shutil.rmtree(output_dir)
    workdir_deleted = True
```

Plus aucun fichier résiduel sur le fs. La variable d'env
`DESIGNER_KEEP_WORKDIR=1` permet de garder les fichiers (debug).

### 13.4 Mise à jour finale du job

```python
jobs.update_job(db_path, job_id, state="success",
                current_stage="done", progress=1.0,
                duration_s=duration,
                summary={
                    "n_sol_dirs": ...,
                    "n_with_xyz": ...,
                    "n_with_md": ...,
                    "n_ingested_db": ingest_stats["n_ingested"],
                    "n_failed_db": ingest_stats["n_failed"],
                    "ingest_complete": True,
                    "workdir_deleted": True,
                    "original": {...},
                    "n_planarity_computed": n_planarity,
                    "stdout_tail": stdout_lines[-50:],
                    ...
                })
```

Le job est désormais en état `success`. Le frontend qui poll
`/api/designer/jobs/<id>` voit cette transition et affiche la modale
résultats.

---

## Étape 14 — Affichage des résultats à l'utilisateur

Le frontend appelle deux endpoints :

### 14.1 `/api/designer/jobs/<id>`

Retourne la row complète de `designer_jobs`, incluant le `summary`
JSON. Le frontend lit `summary.n_sol_dirs`, `n_with_xyz`, `n_with_md`,
`job.duration_s` pour afficher les 4 compteurs en haut de la modale.

### 14.2 `/api/designer/jobs/<id>/solutions`

Décide DB-vs-FS sur `summary.ingest_complete == True` :

- Si `True` ET `designer_solutions` contient des rows pour ce job :
  branche DB. Lit toutes les rows, construit la liste de dicts via
  `_build_sol_dict_from_db`, calcule les compteurs agrégés
  (`counts.plan`, `counts.non_plan`, ...) et retourne avec le bloc
  `original` lu depuis `summary['original']`.
- Sinon : fallback fs. Parcourt `output_dir/sol_*/` et lit
  `planarity.json` + `md_meta.json` sur disque.

Pour chaque sol, le dict contient notamment :

```json
{
  "name": "sol_3_5_6_7_6_6_6",
  "sol_idx": "3",
  "sizes": "5_6_7_6_6_6",
  "has_source_xyz": true,
  "has_md_xyz": true,
  "best_xyz_path": "viewer/output/designer_jobs/.../md_final_opt.xyz",
  "md_verdict": "md_ok",
  "n_attempts": 1,
  "planar": true,
  "angle_deg": 0.135,
  "rmsd": 0.009,
  "height": 0.031,
  "verdict": "plan"
}
```

### 14.3 Affichage des badges

Chaque ligne de solution dans la modale a :

- Un **badge couleur** selon le `verdict` (vert pour plan, rouge pour
  non_plan, jaune pour md_failed, gris pour unknown).
- Un **bouton 3D** qui ouvre `MolViz.openSafe({xyz_path: best_xyz_path, ...})`.
  Le `xyz_path` est résolu par `/api/mol3d?path=...` qui fait d'abord
  un lookup fs, puis fallback DB sur `xyz_files`. Puisque le workdir a
  été supprimé, c'est la DB qui répond.

### 14.4 Bouton "Ouvrir dans le viewer principal"

Ouvre `http://.../?job=<id>` dans un nouvel onglet. Le routing du
viewer principal détecte `?job=<id>` au chargement initial et appelle
`loadJobView(jobId)` qui affiche une **page complète bookmark-able**
avec :

- Bandeau statut + compteurs détaillés
- Bloc Benzénoïde d'entrée (le bloc `original`)
- Tableau complet de toutes les solutions, avec filtres et tri

---

## Récapitulatif des fichiers principaux

| Étape | Fichier | Fonction clé |
|---|---|---|
| 1-2 | `viewer/designer/api.py` | `api_run`, `api_job_status`, `api_job_solutions` |
| 2 | `viewer/designer/jobs.py` | `create_job`, `update_job`, `get_job` |
| 2 | `viewer/designer/runner.py` | `run_job`, dispatch |
| 2 | `viewer/designer/cluster_runner.py` | `run_job_cluster` (mode SSH) |
| 3 | `csp_solver/utils/parser.py` | `parse(filepath) -> BenzenoidGraph` |
| 4 | `csp_solver/utils/preprocessing.py` | `preprocess(graph)` |
| 5 | `viewer/designer/runner.py` | `_test_original_benzenoid` |
| 6 | `csp_solver/utils/model.py` | `build_and_solve` (PyCSP3 + ACE) |
| 6 | `csp_solver/presets.py` | catalogue des presets |
| 7 | `csp_solver/utils/model.py` | `_parse_ace_output` |
| 9 | `csp_solver/reconstruction/pipeline.py` | `reconstruct_molecule` |
| 9 | `csp_solver/reconstruction/assembler.py` | placement BFS + export XYZ |
| 9 | `csp_solver/primitives/valence.py` | `ValenceSolver` (hydrogènes) |
| 10 | `csp_solver/utils/validation/md.py` | stratégie MD |
| 10 | `csp_solver/utils/validation/multi_runs.py` | stratégie multi-runs |
| 10 | `csp_solver/xtb/md.py`, `optimizer.py` | wrappers xTB |
| 11 | `csp_solver/planarity/pca.py` | `compute_planarity`, `is_planar` |
| 12 | `viewer/designer/api.py` | `_compute_verdict` |
| 13 | `viewer/designer/solutions_db.py` | `ingest_local_job`, `_open_conn` |
| 14 | `viewer/static/app.js` | `loadJobView` (page `?job=<id>`) |
| 14 | `viewer/designer/static/designer.js` | modale résultats |

---

## Résumé en une phrase

L'utilisateur dessine ou importe un benzénoïde → on le sérialise en
`.graph` → on en crée un job DB → on parse en `BenzenoidGraph` → on
prétraite (gel + tables + symétries) → on construit un modèle CSP →
on résout avec ACE → on filtre la solution triviale → pour chaque sol,
on **reconstruit en 3D** + on **valide par xTB MD + opt** + on **teste
la planarité par ACP** → on rend un verdict (PLAN, NON PLAN, MD échec)
→ on **ingère tout en DB** (xyz_files + designer_solutions) → on
**supprime le workdir local** → on affiche les résultats à
l'utilisateur via modale + page bookmark-able.
