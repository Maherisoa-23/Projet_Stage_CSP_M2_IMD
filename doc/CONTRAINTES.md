# Contraintes CSP : formalisme, implémentation, expérimentations

Ce document décrit chaque contrainte du modèle CSP du solveur de
non-benzénoïdes : son **formalisme mathématique**, son **implémentation
Python** (PyCSP3), sa **justification chimique ou topologique**, et son
**rôle dans les expérimentations** (v1, v2, v3) qui ont permis d'isoler
les combinaisons gagnantes.

L'objectif est d'avoir une référence unique pour le mémoire de stage et
pour la maintenance du code.

---

## Table des matières

1. [Cadre formel](#1-cadre-formel)
2. [Variables et domaines](#2-variables-et-domaines)
3. [Contraintes structurelles (toujours actives)](#3-contraintes-structurelles-toujours-actives)
   - 3.1 [C1 — Conservation du carbone](#31-c1--conservation-du-carbone)
   - 3.2 [C3 — Voisinage admissible (tables extensionnelles)](#32-c3--voisinage-admissible-tables-extensionnelles)
   - 3.3 [Rupture de symétrie — Lex-leader](#33-rupture-de-symétrie--lex-leader)
4. [Contraintes optionnelles](#4-contraintes-optionnelles)
   - 4.1 [C5 — Adjacence 5-7 (Stone-Wales)](#41-c5--adjacence-5-7-stone-wales)
   - 4.2 [C-SYM — Équilibre global pent/hept](#42-c-sym--équilibre-global-penthept)
   - 4.3 [C-PB — Plafonnement des pentagones au bord](#43-c-pb--plafonnement-des-pentagones-au-bord)
   - 4.4 [C-HB — Plafonnement des heptagones au bord](#44-c-hb--plafonnement-des-heptagones-au-bord)
   - 4.5 [C-TOT — Plafonnement total des défauts](#45-c-tot--plafonnement-total-des-défauts)
   - 4.6 [C-LC — Gauss-Bonnet local](#46-c-lc--gauss-bonnet-local)
5. [Post-filtre tout-hexagones](#5-post-filtre-tout-hexagones)
6. [Catalogue des presets par expérimentation](#6-catalogue-des-presets-par-expérimentation)
7. [Tableau récapitulatif](#7-tableau-récapitulatif)
8. [Notes sur l'utilisation](#8-notes-sur-lutilisation)

---

## 1. Cadre formel

Soit $G$ un benzénoïde fini composé de $h$ hexagones partageant des
arêtes carbone-carbone. Le **graphe dual hexagonal** $G_D = (V_D, E_D)$
est défini par :

- $V_D = \{0, 1, \ldots, h-1\}$ : un sommet par hexagone de $G$
- $(u, v) \in E_D$ ssi les hexagones $u$ et $v$ partagent une arête CC dans $G$

Le **bord** est défini par
$\partial G_D = \{ v \in V_D \mid \deg_{G_D}(v) < 6 \}$.
Un sommet de bord est un hexagone qui n'est pas complètement entouré par
6 voisins.

Le **groupe d'automorphismes** $\text{Aut}(G_D)$ regroupe les permutations
$\pi : V_D \to V_D$ qui préservent les arêtes. Le solveur en extrait un
ensemble générateur $\{\pi_1, \ldots, \pi_k\}$ qu'il utilise pour la
rupture de symétrie.

Le problème CSP cherche à substituer chaque hexagone par un cycle de
taille 5, 6 ou 7 (pentagone, hexagone, heptagone) en préservant la
topologie du dual et en respectant des contraintes de cohérence chimique.

---

## 2. Variables et domaines

### Variables

Pour chaque sommet $v \in V_D$, on définit une variable :

$$
x_v \in \{5, 6, 7\}
$$

$x_v = 5$ signifie "remplacer l'hexagone $v$ par un pentagone", $x_v = 6$
"garder un hexagone", $x_v = 7$ "le remplacer par un heptagone".

### Domaines

Le **prétraitement** ([`csp_solver/utils/preprocessing.py`](../csp_solver/utils/preprocessing.py))
réduit le domaine de certaines variables à $\{6\}$ — on dit que la
variable est **gelée**. Deux règles :

#### Règle deg=6 (toujours active)

$$
\deg_{G_D}(v) = 6 \;\Rightarrow\; x_v = 6
$$

Un hexagone qui est entouré par 6 voisins n'a aucune arête CC libre
pour s'étirer ou se contracter géométriquement. Le remplacer par un
pent/hept rendrait la molécule infaisable en 3D.

#### Règle $b(v) \ge 2$ (active par défaut, désactivable avec `--no-freeze`)

Soit $b(v)$ le nombre de **blocs maximaux d'arêtes libres consécutives**
de l'hexagone $v$ (en parcourant le cycle des 6 arêtes carbones de $v$).
Si :

$$
b(v) \ge 2
$$

alors $x_v$ est gelé à 6. Justification topologique : pour transformer
un hexagone en pent (resp. hept), il faut contracter (resp. dilater)
un bloc d'arêtes contiguës. Si les arêtes libres sont fragmentées en
deux blocs ou plus, la transformation n'est pas réalisable proprement.

#### Domaine final

$$
\text{dom}(x_v) =
\begin{cases}
\{6\} & \text{si } v \text{ est gelé} \\
\{5, 6, 7\} & \text{sinon}
\end{cases}
$$

```python
domains = {
    v: [6] if v in frozen else [5, 6, 7] for v in range(h)
}
x = VarArray(size=h, dom=lambda i: domains[i])
```

---

## 3. Contraintes structurelles (toujours actives)

### 3.1 C1 — Conservation du carbone

#### Formalisme

$$
\sum_{v \in V_D} x_v = 6 h
$$

#### Implémentation

```python
satisfy(Sum(x) == 6 * h)
```

#### Justification

Le nombre total de **sommets carbone** dans un benzénoïde est lié au
nombre d'hexagones par une relation topologique. Pour préserver ce
nombre lors d'une substitution, il faut compenser chaque pentagone
($-1$ carbone par rapport à un hexagone) par un heptagone ($+1$ carbone).
Algébriquement, $\sum x_v = 6h$ équivaut à
$|n_{\text{pent}} - n_{\text{hept}}| \times \pm 1 = 0$, donc
$n_{\text{pent}} = n_{\text{hept}}$.

**Conséquence immédiate** : tout benzénoïde admet la solution triviale
$x_v = 6 \;\forall v$ (le benzénoïde lui-même), qui sera filtrée
ensuite (cf [post-filtre](#5-post-filtre-tout-hexagones)).

### 3.2 C3 — Voisinage admissible (tables extensionnelles)

#### Formalisme

Pour chaque sommet libre $v \in V_D \setminus \text{Frozen}$, on
définit le tuple ordonné :

$$
\tau_v = (x_v, x_{u_1}, x_{u_2}, \ldots, x_{u_k})
$$

où $u_1, \ldots, u_k$ sont les voisins de $v$ dans $G_D$, dans un ordre
cyclique fixé. La contrainte impose :

$$
\tau_v \in T_v
$$

où $T_v \subseteq \{5, 6, 7\}^{k+1}$ est la **table de voisinage**
pré-calculée pour $v$, énumérant tous les tuples chimiquement plausibles.

#### Implémentation

```python
for v in free:
    neighbors_v = graph.neighbors(v)
    scope = [x[v]] + [x[u] for u in neighbors_v]
    satisfy(scope in tables[v])
```

#### Source de la table

La table $T_v$ est lue depuis [`csp_solver/data/table_voisinage.json`](../csp_solver/data/table_voisinage.json).
Elle a été construite à partir de l'observation des benzénoïdes
existants + raffinements manuels validés par le chimiste. Elle tient
compte de la **disposition géométrique** des voisins (l'ordre cyclique
dans le dual), pas seulement de leurs tailles.

#### Justification

C'est le **cœur du filtrage géométrique** du CSP. Sans C3, le solveur
énumérerait des milliers de configurations $(x_v, x_{u_1}, \ldots)$
incompatibles en 3D (par exemple un pentagone entouré de 6 voisins :
géométriquement impossible). C3 élimine en amont les configurations
locales qui ne sauraient se reconstruire en une molécule plane.

#### Désactivation

L'option `--no-table` désactive C3 sur toutes les variables. Utile
pour étudier l'effet du filtrage table sur le nombre de solutions
"brutes" du CSP.

### 3.3 Rupture de symétrie — Lex-leader

#### Formalisme

Pour chaque générateur $\pi$ de $\text{Aut}(G_D)$ :

$$
(x_0, x_1, \ldots, x_{h-1}) \le_\text{lex}
(x_{\pi(0)}, x_{\pi(1)}, \ldots, x_{\pi(h-1)})
$$

où $\le_\text{lex}$ est l'ordre lexicographique sur les vecteurs
d'entiers.

#### Implémentation

```python
for gen in generators:
    permuted = [x[gen[i]] for i in range(h)]
    satisfy(LexIncreasing(x, permuted))
```

#### Justification

Le groupe $\text{Aut}(G_D)$ contient des symétries triviales (rotations,
réflexions) qui transforment une solution en une solution isomorphe. La
contrainte lex-leader élimine ces doublons en imposant que la solution
choisie soit le **représentant canonique** de son orbite (celui qui est
minimal pour l'ordre lex parmi toutes ses images par les symétries).

#### Effet pratique

Sans rupture de symétrie, le solveur retournerait des solutions
équivalentes par symétrie (par exemple $x = (5, 6, 7)$ et
$x = (7, 6, 5)$ pour un benzénoïde symétrique). La contrainte élimine
ces équivalences, ce qui **réduit drastiquement** le nombre de
solutions enumérées et accélère la résolution.

---

## 4. Contraintes optionnelles

Les contraintes ci-dessous sont **désactivées par défaut** et activées
via flags CLI ou via un preset (cf section 6).

### 4.1 C5 — Adjacence 5-7 (Stone-Wales)

#### Flag

`--adj-57`

#### Formalisme

$$
\forall v \in V_D \;:\;
\begin{cases}
x_v = 5 & \Rightarrow & \sum_{u \in N(v)} [x_u = 7] \ge 1 \\
x_v = 7 & \Rightarrow & \sum_{u \in N(v)} [x_u = 5] \ge 1
\end{cases}
$$

où $[P]$ vaut 1 si $P$ est vrai, 0 sinon, et $N(v)$ est l'ensemble des
voisins de $v$ dans $G_D$.

Cela impose que **tout pentagone a au moins un voisin heptagone**, et
réciproquement.

#### Implémentation

```python
if adj_57:
    for v in range(h):
        neighbors_v = graph.neighbors(v)
        if neighbors_v:
            satisfy(If(x[v] == 5,
                       Then=Sum(x[u] == 7 for u in neighbors_v) >= 1))
            satisfy(If(x[v] == 7,
                       Then=Sum(x[u] == 5 for u in neighbors_v) >= 1))
```

#### Justification chimique

Motif **Stone-Wales** : dans la littérature des défauts de nanotubes
et fullerènes, le défaut 5-7-7-5 (un pentagone collé à un heptagone)
est la transformation topologique élémentaire. Localement, le pent
introduit une **courbure positive** ($+\pi/3$) et l'hept une **courbure
négative** ($-\pi/3$), qui s'annulent quand ils sont adjacents. Une
paire 5-7 maintient donc le voisinage globalement plat.

À l'inverse, un pentagone solitaire (sans hept voisin) crée une
courbure non compensée localement, ce qui tend à produire des
géométries non-planes (forme conique ou en cuvette).

C5 est la contrainte clé du preset gagnant `pb1_adj57`.

### 4.2 C-SYM — Équilibre global pent/hept

#### Flag

`--sym K`

#### Formalisme

$$
\left| n_{\text{pent}} - n_{\text{hept}} \right| \le K_{\text{sym}}
$$

où $n_{\text{pent}} = \sum_v [x_v = 5]$ et $n_{\text{hept}} = \sum_v [x_v = 7]$.

#### Implémentation

```python
if K_sym is not None and K_sym >= 0:
    n_pent_global = Sum(x[v] == 5 for v in range(h))
    n_hept_global = Sum(x[v] == 7 for v in range(h))
    satisfy(n_pent_global - n_hept_global <= K_sym)
    satisfy(n_hept_global - n_pent_global <= K_sym)
```

#### Justification

C1 ($\sum x_v = 6h$) impose **déjà** $n_{\text{pent}} = n_{\text{hept}}$,
donc $K_{\text{sym}} = 0$ serait redondant. Mais sur des configurations
géométriques où certaines variables sont gelées à 6, la valeur effective
peut s'écarter localement de l'égalité globale, et C-SYM permet
d'imposer une **borne supérieure** sur cet écart.

En pratique : effet marginal mesuré sur l'expérimentation v2. Conservé
pour étude des combinaisons.

### 4.3 C-PB — Plafonnement des pentagones au bord

#### Flag

`--pb K`

#### Formalisme

$$
\sum_{v \in \partial G_D} [x_v = 5] \le K_{\text{pb}}
$$

où $\partial G_D = \{ v \mid \deg_{G_D}(v) < 6 \}$ est l'ensemble des
hexagones de bord.

#### Implémentation

```python
boundary = sorted(v for v in range(h) if graph.degree(v) < 6)
if K_pb is not None and boundary:
    satisfy(Sum(x[v] == 5 for v in boundary) <= K_pb)
```

#### Justification

Un pentagone au bord du squelette a moins de voisins pour "absorber" sa
courbure positive ($+\pi/3$) : il y a structurellement moins
d'heptagones potentiels à proximité immédiate, et la courbure quasi-libre
qu'il introduit se traduit souvent par une **torsion globale** de la
molécule à l'optimisation xTB.

La contrainte $K_{\text{pb}} \le 1$ est l'**heuristique gagnante** de
l'expérimentation v2 : on garde au plus 1 pent au bord. Effet
expérimentalement mesuré : **+9 à +19 points** de taux de planarité vs
baseline.

### 4.4 C-HB — Plafonnement des heptagones au bord

#### Flag

`--hb K`

#### Formalisme

$$
\sum_{v \in \partial G_D} [x_v = 7] \le K_{\text{hb}}
$$

#### Implémentation

```python
if K_hb is not None and boundary:
    satisfy(Sum(x[v] == 7 for v in boundary) <= K_hb)
```

#### Justification

Symétrique de C-PB pour les heptagones. Moins critique en pratique car
un hept au bord a tendance à s'aplatir vers l'intérieur sans casser la
planarité globale. Utilisé dans le preset `all_strict` (combiné à
C-PB).

### 4.5 C-TOT — Plafonnement total des défauts

#### Flag

`--tot K`

#### Formalisme

$$
\sum_{v \in V_D} [x_v \ne 6] \le K_{\text{tot}}
$$

#### Implémentation

```python
if K_tot is not None:
    satisfy(Sum(x[v] != 6 for v in range(h)) <= K_tot)
```

#### Justification

Limite le **nombre total** de pent + hept dans la molécule. Équivalent
à imposer "au moins $h - K_{\text{tot}}$ hexagones doivent être
préservés". Utile pour générer des molécules avec peu de défauts (pour
étudier l'effet d'une seule paire 5-7 par exemple).

### 4.6 C-LC — Gauss-Bonnet local

#### Flags

`--tau-gb K` et `--radius-gb R` (défaut $R = 2$)

#### Formalisme

Soit $B_R(v) = \{ u \in V_D \mid d_{G_D}(u, v) \le R \}$ la **boule de
rayon $R$** autour de $v$ dans le dual ($d_{G_D}$ = distance de graphe).
Pour chaque $v \in V_D$ :

$$
\left|
\sum_{u \in B_R(v)} [x_u = 5] - \sum_{u \in B_R(v)} [x_u = 7]
\right| \le \tau_{\text{gb}}
$$

#### Implémentation

```python
if tau_gb is not None and tau_gb >= 0:
    import networkx as nx
    for h0 in range(h):
        nbrs = sorted(nx.single_source_shortest_path_length(
            graph.dual, h0, cutoff=radius_gb).keys())
        if not nbrs:
            continue
        pents = Sum(x[v] == 5 for v in nbrs)
        hepts = Sum(x[v] == 7 for v in nbrs)
        satisfy(pents - hepts <= tau_gb)
        satisfy(hepts - pents <= tau_gb)
```

#### Justification (théorème de Gauss-Bonnet local)

Le théorème de Gauss-Bonnet, appliqué à une surface fermée triangulée,
relie la **courbure intégrée** à la caractéristique d'Euler. Pour un
benzénoïde plan, la courbure totale doit être nulle. Localement, dans
un disque de rayon $R$, la **courbure cumulée** est essentiellement
$\frac{\pi}{3}(n_{\text{pent}} - n_{\text{hept}})$ : chaque pent contribue
$+\pi/3$, chaque hept $-\pi/3$.

La contrainte C-LC impose que cette courbure intégrée locale soit
**bornée** : on n'autorise pas l'accumulation de défauts du même signe
dans un voisinage rapproché. C'est une borne **stricte** d'une forme de
"planarité topologique locale".

#### Cas particuliers

- $\tau_{\text{gb}} = 0$ : courbure locale nulle exigée → typiquement très
  contraignant (preset `curv0`).
- $\tau_{\text{gb}} = 1$ : permet 1 défaut net dans le rayon $R$ (preset
  `curv1`). Comparable à C-PB=1 en effet pratique (redondant dans nos
  tests).

---

## 5. Post-filtre tout-hexagones

#### Flag

`--count-hexagon` (par défaut : la solution tout-hexagones est exclue)

#### Justification

C1 ($\sum x_v = 6h$) autorise toujours la solution triviale
$x_v = 6 \;\forall v$, qui correspond au benzénoïde d'origine sans
substitution. Comme l'objectif du solveur est d'**énumérer les
substitutions non-benzénoïdes**, cette solution est filtrée par défaut.

#### Implémentation

```python
if not count_hexagon and solutions_list:
    solutions_list = [s for s in solutions_list
                      if not all(v == 6 for v in s.values())]
```

#### Pourquoi un post-filtre et pas une contrainte ?

Une contrainte CSP "$\sum_v [x_v \ne 6] \ge 1$" deviendrait **infaisable**
si tous les sommets sont gelés à $\{6\}$ (cas d'un benzénoïde fermé où
toutes les variables sont gelées par la règle deg=6). Le post-filtre
post-résolution n'a pas ce problème : il agit après ACE et filtre la
solution triviale uniquement si elle apparaît. Surcoût négligeable
(1 solution à filtrer dans le pire cas).

L'utilisateur peut conserver la solution tout-hexagones (utile pour
forcer la validation xTB du benzénoïde original via le pipeline complet,
plutôt que via le test pré-CSP `_test_original_benzenoid`).

---

## 6. Catalogue des presets par expérimentation

Les presets sont définis dans [`csp_solver/presets.py`](../csp_solver/presets.py)
et sélectionnables via `--preset NAME` ou la liste déroulante de l'UI
designer.

### 6.1 v1 — Baseline

| Preset | Contraintes additionnelles | Rôle |
|---|---|---|
| `baseline` | (aucune) | Référence pour comparaison |

L'expérimentation v1 a posé la question : **quelle proportion de
solutions CSP est réellement plane après optimisation xTB ?** Avec
uniquement les contraintes structurelles (C1 + C3 + sym), le taux est
mediocre. Le pipeline complet (CSP → reconstruction → MD → opt → ACP)
a été mis au point ici.

### 6.2 v2 — Contraintes globales pent/hept

Question : **peut-on filtrer en amont les solutions géométriquement
non-planes en plafonnant globalement les pent/hept et leur position au
bord ?**

| Preset | Contraintes | Effet observé |
|---|---|---|
| `sym1` | $K_{\text{sym}} = 1$ | Marginal |
| `pb2` | $K_{\text{pb}} = 2$ | Léger gain |
| **`pb1`** | $K_{\text{pb}} = 1$ | **Winner v2 : +9 à +19 pts vs baseline** |
| `pb0` | $K_{\text{pb}} = 0$ | UNSAT sur h6-h9 (trop strict) |
| `sym1_pb2` | $K_{\text{sym}} = 1, K_{\text{pb}} = 2$ | Comparable à `pb2` |
| `all_strict` | $K_{\text{sym}} = 0, K_{\text{pb}} = 2, K_{\text{hb}} = 3$ | Très restrictif, peu utile |

**Conclusion v2** : `pb1` est l'heuristique la plus rentable.
L'intuition : un pentagone seul au bord crée une courbure positive
quasi-libre qui se "tord" facilement à l'optimisation.

### 6.3 v3 — Curvature locale + Stone-Wales

Question : **peut-on raffiner v2 avec une borne locale de courbure
(Gauss-Bonnet) ou avec l'adjacence 5-7 imposée ?**

| Preset | Contraintes | Effet observé |
|---|---|---|
| `curv1` | $\tau_{\text{gb}} = 1, R = 2$ | Redondant avec `pb1` |
| `curv0` | $\tau_{\text{gb}} = 0, R = 2$ | Très restrictif |
| `pb1_curv1` | $K_{\text{pb}} = 1, \tau_{\text{gb}} = 1$ | $\approx$ `pb1` |
| `sym1_pb2_curv1` | combinaison | Test exploratoire |
| **`pb1_adj57`** | $K_{\text{pb}} = 1$, C5 actif | **Winner global : +17 à +32 pts vs baseline** |
| `sym1_pb1_adj57` | + $K_{\text{sym}} = 1$ | Variante plus stricte |

**Conclusion v3** : la combinaison **`pb1_adj57`** est gagnante. Le
plafonnement C-PB=1 élimine les pent solitaires de bord
problématiques ; la contrainte d'adjacence C5 force les pent et hept
restants à être appariés localement (motif Stone-Wales), ce qui annule
leur courbure et favorise la planarité finale.

C'est le preset **recommandé par défaut** dans l'interface designer.

### 6.4 Vue d'ensemble : 13 presets

```python
PRESETS = {
    "baseline":         {},
    "sym1":             {"K_sym": 1},
    "pb2":              {"K_pb": 2},
    "pb1":              {"K_pb": 1},                   # winner v2
    "pb0":              {"K_pb": 0},                   # UNSAT
    "sym1_pb2":         {"K_sym": 1, "K_pb": 2},
    "all_strict":       {"K_sym": 0, "K_pb": 2, "K_hb": 3},
    "curv1":            {"tau_gb": 1, "radius_gb": 2},
    "curv0":            {"tau_gb": 0, "radius_gb": 2},
    "sym1_pb2_curv1":   {"K_sym": 1, "K_pb": 2, "tau_gb": 1, "radius_gb": 2},
    "pb1_curv1":        {"K_pb": 1, "tau_gb": 1, "radius_gb": 2},
    "pb1_adj57":        {"K_pb": 1, "adj_57": True},   # winner global
    "sym1_pb1_adj57":   {"K_sym": 1, "K_pb": 1, "adj_57": True},
}
```

---

## 7. Tableau récapitulatif

| Code | Nom | Formule | Type | Flag CLI | Origine |
|---|---|---|---|---|---|
| **deg=6** | Gel des hexagones internes | $\deg(v) = 6 \Rightarrow x_v = 6$ | Domaine (structurel) | toujours actif | v1 |
| **b(v)≥2** | Gel des arêtes fragmentées | $b(v) \ge 2 \Rightarrow x_v = 6$ | Domaine (structurel) | `--no-freeze` désactive | v1 |
| **C1** | Conservation du carbone | $\sum_v x_v = 6h$ | Structurelle | toujours actif | v1 |
| **C3** | Voisinage admissible | $(x_v, x_{u_1}, \ldots) \in T_v$ | Structurelle (table) | `--no-table` désactive | v1 |
| **sym** | Rupture de symétrie | $x \le_\text{lex} \pi(x)$ pour $\pi \in \text{Gen}(\text{Aut}(G_D))$ | Structurelle | toujours actif | v1 |
| **C5** | Adjacence 5-7 | $x_v = 5 \Rightarrow \exists u \in N(v) : x_u = 7$ (et sym) | Optionnelle | `--adj-57` | v3 |
| **C-SYM** | Équilibre pent/hept | $\|n_5 - n_7\| \le K$ | Optionnelle | `--sym K` | v2 |
| **C-PB** | Pentagones au bord | $\sum_{v \in \partial} [x_v = 5] \le K$ | Optionnelle | `--pb K` | v2 |
| **C-HB** | Heptagones au bord | $\sum_{v \in \partial} [x_v = 7] \le K$ | Optionnelle | `--hb K` | v2 |
| **C-TOT** | Total des défauts | $\sum_v [x_v \ne 6] \le K$ | Optionnelle | `--tot K` | v2 |
| **C-LC** | Gauss-Bonnet local | $\|n_5(B_R(v)) - n_7(B_R(v))\| \le \tau$ | Optionnelle | `--tau-gb K --radius-gb R` | v3 |
| **C0** | Filtre tout-hexagones | $\exists v : x_v \ne 6$ | Post-filtre | `--count-hexagon` désactive | v1 |

### Légende

- $h$ : nombre d'hexagones du benzénoïde
- $V_D$ : sommets du graphe dual hexagonal (taille $h$)
- $\partial G_D$ : sommets de bord ($\deg < 6$)
- $N(v)$ : voisins de $v$ dans $G_D$
- $B_R(v)$ : boule de rayon $R$ autour de $v$
- $n_5, n_7$ : nombres globaux (ou locaux) de pent et hept
- $\text{Gen}(\text{Aut}(G_D))$ : ensemble générateur du groupe d'automorphismes du dual

---

## 8. Notes sur l'utilisation

### Combinaisons recommandées

- **Démarrer simple** : `--preset baseline` pour voir le nombre de
  solutions brutes du CSP.
- **Préset chiral** : `--preset pb1_adj57` (winner global, recommandé
  par défaut dans l'UI).
- **Étude d'un effet isolé** : combiner les flags individuels (par
  exemple `--pb 1 --adj-57` est équivalent à `--preset pb1_adj57`).

### Override des presets

Quand on passe à la fois un preset et des flags individuels :

```
python -m csp_solver.main file.graph --preset pb1_adj57 --pb 2
```

Le flag individuel **prime** sur la valeur du preset (cf
[`csp_solver/main.py`](../csp_solver/main.py), section "Preset"). Cela
permet de surcharger un seul paramètre tout en gardant les autres du
preset.

### Coût de résolution

- Les contraintes optionnelles **réduisent** l'espace de recherche →
  résolution **plus rapide** dans tous les cas observés (preset gagnant
  `pb1_adj57` est typiquement 2-5× plus rapide que baseline).
- C-LC (Gauss-Bonnet) introduit des variables auxiliaires
  (`aux_gb` dans le XML XCSP3) qui apparaissent dans le parseur de
  sortie d'ACE — ces variables sont ignorées (cf
  [`_parse_ace_output`](../csp_solver/utils/model.py)).

### Cas UNSAT

Si la combinaison de contraintes est trop stricte, ACE retourne UNSAT
et le solveur affiche "Aucune solution trouvée". Cas connus :

- `pb0` ($K_{\text{pb}} = 0$) : UNSAT systématique sur h6-h9.
- `curv0` ($\tau_{\text{gb}} = 0$) : souvent UNSAT pour les benzénoïdes
  asymétriques.
- `all_strict` ($K_{\text{sym}} = 0, K_{\text{pb}} = 2, K_{\text{hb}} = 3$) :
  UNSAT pour les petits squelettes.

### Diagnostic

`csp_solver.main` affiche en début de résolution les contraintes
actives :

```
=== Resolution CSP ===
  Contrainte C5 (adjacence 5-7) : ACTIVEE
  Solution tout-hexagones : EXCLUE (defaut)
  Contraintes additionnelles : preset=pb1_adj57 pb=1
```

Cela permet de vérifier rapidement quelle configuration tourne.

---

## Références

- Formalisme général du CSP : voir [`csp_solver/utils/model.py`](../csp_solver/utils/model.py)
- Construction des tables de voisinage : [`csp_solver/data/table_voisinage.json`](../csp_solver/data/table_voisinage.json)
- Détails des expérimentations v1/v2/v3 : [`experiments/v1/`](../experiments/v1/),
  [`experiments/v2/`](../experiments/v2/), [`experiments/v3/`](../experiments/v3/)
  (rapports `.tex` dans chaque dossier)
- Pipeline complet d'un job : [`doc/PIPELINE.md`](PIPELINE.md)
- Procédure du chimiste (validation) : [`doc/doc from commit/notes_chimie_delocalisation.md`](doc%20from%20commit/notes_chimie_delocalisation.md)
