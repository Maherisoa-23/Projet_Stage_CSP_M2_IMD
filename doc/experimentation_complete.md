# Experimentation complete -- journal detaille

Document complementaire a `experimentation.md` (qui contient la synthese et
la recommandation finale). Ici, on garde la trace **chronologique et
detaillee** de toutes les pistes explorees, y compris celles qui n'ont pas
abouti, avec les chiffres exacts et les decisions prises.

Public cible : le stagiaire qui reprendra le projet, le jury qui veut
comprendre la demarche, le lecteur du memoire qui veut creuser un point.

---

## Sommaire

1. [Pipeline et choix techniques](#1-pipeline-et-choix-techniques)
2. [Configurations CSP du run final (C1/C2/C3)](#2-configurations-csp-du-run-final)
3. [Migration vers la DB du viewer](#3-migration-vers-la-db-du-viewer)
4. [Configurations virtuelles initiales (C4/C5/C8/C48)](#4-configurations-virtuelles-initiales)
5. [Analyse manuelle des sols non-plans h9 (top-10)](#5-analyse-manuelle-des-sols-non-plans)
6. [Tentative C9 : echec du triple_jct_defect](#6-tentative-c9)
7. [Decouverte du non-determinisme xTB MD](#7-decouverte-du-non-determinisme-xtb-md)
8. [Motifs de bord (w=4, w=5)](#8-motifs-de-bord)
9. [Validation universelle h7/h8/h9 des motifs de bord](#9-validation-universelle-h7h8h9)
10. [Configurations virtuelles "C-motifs"](#10-configurations-virtuelles-c-motifs)
11. [Motifs rayon-2 du graphe dual](#11-motifs-rayon-2-du-graphe-dual)
12. [Topologie du squelette (avant assignment)](#12-topologie-du-squelette)
13. [Combinaison finale : Ctopo](#13-combinaison-finale--ctopo)
14. [Visualisations produites](#14-visualisations-produites)
15. [Bilan numerique complet](#15-bilan-numerique-complet)

---

## 1. Pipeline et choix techniques

### 1.1 Chaine de traitement

```
Squelette benzenoide (h hexagones)
   │
   ▼ Solveur CSP (PyCSP3 + ACE)
[Affectations valides (5/6/7) sur cycles]
   │
   ▼ Reconstruction 3D + det-opt xTB
[Geometrie XYZ optimisee]
   │
   ▼ Mesure angle hors-plan (ACP sur coords C)
[Verdict PLAN (<= 10°) | NON_PLAN | xTB_failed]
```

### 1.2 Contraintes CSP de base (utilisees par toutes les configs)

- **Table de voisinage** : liste exhaustive des paires (taille, tailles_voisins)
  geometriquement realisables. Construite manuellement.
- **Conservation atomique** : Sigma x = 6h (le nombre total d'atomes du
  non-benzenoide est conserve par rapport au benzenoide d'origine).
- **Symetrie C1/C3** : canonisation des solutions equivalentes par rotation /
  reflexion.

Source : `csp_solver/utils/model.py`.

### 1.3 Generation 3D + optimisation xTB

Apres une solution CSP, on reconstruit une geometrie 3D plate initiale
(coordonnees planaires generees a partir de la topologie hexagonale +
substitutions 5/7 locales). Cette geometrie sert d'input a une optimisation
xTB.

Le protocole originel etait :
```
xtb geom_init.xyz --md 1ps@298K   # casser les minima plats parasites
tail [last frame] xtb.trj > md_geom.xyz
xtb md_geom.xyz --opt tight
```

Mais ce protocole n'est pas reproductible (cf. section 7). Nous avons donc
remplace la MD par une **perturbation analytique deterministe** :
```
z_i' = z_i + 0.05 × sin(2π × i/N + 0.5)
```
Puis `xtb perturbed.xyz --opt tight` avec `OMP_NUM_THREADS=1`,
`MKL_NUM_THREADS=1`.

Le pipeline complet est byte-deterministe : md5(`md_final_opt.xyz`) est
constant pour un meme input.

Source : `csp_solver/xtb/md.py` (les noms `md_*` sont conserves pour
retro-compat avec les scripts existants).

### 1.4 Verdict planarite

ACP sur les coordonnees des carbones :
- Plan principal = les 2 axes de variance maximale.
- Angle hors-plan = angle entre les 2 vecteurs normaux du plan principal et
  du plan ideal de la solution.
- Seuil : <= 10° -> PLAN, sinon NON_PLAN.

---

## 2. Configurations CSP du run final

Trois configurations CSP ont ete executees integralement (run xTB cluster)
sur h3-h9.

### 2.1 C1 -- Base (topologie minimale)

```python
{
    "label": "Base (topologie minimale)",
    "preset_name": None,
    "K_sym": None, "K_pb": None, "K_hb": None, "K_tot": None,
    "tau_gb": None, "radius_gb": 2,
    "adj_57": False,
    "no_table": False,
    "freeze_b2": False,
}
```

Pas de contrainte additionnelle. Sert de baseline et fournit l'espace de
reference pour les analyses a posteriori.

### 2.2 C2 -- Pb1 + adj_57

```python
{
    "label": "Pb1 + adj_57",
    "preset_name": "pb1_adj57",
    "K_pb": 1,             # Pb1 : n_pent <= 1
    "adj_57": True,        # >= 1 paire pent-hept adjacente
    ...
}
```

Motivation : forcer la presence d'un motif Stone-Wales (compensation locale
de courbure +pi/3 / -pi/3) tout en limitant la concentration de pentagones.

### 2.3 C3 -- C2 + tau_gb = 0

```python
{
    "label": "Pb1 + adj_57 + tau_gb=0 (interdiction 7-7 adjacents)",
    ...
    "tau_gb": 0,           # aucune paire d'heptagones adjacents (rayon 2)
}
```

Source : `csp_solver/_final_configs.py`.

### 2.4 Resultats numeriques du run final

```
 h    cfg     N_sols   N_plans    %PLAN   median   max
 h6   C1        2146      1684    78.5%    0.28°  79.09°
 h6   C2         254       224    88.2%    0.24°  49.82°
 h6   C3          75        70    93.3%    0.18°  27.93°
 h7   C1       15004      9886    65.9%    0.41°  87.01°
 h7   C2         900       750    83.3%    0.29°  82.25°
 h7   C3         178       170    95.5%    0.24°  24.19°
 h8   C1      112800     64746    57.4%    0.65°  89.68°
 h8   C2        3292      2701    82.0%    0.34°  87.90°
 h8   C3         512       498    97.3%    0.29°  33.22°
 h9   C1      646319    246855    38.2%   19.82°  89.86°
 h9   C2       21127     10506    49.7%   10.38°  89.07°
 h9   C3        2845      1711    60.1%    0.60°  80.70°
```

Observation : **C3 plafonne a 60% sur h9**, en chute drastique par rapport
a 97% sur h8. C'est ce qui a motive toute l'analyse post-hoc qui suit.

---

## 3. Migration vers la DB du viewer

La DB du run final (`experiments/final/final_h3_h9.db`) contient les
solutions sous une schema specifique (table `final_solutions`). Le viewer
attend un schema different (tables `xyz_files`, `molecules`, `solutions`,
`configs`).

**Solution** : creer une VIEW `xyz_files` qui mappe sur
`final_solutions.xyz_optimized_gz` (pas de duplication des 3 Go de XYZ),
plus des tables materialisees `solutions` (805 909 rows), `molecules`
(7 725 rows), `configs` (21 rows).

Convention `rel_path` :
```
final/h{size_h}/{config}/{graph_name}/sol{sol_index}/md_validation/md_final_opt.xyz
```

Mapping verdict : `PLAN -> plan`, `NON_PLAN -> non_plan`,
`LIMITE -> non_plan`, `status=failed -> xtb_failed`.

Script : `tmp/migrate_final_to_viewer.py`.

---

## 4. Configurations virtuelles initiales

Premiere serie de tentatives : filtrer les sols C1 done par des predicats
topologiques **simples** sans relancer xTB.

### 4.1 Predicats testes

```python
VIRTUAL_CONFIGS = {
    'C4':  "adj_77 = 0",                       # pas de 7-7 adjacents
    'C5':  "adj_77 = 0 AND adj_55 = 0",        # ni 7-7 ni 5-5
    'C8':  "n_pent + n_hept <= 4",             # peu de defauts
    'C48': "adj_77 = 0 AND n_sum <= 4",        # combinaison
}
```

Features calculees par `tmp/compute_adjacencies_all.py` (table `sol_features`,
776 598 rows en ~17s avec multiprocessing).

Materialisation par `tmp/materialize_virtual_configs.py`.

### 4.2 Resultats

```
 h    cfg     N_sols   N_plans    %PLAN
 h8   C1      112800     64746    57.4%
 h8   C2        3292      2701    82.0%
 h8   C3         512       498    97.3%
 h8   C4       63063     42087    66.7%
 h8   C5       44107     29551    67.0%
 h8   C8       47673     31459    66.0%
 h8   C48      42086     28230    67.1%
```

**Observation** : toutes les configs virtuelles convergent vers **~67% PLAN
sur h8**, plafond qui n'atteint pas C2 reel (82%). Le facteur dominant est
clairement **Pb1** (n_pent <= 1), pas un filtrage topologique post-hoc.

**Conclusion** : ces configs ont ete abandonnees apres validation. Elles
ont ete supprimees de la DB lors de la materialisation de Ctopo.

---

## 5. Analyse manuelle des sols non-plans h9 (top-10)

Pour comprendre **pourquoi** C3 echoue sur h9, on a regarde les 10 sols h9
avec les plus grands angles (~89.5-89.9°), dedoublonnees par
`(mol, sol_idx)`.

Script : `tmp/analyze_h9_top10.py`.

### 5.1 Caracteristiques communes

- Tous a `K_signed = n5 - n7 = 0` (courbure cumulee Gauss-Bonnet nulle).
- Tous avec des max_dual_deg = 3.

### 5.2 Deux familles identifiees

**Famille A : saturation en defauts (7 sols / 10)**

| sol | n5 | n7 | adj 55 / 57 / 77 | cluster |
|---|---:|---:|---|---:|
| `1-11-21-30-39-48-56-57-67`#242 | 4 | 4 | 2 / 3 / 2 | 8 |
| `1-2-11-21-30-39-48-56-57`#29  | 4 | 4 | 1 / 5 / 1 | 8 |
| `3-9-12-19-22-29-30-31-40`#378 | 4 | 4 | 1 / 6 / 0 | 6 |

Pattern : **8 cycles non-hex sur 9 cycles totaux**, defauts en amas (un seul
cluster connexe de defauts), tous sur le bord. Co-presence frequente de
`adj_55 >= 1` ET `adj_77 >= 1` -> frustration geometrique : compensation
locale +π/3 / -π/3 impossible globalement.

**Famille B : defauts isoles sur atome peri-condense (3 sols / 10)**

| sol | n5 | n7 | adj | triple_jct |
|---|---:|---:|---|---:|
| `3-13-18-19-20-22-23-30-31`#695 | 2 | 2 | 5-7=1 | 1 |
| `3-12-18-21-22-27-28-29-30`#714 | 2 | 2 | 5-7=1 | 2 |
| `3-9-11-12-18-21-28-29-30`#883 | 2 | 2 | 5-5=1 | 1 |

Pattern : peu de defauts (4 sur 9), defauts isoles, mais squelette
**peri-condense** (au moins 1 atome partage par 3 cycles).

### 5.3 Interpretation initiale (qui sera infirmee)

A ce stade on a postule que `triple_jct >= 1` etait un facteur **defavorable**
a la planarite. C'est cette hypothese qui mene a la tentative C9 (section 6).

---

## 6. Tentative C9

### 6.1 Formulation

```
C9 = Pb1 + adj_77 = 0 + n_sum <= 4 + triple_jct_defect = 0
```

ou `triple_jct_defect` = atomes peri-condenses qui appartiennent a au moins
un cycle pent ou hept.

Features calculees par `tmp/compute_c9_features.py` (table
`sol_features_c9`).

### 6.2 Resultats

```
 h    variante                  N_sols   N_plans    %PLAN
 h9   C1                        606402    246855    40.7%
 h9   triple_jct_def=0          148280     51736    34.9%   # WORSE !
 h9   Pb1 only                   24117     12378    51.3%
 h9   C9 complete                 9076      4360    48.1%
 h9   C2 reel                    21127     10506    49.7%
```

**Verdict** : ECHEC. La feature `triple_jct_defect = 0` est **anti-correlee**
avec PLAN (34.9% vs baseline 40.7%). La famille B identifiee dans le top-10
etait une **coincidence statistique sur 3 cas**, pas un mecanisme general.

Pire : ajouter `triple_jct_defect = 0` a Pb1 + adj_77=0 **FAIT BAISSER** le
%PLAN (78% -> 76% sur h8, 51% -> 48% sur h9). Le filtre exclut plus de plans
que de non-plans.

### 6.3 Lecon

Une interpretation visuelle sur 3-10 cas extremes n'est PAS validable
statistiquement. Il faut TOUJOURS tester l'hypothese sur la distribution
complete avant de la promouvoir en contrainte.

---

## 7. Decouverte du non-determinisme xTB MD

Pendant la mise au point du run final, on a observe que **deux runs xTB MD
identiques produisaient des verdicts differents** (PLAN/NON_PLAN bascule)
sur certaines structures tendues.

### 7.1 Verification

Test direct avec la configuration recommandee par les chimistes (Yannick) :
```
$md
   temp=298.15
   time=1.0     # ps
   dump=50.0    # fs
   step=4.0     # fs
   velo=false
   nvt=true
   hmass=4
   sccacc=2.0
$end
```
Sequence : `xtb --md` puis `xtb --opt` sur la derniere frame.

**3 runs identiques, OMP_NUM_THREADS=1, MKL_NUM_THREADS=1** :

| Fichier | Benzene C6H6 | h6 tendu (sol angle 79°) |
|---|---|---|
| xtb.trj      | 3 MD5 differents | 3 MD5 differents |
| geom.xyz     | 3 MD5 differents | 3 MD5 differents |
| xtbopt.xyz   | 3 MD5 differents | 3 MD5 differents |
| Energie (Eh) | varie de ~7e-7 | varie de ~4e-5 (~0.024 kcal/mol) |
| Ecart au plan | -- | 1.6976 / 1.7189 / 1.6942 A |

### 7.2 Cause racine

Verification du code source xTB (subroutine `mdinitu`,
`src/dynamic.f90`) : les vitesses initiales Maxwell-Boltzmann sont tirees
par `call random_number()` sans seed fixee. La graine de Fortran est tiree
de l'horloge systeme par `call random_seed()` (sans argument).

Il existe **une** instruction xcontrol semi-cachee : `$samerand` (dans
`src/setparam.f90:550-566`) qui force une seed hardcodee (`imagic=41`). Mais
elle n'est pas dans `$md`, n'est pas documentee, et n'expose pas la valeur
de la seed a l'utilisateur. Si Yannick l'utilisait il n'en parle pas.

### 7.3 Issue GitHub officielle

[#730 "Provide a seed parameter for the random number generator"](https://github.com/grimme-lab/xtb/issues/730)
ouverte **2022-11-25**, label "enhancement", **toujours OPEN**, zero
reponse de mainteneur. Re-pings 2025-04 et 2025-07 sans suite.

Position officielle des mainteneurs (issue #348) : reproductibilite via
fichiers `mdrestart`, **pas** via seed.

### 7.4 Notre solution : det-opt

Remplacement de la MD par une perturbation deterministe :
```
z_i' = z_i + amplitude * sin(2π × i/N + phase)
```
- amplitude = 0.05 A
- phase = 0.5 rad
- N = nombre d'atomes
- i = indice d'atome (ordre canonique du XYZ)

Pas de RNG. Identique a chaque appel. Brise la symetrie z=0 (qui imposerait
un gradient nul perpendiculaire au plan et piegerait `xtb --opt` sur le
minimum plat).

Puis `xtb perturbed.xyz --opt tight` avec `OMP_NUM_THREADS=1`,
`MKL_NUM_THREADS=1`.

Source : `csp_solver/xtb/md.py` (le nom `md.py` est conserve pour
retro-compat avec les scripts existants ; la docstring du module documente
le changement).

Email envoye a Yannick et Denis pour confirmer la decouverte (cf. section
8 du fichier ARCHITECTURE_FINAL_RUN.md).

---

## 8. Motifs de bord

Nouvelle direction d'analyse, inspiree de la litterature des benzenoides
(zigzag, cove, bay, deep bay, ultra-deep bay) : caracteriser les
**sequences de cycles** le long du bord externe.

### 8.1 Definition

Pour chaque solution :
1. Identifier les aretes-frontieres du graphe dual (aretes appartenant a 1
   seul cycle).
2. Parcourir ces aretes en sequence cyclique -> liste ordonnee de cycles.
3. Deduper les repetitions consecutives.
4. Extraire toutes les **fenetres glissantes** de longueur w (cyclique).
5. Canoniser chaque fenetre : `min(window, reversed(window))` (symetrie
   miroir).

Exemple sur h8 : un sol avec sequence de bord `6-5-6-7-6-5-6-7-6` donne en
w=4 les motifs `(6,5,6,7)`, `(5,6,7,6)`, `(6,7,6,5)`, etc. apres
canonisation.

Script : `tmp/extract_boundary_motifs.py` ou `tmp/extract_boundary_motifs_h8.py`.

### 8.2 Resultats h8 (baseline 60.08% PLAN)

**Top 10 motifs FAVORISANT (w=4)** :

```
motif           N      %PLAN   delta_pp
6-6-6-7      22095     73.5%   +13.4
6-6-6-6      16521     75.2%   +15.1
5-6-6-6      27611     70.7%   +10.6
5-7-6-6      22738     69.7%   +9.7
6-6-7-6      21909     69.9%   +9.8
6-5-6-6      23658     68.1%   +8.0
6-6-5-7      27622     66.6%   +6.5
```

Pattern : un defaut isole (pent OU hept) entoure d'hexagones. La
compensation locale fonctionne.

**Top 10 motifs DEFAVORISANT (w=4)** :

```
motif           N      %PLAN   delta_pp
5-7-7-7      18673     41.3%   -18.8
7-7-7-7       4414     27.5%   -32.6
5-5-7-7      18542     44.7%   -15.4
7-5-7-7      19784     46.2%   -13.9
5-5-5-7      11983     43.6%   -16.5
5-7-7-5      17663     47.2%   -12.9
6-7-7-7       2411     29.5%   -30.6
5-5-5-5       2384     31.0%   -29.1
```

Pattern : amas de cycles de meme nature (++ ou --), ou melange mal
positionne.

### 8.3 w=5 : contrastes encore plus forts

```
motif              N      %PLAN   delta_pp
7-7-7-7-7       1478     14.0%   -46.1   <- catastrophique
5-5-5-5-5       1305     20.5%   -39.5
5-7-7-7-7       4187     27.7%   -32.4
6-6-6-6-7      10309     79.7%   +19.6   <- excellent
5-6-6-6-6      13218     77.0%   +17.0
```

Une chaine pure de 5 heptagones consecutifs = quasi-garantie de non-planarite.

### 8.4 Interpretation Gauss-Bonnet

- Hexagone (6) : angle plat, courbure 0.
- Pentagone (5) : +π/3 (cone, courbure positive).
- Heptagone (7) : -π/3 (selle, courbure negative).

Motif `5-7` adjacent compense localement (Stone-Wales). Casse :
- Amas meme signe : `7-7-7-7` accumule -4π/3, non-compensable en 2D
  -> repliement 3D.
- Melange mal positionne : `5-7-7-7` = +π/3 - 3π/3, pas d'appariement 1-1.

### 8.5 Nomenclature proposee

| Motif | Nom propose |
|---|---|
| `6-6-6-6`, `5-6-6-6`, `6-6-6-7` | **plateau** |
| `5-7-6-6`, `7-6-6-5` | **soft cove** |
| `7-7-7-7`, `7-7-7-7-7` | **gorge negative** |
| `5-5-5-5`, `5-5-5-5-5` | **dome** (analogue calotte fullerene) |
| `5-7-7-7`, `5-5-5-7` | **frustration mixte** |
| `5-5-7-7`, `5-7-7-5` | **vallee profonde** (analogue deep bay) |

---

## 9. Validation universelle h7/h8/h9

Avant d'investir dans les motifs comme contrainte, on a verifie qu'ils sont
**reproductibles sur les 3 tailles** (h7, h8, h9).

Script : `tmp/extract_boundary_motifs.py` (parametrable par h).

### 9.1 Couverture combinatoire

```
w=4 : 45 motifs canoniques theoriques  (h7=45, h8=45, h9=45) -> 100%
w=5 : 135 motifs canoniques theoriques (h7=133, h8=135, h9=135) -> ~100%
```

### 9.2 Spearman entre classements

```
       w=4    w=5
h7-h8  0.916  0.892
h8-h9  0.941  0.938
h7-h9  0.896  0.848
```

Tous > 0.85. Les classements sont **fortement coherents** entre tailles.

### 9.3 Motifs universels (top 10 dans h7 ET h8 ET h9)

w=4 : `5-5-5-7`, `5-5-7-7`, `5-7-7-7`, `6-6-6-7`, `7-5-7-7`, `7-7-7-7`
(6/10 sur 10).

w=5 : `5-5-5-7-7`, `5-5-7-7-7`, `5-7-7-7-7`, `6-6-6-6-7`, `7-5-7-7-7`,
`7-7-5-7-7` (6/10 sur 10).

Tous les motifs deleteres en `7-...-7` sont presents partout. Les
favorisants en `6-6-6-x` aussi.

### 9.4 Erosion de l'effet avec h

Le motif `7-7-7-7` :
- h7 : 31.5% PLAN, Δ = -36.2 pp
- h8 : 27.5% PLAN, Δ = -32.6 pp
- h9 : 14.4% PLAN, Δ = -26.3 pp

L'effet **relatif** diminue (la baseline h9 a 40.7% est plus basse, donc
plus difficile d'etre tres en dessous). Mais en **valeur absolue**, c'est
plus catastrophique : `7-7-7-7-7` h9 = 7% PLAN.

---

## 10. Configurations virtuelles "C-motifs"

Tentative de filtrer les sols C1 en interdisant les motifs de bord
deleteres.

### 10.1 Blacklists

```python
BLACKLIST_W4_STRICT = {
    (7,7,7,7), (5,7,7,7), (5,5,5,7), (5,5,7,7), (7,5,7,7),
}
BLACKLIST_W5_STRICT = {
    (5,7,7,7,7), (7,5,7,7,7), (7,7,5,7,7), (5,5,5,7,7), (5,5,7,7,7),
}
# Plus une version "loose" ajoutant 5-5-5-5, 6-7-7-7, etc.
```

Favorisants : `6-6-6-7`, `5-6-6-6`, `5-7-6-6`, etc.

Script : `tmp/test_config_motifs.py`.

### 10.2 Resultats

```
                                N        N_plan    %PLAN
h9 C1                          606402    246855    40.7%
h9 C-mot strict (w4)           344763    163967    47.6%   (+6.9)
h9 C-mot loose (w4+w5)         315552    153112    48.5%   (+7.8)
h9 C-mot + fav_w5              146723     75678    51.6%   (+10.9)
h9 Pb1 only                     22937     12365    53.9%   (+13.2)
h9 Pb1 + C-mot                  22937     12365    53.9%   (= Pb1)
```

### 10.3 Conclusion

- Les motifs de bord ont un **vrai signal** (+5-10 pp) reproductible sur les
  3 tailles.
- Mais ils sont **domines par Pb1** : `Pb1 + C-mot` n'est pas mieux que `Pb1
  seul`.
- Pb1 capture l'essentiel de l'effet topologique des motifs.

Les configs C-motifs n'ont **pas ete materialisees** dans la DB (juste
testees). Elles font office de validation que la statistique motifs est
reelle mais redondante avec Pb1.

---

## 11. Motifs rayon-2 du graphe dual

Generalisation des motifs : au lieu de regarder les sequences le long du
bord externe (1D), on regarde **chaque cycle avec tous ses voisins
immediats** dans le graphe dual.

### 11.1 Definition

Pour chaque cycle ci :
```
motif(ci) = (sizes[ci], tuple(sorted(sizes[u] for u in neighbors_dual(ci))))
```

Exemple : `7|[5,7,7]` = un heptagone qui a comme voisins dans le dual : un
pentagone, deux heptagones.

Un sol contient un **multiset** de ces motifs. On compte pour chaque motif
distinct combien de sols qui le contiennent sont PLAN vs NON_PLAN.

Script : `tmp/test_radius2_motifs.py`.

### 11.2 Resultats h8 (baseline 60.08% PLAN)

**Top motifs DEFAVORISANT** :

```
motif (centre|voisins)    N      %PLAN   delta_pp
7|[6,7,7]               2069    9.23%   -50.85    <- record absolu
7|[5,6,7,7]             1650   14.12%   -45.96
7|[7,7]                 4361   22.11%   -37.98
7|[5,7,7]               7811   29.10%   -30.98
5|[5]                   9101   34.08%   -26.00
```

**Top motifs FAVORISANT** :

```
motif                     N      %PLAN   delta_pp
6|[6,6,6,7]             1077   87.74%   +27.66
5|[6,6,6,7]             1647   85.00%   +24.92
6|[5,6,6,6]             1624   83.62%   +23.54
6|[6,6,6]               4270   84.24%   +24.16
6|[5,6,6,7]             4888   83.29%   +23.20
```

### 11.3 Resultats h9 (baseline 40.71% PLAN)

```
motif                     N       %PLAN   delta_pp
7|[6,6,7,7]              3729    0.13%   -40.57    <- 5 plans sur 3729 !
6|[6,7,7]                4550    1.89%   -38.82
7|[6,7,7]               23815    6.14%   -34.57
7|[7,7]                 40118   17.70%   -23.01
```

`7|[6,6,7,7]` = quasi-garantie d'etre non-plan.

### 11.4 Pourquoi c'est plus fort que les motifs de bord

Les motifs de bord ne capturent que la **frontiere externe**. Les motifs
rayon-2 voient **tous les cycles**, y compris ceux a l'interieur (peri-condenses).
Sur h8/h9, beaucoup de defauts deleteres sont **internes** ou
**peri-positionnes**, hors du bord externe.

### 11.5 Limites

Notation compacte mais peu lisible (`7|[5,6,7,7]`). Pas de visualisation
dediee (contrairement aux motifs de bord qui ont 40 captures 3D dans
`doc/motifs_bord_h8.pdf`).

---

## 12. Topologie du squelette

Hypothese : la forme du squelette (**avant** assignment des 5/6/7) influence
deja la planarite, par la **rigidite mecanique** intrinseque.

Script : `tmp/test_skeleton_topology.py`.

### 12.1 Categories

Pour chaque squelette unique :
- `n_peri_atoms` : nombre d'atomes partages par >= 3 cycles
  (peri-condenses)
- `shape` : `linear` si max_dual_deg=2 ; `branched` si max_dual_deg>=3 et
  n_peri=0 ; `peri` si n_peri >= 1
- `max_dual_deg` : degre maximum dans le graphe dual

### 12.2 Resultats h9 par shape

```
shape           N_mol     N_sols     N_plan   %PLAN
branched          285      50898       6241   12.3%   <- catastrophique
linear            229      78915      40753   51.6%
peri             1904     476589     199861   41.9%
```

Un squelette branched (ramifie sans peri-condensation) ne donne que **12%
de plans** sur h9. Contre 52% pour linear et 42% pour peri.

### 12.3 Effet du nombre d'atomes peri-condenses (h9)

```
n_peri    N_mol    %PLAN
0          514     36.2%
1          762     39.7%
2          521     37.8%
3          344     41.8%
4          151     52.1%
5           72     61.3%
6           36     72.8%
7           14     76.6%
8            4     74.4%
```

**Plus le squelette est peri-condense, plus il est plan**, jusqu'a 76% pour
n_peri = 7. C'est **l'oppose** de ce qu'on avait suppose avec la Famille B.

Mecanisme physique : un squelette peri-condense (genre coronene, ovalene) a
beaucoup d'atomes partages, donc il est **mecaniquement rigide**. Il
resiste a la deformation. Un squelette etendu (catacondense lineaire) se
plie facilement.

### 12.4 Effet du max_dual_deg

```
max_dd    N_mol    %PLAN
2          229     51.6%
3         1384     37.8%   <- pire
4          689     38.4%
5          106     61.7%
6           10     73.0%
```

U-shape : les squelettes extremement lineaires (deg=2) et extremement
compacts (deg=5-6) sont les meilleurs. Les ramifies intermediaires (deg=3)
sont les pires.

---

## 13. Combinaison finale : Ctopo

L'union des deux descripteurs (rayon-2 + topologie squelette) donne le
meilleur predicteur post-hoc.

### 13.1 Predicats testes

Script : `tmp/test_combined_r2_skel.py`.

```python
BL_R2_LOOSE = {
    (7, (5,7,7)), (7, (7,7)), (7, (6,7,7)), (7, (5,6,7,7)),
    (5, (5,)), (7, (7,)),
    (7, (5,5,7,7)), (5, (5,5)), (7, (6,6,7,7)), (6, (6,7,7)),
}

FAV_R2 = {
    (6, (6,6,6,7)), (5, (6,6,6,7)), (6, (5,6,6,7)),
    (6, (6,6,6)), (6, (5,6,6,6)), (6, (6,6,7)),
}
```

### 13.2 Resultats par h

```
                                       N         N_plan   %PLAN
h7 C1 baseline                       14584       9886    67.8%
h7 C-r2 + n_peri >= 3                 2537       2234    88.1%
h7 C-r2 loose + n_peri >= 4           1035        989    95.6%

h8 C1 baseline                      107764      64746    60.1%
h8 C-r2 + n_peri >= 3                22037      17209    78.1%
h8 C-r2 loose + n_peri >= 4           9340       8092    86.6%

h9 C1 baseline                      606402     246855    40.7%
h9 C-r2 + n_peri >= 3                98644      58325    59.1%
h9 C-r2 loose + n_peri >= 4          43057      30742    71.4%   <- bat C3
h9 C-r2 + fav + n_peri >= 3          38190      24823    65.0%
```

### 13.3 Configuration retenue : Ctopo

```
Ctopo = sol C1 done satisfait :
        (1) has_bl_r2_loose = 0   (aucun motif rayon-2 dans la blacklist)
        ET
        (2) skel_n_peri >= 4      (squelette compact)
```

Resultats Ctopo vs C3 reel :

```
 h    Ctopo                    C3 reel
      N_sols  N_plans  %PLAN   N_sols  N_plans  %PLAN
 h6      90       90  100.0%      75       70   93.3%
 h7    1035      989   95.6%     178      170   95.5%
 h8    9340     8092   86.6%     512      498   97.3%
 h9   43057    30742   71.4%    2845     1711   60.1%   <- bat C3 nettement
```

### 13.4 Pourquoi Ctopo est nouveau

- La litterature des benzenoides decrit principalement le **bord** (zigzag,
  cove, deep bay).
- Ctopo combine un descripteur **bord-dual** (motif rayon-2 ne se limite pas
  au bord) avec un descripteur **bulk-dual** (n_peri sur le squelette).
- Le tout sur des **non-benzenoides** (avec cycles 5 et 7), pas sur des
  benzenoides purs.

Ce croisement n'a pas d'equivalent direct dans les travaux sur les
defauts Stone-Wales, qui se concentrent sur la **paire** 5-7 isolee, pas sur
l'interaction avec la topologie peri-condensee globale.

### 13.5 Materialisation

Script : `tmp/materialize_ctopo.py`. INSERT depuis C1 done filtre, sol_dir
pointant vers C1 (pas de duplication XYZ).

Tables modifiees : `solutions` (+ 53 522 rows), `molecules` (+ 352 rows),
`configs` (+ 4 rows : h6, h7, h8, h9).

---

## 14. Visualisations produites

Tout dans `doc/` (les .pdf/.png sont gitignored sauf experimentation.md).

### 14.1 doc/motifs_bord_h8.pdf

6 pages, 3.1 MB, genere par `tmp/gen_motifs_latex_with_images.py` :
- p1 : methodologie
- p2 : top 10 favorisants w=4 (10 captures 3D)
- p3 : top 10 defavorisants w=4
- p4 : top 10 favorisants w=5
- p5 : top 10 defavorisants w=5
- p6 : lecture statistique + nomenclature

Chaque vignette = sol reel de la DB, projection top-down via 3Dmol.js,
fenetre du motif surlignee.

### 14.2 doc/captures/ (40 PNG)

Captures 3D top-down realisees par `tmp/capture_motif_views.py` avec
Playwright + 3Dmol.js. Aligne la camera sur l'axe principal d'inertie de
la molecule. Couleurs : pent rouge clair, hex gris, hept bleu clair, cycles
de la fenetre du motif en couleurs saturees.

### 14.3 Viewer Flask integre

`http://127.0.0.1:8765` apres lancement de `viewer/server.py`. Permet de
naviguer interactivement dans les 4 configs (C1/C2/C3/Ctopo), descendre
jusqu'aux sols individuelles, et visualiser en 3D avec annotations
Kekule/Clar.

---

## 15. Bilan numerique complet

### 15.1 Tableau complet par (h, config)

```
 h    cfg     N_sols   N_plans    %PLAN
 h3   C1           7         7   100.0%
 h3   C2           5         5   100.0%
 h3   C3           5         5   100.0%
 h4   C1          44        42    95.5%
 h4   C2          16        16   100.0%
 h4   C3          12        12   100.0%
 h5   C1         278       245    88.1%
 h5   C2          62        55    88.7%
 h5   C3          28        24    85.7%
 h6   C1        2146      1684    78.5%
 h6   C2         254       224    88.2%
 h6   C3          75        70    93.3%
 h6   Ctopo       90        90   100.0%
 h7   C1       15004      9886    65.9%
 h7   C2         900       750    83.3%
 h7   C3         178       170    95.5%
 h7   Ctopo     1035       989    95.6%
 h8   C1      112800     64746    57.4%
 h8   C2        3292      2701    82.0%
 h8   C3         512       498    97.3%
 h8   Ctopo     9340      8092    86.6%
 h9   C1      646319    246855    38.2%
 h9   C2       21127     10506    49.7%
 h9   C3        2845      1711    60.1%
 h9   Ctopo    43057     30742    71.4%
```

### 15.2 Totaux sur le run

- Solutions CSP total : ~1 907 641 rows dans la DB viewer
- Molecules uniques : ~7 725
- Plans absolus :
  - C1 (toutes tailles) : ~328 159
  - C2 : ~14 252
  - C3 : ~3 070
  - Ctopo : ~39 913

### 15.3 Compute total

- Run xTB complet (C1+C2+C3 h3-h9) : ~3 mois cluster
- Calcul features (sol_features, sol_features_c9,
  sol_combined_features, sol_motif_features) : ~5 min cumule (multiproc local)
- Captures 3D Playwright : ~20 min pour 40 images

---

## Annexes

### A. Glossaire

- **C-r2** ou **rayon-2** : motif local = (taille_cycle, multiset(tailles_voisins_dans_le_dual))
- **n_peri** : nombre d'atomes appartenant a >= 3 cycles
- **bord externe** : ensemble des aretes du graphe dual appartenant a 1 seul cycle
- **det-opt** : optimisation deterministe (perturbation sin analytique + xtb --opt)
- **Pb1** : contrainte CSP `n_pent <= 1` (au plus un pentagone)
- **tau_gb** : contrainte de courbure cumulee (Gauss-Bonnet) sur le voisinage rayon r

### B. Scripts et tables DB

```
TABLES en DB experiments/final/final_h3_h9.db :
  final_solutions       table source (run xTB)
  solutions             vue pour le viewer
  molecules             agregat par mol
  configs               agregat par (h, config)
  xyz_files             VIEW sur final_solutions.xyz_optimized_gz
  sol_features          adj_55, adj_57, adj_77, n_sum (par sol_id)
  sol_features_c9       n_pent, n_hept, triple_jct_defect
  sol_motif_features    has_bl_strict_w4, has_bl_loose_w5, has_fav_w5, ...
  sol_combined_features has_bl_r2_strict/loose, has_fav_r2, skel_shape, skel_max_deg, skel_n_peri
```

```
SCRIPTS canoniques dans tmp/ :
  migrate_final_to_viewer.py        migration DB
  compute_adjacencies_all.py        adj_55/57/77
  compute_c9_features.py            n_pent, triple_jct
  extract_boundary_motifs.py        motifs de bord (parametrable h)
  test_radius2_motifs.py            motifs rayon-2 dual
  test_skeleton_topology.py         classification squelette
  test_combined_r2_skel.py          combinaison rayon-2 + topologie
  materialize_ctopo.py              materialisation Ctopo
  gen_motifs_latex_with_images.py   generation PDF figures
  capture_motif_views.py            captures Playwright 3Dmol
```

### C. References externes

- Issue xTB #730 : https://github.com/grimme-lab/xtb/issues/730
- Docs xTB : https://xtb-docs.readthedocs.io/en/latest/md.html
- PyCSP3 : https://pycsp.org/
- 3Dmol.js : https://3dmol.csb.pitt.edu/
