# Analyse électronique : Kekulé, Clar, RBO, radicaux

Ce document décrit le module **`viewer/molviz/`**, qui calcule et
affiche les propriétés électroniques d'une molécule polycyclique
plane (PAH ou non-benzénoïde) : structures de Kekulé, couvertures de
Clar (sextets aromatiques), Ring Bond Orders, et identification des
sites radicalaires.

Ces analyses sont **statiques** : elles ne lancent aucun calcul
quantique. Elles se font directement sur le **graphe** de la molécule
(carbones + liaisons) à partir d'un fichier XYZ optimisé. Le viewer
3D s'appuie sur ces calculs pour proposer plusieurs **modes
d'affichage** complémentaires.

---

## Table des matières

1. [Cadre général](#1-cadre-général)
2. [Construction du graphe (`bonds.py`)](#2-construction-du-graphe-bondspy)
3. [Kekulé : matching et radicaux (`kekule.py`)](#3-kekulé--matching-et-radicaux-kekulepy)
4. [Clar : sextets aromatiques (`clar.py`)](#4-clar--sextets-aromatiques-clarpy)
5. [Ring Bond Orders (`rbo.py`)](#5-ring-bond-orders-rbopy)
6. [API Flask et frontend (`api.py`, `molviz.js`)](#6-api-flask-et-frontend-apipy-molvizjs)
7. [Cas particuliers et limites](#7-cas-particuliers-et-limites)
8. [Références bibliographiques](#8-références-bibliographiques)

---

## 1. Cadre général

Une molécule polycyclique aromatique est modélisée comme un **graphe
simple** $\mathcal{M} = (A, E)$ où :

- $A$ = atomes de carbone (les hydrogènes sont ignorés pour l'analyse
  électronique)
- $E$ = liaisons carbone-carbone

Sur ce graphe on calcule :

| Analyse | Objet mathématique | Significat chimique |
|---|---|---|
| Kekulé | Matching de cardinalité maximale | Double liaisons localisées + radicaux |
| Clar | Sous-ensemble vertex-disjoint de cycles à 6 + matching du résidu | Sextets aromatiques |
| RBO | Moyenne sur l'ensemble des Kekulé | Délocalisation des liaisons π |
| Radicaux | Atomes non couverts par le matching max | Sites de réactivité |

Le pipeline d'appel typique côté frontend est :

```
Click sur "3D" pour une solution
       |
       v
fetch /api/mol3d?path=...  (mode défaut : 1 Kekulé arbitraire)
       |
       v
Affichage 3Dmol.js
       |
       +- Switch "Mode Kekulé"  -> fetch /api/kekule_list
       +- Switch "Mode RBO"     -> fetch /api/rbo
       +- Switch "Mode Clar"    -> fetch /api/clar_list
```

Chaque endpoint utilise un **cache LRU** côté serveur (256 entrées) pour
éviter de recalculer les structures coûteuses (matchings, énumérations)
à chaque clic.

---

## 2. Construction du graphe ([`bonds.py`](../viewer/molviz/bonds.py))

### 2.1 Détection des liaisons C-C

À partir d'un fichier XYZ optimisé :

1. Lecture des coordonnées 3D des atomes carbone (les H sont droppés
   à ce stade ; ils servent uniquement à la validation xTB).
2. Pour chaque paire $(c_i, c_j)$ de carbones, on calcule la distance
   euclidienne $d(c_i, c_j)$.
3. La liaison est conservée si $d(c_i, c_j) \le d_{\max}^{\text{CC}}$
   (typiquement $1.65 \text{ Å}$, soit légèrement plus que la longueur
   d'une liaison simple C-C de $1.54 \text{ Å}$ pour tolérer les
   distortions post-optimisation).

Le seuil est ajustable. Une liaison C-C "longue" (au-delà du seuil)
est interprétée comme une **rupture** : le graphe peut se fragmenter
si la molécule s'est ouverte au cours de l'optimisation.

### 2.2 Identification des cycles

Le module détecte les cycles du graphe par BFS spécialisé. Chaque cycle
est caractérisé par :

- `size` : nombre de carbones (5, 6 ou 7 pour un non-benzénoïde)
- `atoms` : liste ordonnée des indices des atomes du cycle
- `anomaly` : flag mis à `True` si la taille n'est pas dans `{5, 6, 7}`
  (cas pathologique post-optimisation)

Le résultat est une structure `MolGraph` contenant `atoms`, `bonds`,
`cycles` qui alimente toutes les analyses suivantes.

---

## 3. Kekulé : matching et radicaux ([`kekule.py`](../viewer/molviz/kekule.py))

### 3.1 Définition

Une **structure de Kekulé** assigne à chaque liaison C-C un ordre
$\in \{1, 2\}$ (simple ou double) tel que chaque atome de carbone soit
incident à **exactement une double liaison**. Algébriquement, c'est un
**matching parfait** du graphe $\mathcal{M}$.

$$
M \subseteq E \;:\; \forall a \in A,\; \left| \{e \in M : a \in e\} \right| = 1
$$

Chaque atome a alors 3 liaisons simples (sigma) + 1 double (sigma + pi),
ce qui correspond à la valence sp² typique d'un carbone aromatique.

### 3.2 Cas non parfait : radicaux

Si $\mathcal{M}$ n'admet pas de matching parfait (nombre impair
d'atomes, ou topologie spécifique), on prend un **matching de
cardinalité maximale**. Les atomes **non couverts** par ce matching
sont les **sites radicalaires** : ils portent un électron π non
apparié et sont chimiquement réactifs.

$$
R(M) = A \setminus V(M) \quad \text{(atomes non couverts par } M\text{)}
$$

### 3.3 Implémentation

**Mode "un seul Kekulé"** ([`assign_kekule`](../viewer/molviz/kekule.py)) :

```python
import networkx as nx
g = build_nx_graph(mol)
matching = nx.max_weight_matching(g, maxcardinality=True, weight=None)
```

Utilise l'algorithme **Edmonds Blossom** (via networkx) qui calcule un
matching maximum en temps polynomial $\mathcal{O}(|V|^3)$. Suffit pour le
mode "défaut" du viewer.

**Mode "énumération de tous les Kekulé"** (`enumerate_kekule`) :

Algorithme de backtracking qui énumère tous les matchings maximums
distincts du graphe, avec :

- **Canonicalisation** pour éliminer les doublons (deux matchings sont
  équivalents si l'ensemble de leurs arêtes coïncide).
- **Plafond** `max_count` (défaut 200 pour le viewer, 10000 pour RBO)
  pour éviter l'explosion combinatoire sur les molécules avec
  beaucoup de symétries.
- Drapeau `is_exact` = `True` si l'énumération a été exhaustive,
  `False` si on a plafonné.

### 3.4 Sortie

```python
@dataclass
class KekuleAssignment:
    bond_orders: List[int]   # 1 ou 2 par liaison
    radicals: Set[int]       # indices des atomes non couverts
    n_doubles: int           # nombre de doubles
    is_perfect: bool         # True si pas de radicaux
```

Pour une molécule benzénique typique (nombre pair d'atomes, topologie
"propre"), `is_perfect = True` et `radicals = ∅`. Pour des
non-benzénoïdes avec une parité ou une topologie particulière, on peut
avoir 1 ou 2 radicaux qui sont identifiés et affichés dans le viewer
comme des **sphères colorées**.

---

## 4. Clar : sextets aromatiques ([`clar.py`](../viewer/molviz/clar.py))

### 4.1 Définition (Clar 1972)

Une **couverture de Clar** est définie par deux objets :

1. Un sous-ensemble $S \subseteq \text{Cycles}_6(\mathcal{M})$
   d'**hexagones**, deux à deux **vertex-disjoints** (aucun atome n'est
   partagé entre deux hexagones de $S$). Chaque hexagone de $S$ porte
   un **rond de Clar** : un sextet de 6 électrons $\pi$ délocalisés
   dans l'hexagone.
2. Un **matching parfait** $M$ du sous-graphe $\mathcal{M} \setminus V(S)$
   (le **résidu** : la molécule moins les atomes consommés par les
   sextets). Si la molécule est radicalaire, on tolère que ce matching
   laisse des atomes non couverts (mêmes que ceux du matching max
   global).

Le **score de Clar** d'une couverture est $|S|$. Le **nombre de Clar**
de la molécule est :

$$
\text{Cl}(\mathcal{M}) = \max_{S \text{ vertex-disjoint}} |S|
$$

en exigeant qu'il existe un matching parfait du résidu.

### 4.2 Pourquoi seuls les hexagones ?

La règle de **Hückel** dit qu'un cycle aromatique stable a $4n + 2$
électrons $\pi$. Pour un sextet (6 électrons délocalisés), $n = 1$.
Cela impose **exactement 6 atomes** dans le cycle aromatique :

- Un **pentagone** a 5 atomes $\Rightarrow$ ne peut pas porter de
  sextet.
- Un **heptagone** a 7 atomes $\Rightarrow$ ne peut pas non plus.

Seuls les **hexagones** peuvent porter un rond de Clar. Pentagones et
heptagones du squelette appartiennent obligatoirement au résidu et
voient leurs liaisons assignées par le matching standard.

### 4.3 Pourquoi vertex-disjoints stricts ?

C'est la **définition stricte** de Clar, validée avec les chimistes
(Hagebaum-Reignier, Carissan). Un rond de Clar représente un sextet
aromatique **autonome** : ses 6 électrons $\pi$ circulent dans
l'hexagone seul, donc deux ronds ne peuvent pas se partager d'atome
(ce qui briserait la circulation indépendante des deux courants).

Pour les PAH condensés (où des hexagones partagent des arêtes), cette
contrainte est **forte** : on ne peut pas mettre de ronds sur deux
hexagones fusionnés.

### 4.4 Algorithme

Pour une molécule à $n_{\text{hex}}$ hexagones :

```
Pour chaque sous-ensemble S ⊆ Hex(M) (2^n_hex iterations) :
    Si S vertex-disjoint :
        Calculer max matching du résidu G \ V(S)
        Si nb_radicaux_resultant <= min global :
            Couverture valide de score |S|
Conserver celles avec |S| max
```

Pour $n_{\text{hex}} \le 9$ (notre cas), $2^9 = 512$ sous-ensembles à
tester — trivial. Pour des molécules plus grosses, une approche par
**backtracking avec pruning** serait nécessaire.

### 4.5 Sortie

```python
@dataclass
class ClarCover:
    sextets: List[int]        # indices des cycles porteurs d'un rond
    bond_orders: List[int]    # 1 ou 2, par liaison
    radicals: Set[int]        # indices des atomes non couverts
    n_sextets: int            # |sextets|
```

Les `bond_orders` sont construits **canoniquement** :

- Sur les arêtes d'un sextet : **alternance** double-simple-double-...
  (les liaisons "doubles" du sextet par convention).
- Sur les arêtes du résidu : matching max calculé.
- Sur les arêtes connectant sextet et résidu : simple.

Plusieurs couvertures peuvent atteindre le même `n_sextets` maximum,
choisies sur des hexagones différents. Le viewer permet de naviguer
entre elles.

---

## 5. Ring Bond Orders ([`rbo.py`](../viewer/molviz/rbo.py))

### 5.1 Définition (Pauling-Randić)

Le **bond order** (ordre de liaison) d'une arête $e$ est défini comme la
fraction des structures de Kekulé dans lesquelles cette arête est une
double liaison :

$$
\text{bo}(e) = \frac{\#\{K \in \mathcal{K}(\mathcal{M}) : e \in K\}}{|\mathcal{K}(\mathcal{M})|}
$$

où $\mathcal{K}(\mathcal{M})$ est l'ensemble de tous les Kekulé
(matchings parfaits) de $\mathcal{M}$. C'est une valeur dans $[0, 1]$ qui
mesure la **propension à être double** d'une arête dans le
"superpositionnement" de toutes les Kekulé — c'est-à-dire la
**délocalisation locale** de la liaison $\pi$.

Le **Ring Bond Order** (RBO, ou CBO pour Cycle Bond Order) d'un cycle
$C \subseteq E$ est :

$$
\text{CBO}(C) = \sum_{e \in C} \text{bo}(e)
$$

C'est la "somme des doubles" du cycle moyennée sur les Kekulé.

### 5.2 Bornes par taille de cycle

Pour un PAH purement benzénique :

- Hexagone : $\text{CBO} \in [0, 3]$ (au plus 3 doubles dans un hex).
- Pentagone : $\text{CBO} \in [0, 2]$ (au plus 2 doubles dans un pent
  d'un PAH).
- Heptagone : $\text{CBO} \in [0, 3]$.

Mais ces bornes dépendent du contexte (l'environnement du cycle limite
ce qui est atteignable). Le code calcule donc **`cbo_max`** a
posteriori comme :

$$
\text{cbo\_max}(C) = \max_{K \in \mathcal{K}(\mathcal{M})} |C \cap K|
$$

Le ratio $\text{CBO}(C) / \text{cbo\_max}(C)$ est plus honnête à
afficher que le ratio par rapport à une borne théorique fixe — il
reflète à quel point le cycle est "saturé en doubles" dans son
contexte propre.

### 5.3 Algorithme

```python
kekule_list, is_exact = enumerate_kekule(mol, max_count=DEFAULT_MAX_KEKULE)
n = len(kekule_list)
for each bond e :
    bond_orders[e] = (#K in kekule_list with e double) / n
for each cycle C :
    cbo[C]     = sum(bond_orders[e] for e in C)
    cbo_max[C] = max over K of (#doubles of K in C)
```

Plafond `DEFAULT_MAX_KEKULE = 10000`. Au-delà, l'énumération est
plafonnée et `is_exact = False`. Le RBO est alors approximé sur les
10000 premières Kekulé (ordre canonique).

### 5.4 Cas radicalaire

Si la molécule n'admet **aucun** matching parfait (donc aucune Kekulé
"stricte"), le RBO **n'est pas défini** au sens de Pauling-Randić
(qui ne traite que les Kekulé strictes). Le code retourne :

```python
RboResult(available=False, reason="aucune Kekule stricte (molecule radicalaire)")
```

Le frontend affiche alors un message clair au lieu des valeurs RBO.

### 5.5 Sortie

```python
@dataclass
class RboResult:
    available: bool            # False si radicalaire ou pathologique
    bond_orders: List[float]   # valeur in [0, 1] par liaison
    cbo: List[float]           # par cycle
    cbo_max: List[int]         # max observé par cycle
    n_kekule: int              # # Kekulé énumérées
    is_exact: bool             # False si plafonné à DEFAULT_MAX_KEKULE
    n_radicals: int
    reason: Optional[str]
```

---

## 6. API Flask et frontend (`api.py`, `molviz.js`)

### 6.1 Endpoints

Tous prefixés par `/api/`. Chaque endpoint accepte `?path=<rel_path>`
qui pointe vers un fichier `.xyz`. Le path est résolu côté serveur via
`_load_xyz_text` qui fait **fs first, DB fallback** (cf doc
[`DESIGNER_CLUSTER_DB.md`](DESIGNER_CLUSTER_DB.md)) — donc transparent
qu'on serve un XYZ depuis le disque ou depuis le BLOB `xyz_files` de
sqlite.

| Endpoint | Retourne | Mode UI correspondant |
|---|---|---|
| `GET /api/mol3d` | 1 Kekulé arbitraire + cycles + radicaux | "Défaut" (vue initiale) |
| `GET /api/kekule_list?max=N` | Liste de N Kekulé canoniques | "Kekulé" (navigation) |
| `GET /api/clar_list?max=N` | Liste de N couvertures de Clar de score max | "Clar" (sextets) |
| `GET /api/rbo?max=N` | RBO + bond_orders + cbo/cbo_max par cycle | "RBO" (délocalisation) |

### 6.2 Cache

Chaque endpoint utilise `@lru_cache(maxsize=256)` avec une clé composée
de `(rel_path, xyz_text [, max_count])`. Les calculs lourds
(enumerate_kekule, enumerate_clar_covers) ne s'exécutent qu'une fois
par molécule unique. Plafond mémoire : environ 2 MB de cache total.

### 6.3 Frontend ([`viewer/molviz/static/molviz.js`](../viewer/molviz/static/molviz.js))

Une seule fonction publique `MolViz.openSafe({xyz_path, title, ...})`
qui :

1. Ouvre une modale avec un canvas 3Dmol.js.
2. Fetch `/api/mol3d` pour le rendu initial.
3. Charge la lib 3Dmol.js si pas déjà chargée (lazy).
4. Affiche un menu déroulant pour basculer entre les 4 modes.

Les **modes d'affichage** :

- **Défaut** : carbones + bonds (double = trait double), radicaux en
  sphères rouges, cycles colorés selon taille (6 = bleu, 5 = orange,
  7 = vert).
- **Kekulé** : navigation entre toutes les Kekulé énumérées avec
  flèches gauche/droite. Affiche le numéro et le total.
- **Clar** : affiche les ronds de Clar (cercles orange) sur les
  hexagones du sextet. Navigation entre les couvertures de Clar
  maximales si plusieurs.
- **RBO** : couleur des arêtes graduée selon `bond_orders[e]`
  (rouge = pure simple, bleu = pure double, gradient en
  intermédiaire). Affiche `cbo[C] / cbo_max[C]` au centre de chaque
  cycle.

Tous les calculs (Kekulé, Clar, RBO) sont **purement statiques** : ils
opèrent sur le squelette + connectivité, **sans** lancer de calcul
quantique. Ils sont donc instantanés (millisecondes) une fois le
graphe construit.

---

## 7. Cas particuliers et limites

### 7.1 Molécules ouvertes (fragmentation)

Si l'optimisation xTB a cassé la molécule (un atome s'est éloigné), le
détecteur de bonds produit un graphe avec **plusieurs composantes
connexes**. Tous les calculs (Kekulé, Clar, RBO) s'appliquent alors
**par composante**, mais le résultat n'a plus de sens chimique cohérent.
Le viewer ne signale pas explicitement la fragmentation (à améliorer).

### 7.2 Cycles "anormaux"

Si un cycle a une taille différente de 5/6/7 (par exemple 4 ou 8 après
une optimisation pathologique), il est tagué `anomaly=True`. Les
sextets de Clar ne sont jamais portés par un cycle anomal.

### 7.3 Énumérations plafonnées

Pour les molécules avec beaucoup de symétries ou des cycles longs,
l'énumération exhaustive des Kekulé peut exploser. Plafonds par
défaut :

- `enumerate_kekule` : 10000 (pour RBO)
- `enumerate_clar_covers` : 200 (pour navigation viewer)

Quand plafonné, `is_exact = False` est remonté à l'API, et le viewer
affiche un avertissement "Plus de N structures, affichage tronqué".

### 7.4 Radicaux et RBO

Une molécule **radicalaire** (sans Kekulé stricte) a `available=False`
pour RBO, car la définition de Pauling-Randić n'est plus applicable.
Une extension naturelle serait d'utiliser les **matchings maximums**
(qui couvrent un sous-graphe maximal et laissent les mêmes radicaux),
mais ce n'est pas implémenté pour l'instant — c'est une piste pour
les évolutions futures.

### 7.5 Coût asymptotique

- **Détection bonds + cycles** : $\mathcal{O}(|A|^2)$ pour les bonds,
  $\mathcal{O}(|A| + |E|)$ pour les cycles via BFS.
- **assign_kekule** : Edmonds Blossom, $\mathcal{O}(|A|^3)$.
- **enumerate_kekule** : backtracking, **exponentiel** dans le pire cas.
  Pratique pour $|A| \le 50$ environ.
- **enumerate_clar_covers** : $\mathcal{O}(2^{n_{\text{hex}}})$ avec
  vérification de vertex-disjointness en $\mathcal{O}(n_{\text{hex}}^2)$
  + matching du résidu en $\mathcal{O}(|A|^3)$. Trivial pour
  $n_{\text{hex}} \le 9$.
- **compute_rbo** : domine par `enumerate_kekule`.

Pour h≤9 (notre cas), tout est instantané (≤ 100 ms par molécule).

---

## 8. Références bibliographiques

- **Kekulé / matching parfait** : Lovász, *Combinatorial Problems and
  Exercises*. Algorithme d'Edmonds : J. Edmonds, *Paths, trees, and
  flowers*, 1965.
- **Clar 1972** : E. Clar, *The Aromatic Sextet*, Wiley. Définition
  originale du sextet et nombre de Clar.
- **RBO / bond order Pauling-Randić** : L. Pauling, *The Nature of the
  Chemical Bond*. M. Randić, *Conjugated circuits and bond orders*.
- **Thèse Varet** (référence interne) : définitions formelles des
  sections 2.4.5 (Clar) et 2.4.14-2.4.15 (RBO). Cf module
  [`viewer/molviz/clar.py`](../viewer/molviz/clar.py) docstring qui
  pointe vers ces sections.
- **Règle de Hückel** : E. Hückel, 1931. $4n + 2$ électrons $\pi$ pour
  un cycle aromatique stable.
- **Pipeline complet du designer** : [`doc/PIPELINE.md`](PIPELINE.md)
- **Contraintes CSP du solveur amont** : [`doc/CONTRAINTES.md`](CONTRAINTES.md)
