# Experimentation -- generation de non-benzenoides plans par CSP

Synthese des configurations CSP testees, du protocole de validation, des
resultats numeriques et de la recommandation finale post-analyse.

---

## 1. Objectif

Generer des structures non-benzenoides (h cycles avec tailles dans {5, 6, 7})
sur des squelettes benzenoides de tailles `h3` a `h9`, et identifier les
**contraintes topologiques** qui favorisent la **planarite** de la structure 3D
apres optimisation xTB.

La planarite est quantifiee par l'angle hors-plan maximal de la structure
optimisee : seuil <= 10° = PLAN, sinon NON_PLAN.

---

## 2. Pipeline

```
Squelette benzenoide (h hexagones)         ─┐
   │                                        │
   ▼                                        │ CSP : table de voisinage
[Solveur CSP -- PyCSP3 + ACE]               │       Sigma x = 6h
   │                                        │       symetries C1/C3
   ▼ affectations valides (sizes ∈ {5,6,7})┘
   │
[Reconstruction 3D + det-opt xTB]
   │                                        │ OMP=1, perturbation z
   ▼ XYZ optimise                           │ analytique deterministe
   │
[Mesure angle hors-plan + verdict]
   │
   ▼
PLAN (<=10°) | NON_PLAN | xTB_failed
```

**Note importante sur le protocole xTB.** Les premieres versions utilisaient
une dynamique moleculaire courte (xtb --md, 1 ps a 298 K) suivie d'une
optimisation. Nous avons constate que xTB MD n'est PAS deterministe (graine
des vitesses initiales tiree sur l'horloge systeme, aucun parametre `seed`
expose -- confirme par lecture du code source et par l'issue GitHub #730
ouverte depuis 2022 sans reponse). Sur les structures tendues h8-h9 avec amas
5/7 denses, cette non-reproductibilite faisait basculer les verdicts
PLAN/NON_PLAN entre deux runs identiques.

Nous avons donc remplace la MD par une **perturbation analytique deterministe**
suivie d'une optimisation `xtb --opt tight` :

```
z_i' = z_i + 0.05 × sin(2π · i / N + 0.5)
```

Cette perturbation, parametree sur l'indice d'atome, brise la symetrie z=0
(qui pieger l'opt sur le minimum plat) sans introduire de RNG. Le pipeline
est ainsi byte-deterministe : md5(xyz_final) constant pour un meme input.

Tout est stocke dans `experiments/final/final_h3_h9.db`.

---

## 3. Configurations CSP

Trois configurations CSP ont ete executees a travers le run final (run xTB
complet sur ~776k solutions h3-h9) :

| Config | Contraintes additionnelles | Motivation |
|--------|---------------------------|------------|
| **C1** | aucune (baseline) | Mesurer le taux brut de planarite, fournir l'espace de reference. |
| **C2** | `Pb1` (n_pent <= 1) + `adj_57 >= 1` | Forcer un motif Stone-Wales (compensation locale de courbure +π/3 / -π/3) et limiter la concentration de defauts. |
| **C3** | C2 + `tau_gb = 0` rayon 2 | Interdire les paires d'heptagones adjacents (concentration de courbure negative). |

Symetrie C1/C3 activee, gel d'hexagone desactive, table de voisinage active.
Source : `csp_solver/_final_configs.py`.

### Resultats numeriques C1/C2/C3

```
 h    cfg     N_sols   N_plans    %PLAN
 h6   C1        2146      1684    78.5%
 h6   C2         254       224    88.2%
 h6   C3          75        70    93.3%
 h7   C1       15004      9886    65.9%
 h7   C2         900       750    83.3%
 h7   C3         178       170    95.5%
 h8   C1      112800     64746    57.4%
 h8   C2        3292      2701    82.0%
 h8   C3         512       498    97.3%
 h9   C1      646319    246855    38.2%
 h9   C2       21127     10506    49.7%
 h9   C3        2845      1711    60.1%
```

### Lectures

1. **C3 est la configuration la plus pure** : 95-97% PLAN sur h7-h8.
2. **Effondrement de C3 sur h9** : 60% PLAN seulement, et le nombre absolu de
   solutions chute drastiquement (1 711 plans contre 246 855 pour C1).
3. Les contraintes locales (Pb1, adj_57, tau_gb=0) **sont efficaces a moyenne
   taille mais ne couvrent pas tous les mecanismes** d'echec sur h9.

---

## 4. Analyse a posteriori et recommandation

Apres le run final, plusieurs descripteurs topologiques ont ete extraits des
solutions C1 sans relancer xTB. L'objectif : trouver un filtre qui apporte
quelque chose de **non-redondant** avec Pb1.

### 4.1 Ce qui n'a pas marche (resume)

- **Configs virtuelles "simples"** (adj_77=0, adj_55+adj_77=0, n_sum<=4) :
  plafonnent autour de 67% PLAN sur h8, moins bonnes que C2 reel. Pb1 capture
  deja l'essentiel de leur effet.
- **C9 (Pb1 + adj_77=0 + n_sum<=4 + triple_jct_defect=0)** : echec. La feature
  `triple_jct_defect` est **anti-correlee** avec PLAN (les defauts sur atomes
  peri-condenses sont en moyenne plus stables -- contre-intuitif).
- **Motifs de bord** (fenetres glissantes w=4 et w=5 sur le bord externe) :
  universels h7/h8/h9 (Spearman 0.9+), signature claire (`7-7-7-7-7` a 14%
  PLAN, `5-5-5-5-5` a 20%), mais comme contrainte virtuelle : +5-7 pp
  seulement, **domine par Pb1**. Documente separement en annexe.

### 4.2 La piste qui marche : combinaison rayon-2 + topologie squelette

Deux descripteurs topologiques se sont reveles **complementaires** et
**independants de Pb1** :

**Descripteur 1 -- motifs rayon-2 du graphe dual**

Pour chaque cycle, on calcule son motif local : `(taille_centrale, multiset
des tailles de voisins)`. Exemple : `7|[5,7,7]` = heptagone avec deux
heptagones et un pentagone voisins.

Motifs deleteres (universels h7/h8/h9) :
- `7|[6,7,7]` -> 9.2% PLAN (h8), Δ = -50.9 pp
- `7|[6,6,7,7]` -> 0.13% PLAN (h9), Δ = -40.6 pp
- `7|[7,7]`, `7|[5,7,7]`, `7|[5,6,7,7]`, `5|[5]`, `5|[5,5]`, `6|[6,7,7]`

Motifs favorables : `6|[6,6,6,7]`, `5|[6,6,6,7]`, `6|[5,6,6,7]`, etc.

**Descripteur 2 -- topologie du squelette (avant assignment)**

On classe chaque squelette par sa forme **avant** d'attribuer les tailles 5/6/7 :

- `n_peri_atoms` : nombre d'atomes partages par 3 cycles (peri-condenses)
- `shape` : linear / branched / peri-compact
- `max_dual_deg` : degre maximal dans le graphe dual

**Observation cle** sur h9 : `n_peri_atoms >= 3` augmente le %PLAN de
+30 pp **independamment** de l'assignment 5/6/7. Mecanisme : un squelette
peri-condense est rigide (genre coronene), il resiste a la deformation. Un
squelette etendu (catacondense lineaire ou branche) se replie facilement.

### 4.3 Configuration recommandee : **Ctopo**

```
Ctopo : sol C1 done qui satisfait
        (1) has_bl_r2_loose = 0   (aucun motif rayon-2 deletere)
        ET
        (2) skel_n_peri >= 4      (squelette compact)
```

Resultats Ctopo vs C1/C2/C3 :

```
 h    cfg     N_sols   N_plans    %PLAN
 h6   C3          75        70    93.3%
 h6   Ctopo       90        90   100.0%
 h7   C3         178       170    95.5%
 h7   Ctopo     1035       989    95.6%
 h8   C3         512       498    97.3%
 h8   Ctopo     9340      8092    86.6%
 h9   C3        2845      1711    60.1%
 h9   Ctopo    43057     30742    71.4%
```

### 4.4 Pourquoi Ctopo est interessante

1. **Bat C3 sur h9 en purete ET en volume** : 71.4% PLAN vs 60.1%, et 30 742
   plans vs 1 711 (x18 plans).
2. **Largement plus de candidats plans accessibles** : pour h7-h9 reunis,
   Ctopo donne 39 823 plans vs 2 379 pour C3 (x17).
3. **Nouveau** par rapport a la litterature : la litterature des benzenoides
   decrit principalement le **bord** (zigzag, cove, bay, deep bay) ; Ctopo
   combine un descripteur **bord-dual** (motif rayon-2) avec un descripteur
   **bulk-dual** (n_peri) sur des **non-benzenoides 5/6/7**.
4. **Transferable** : c'est un filtre a posteriori, applicable en quelques
   secondes a n'importe quelle base C1, y compris pour h10/h11 sans relancer
   xTB.
5. **Sur h6-h8, Ctopo n'est PAS strictement meilleure que C3 en purete**, mais
   donne toujours beaucoup plus de plans en absolu.

---

## 5. Limites identifiees

1. **Validation initiale par filtre a posteriori sur les sols C1** : le %PLAN
   est mesure sur les sols C1 deja validees par xTB qui satisfont le predicat
   (rayon-2 + squelette). Un run xTB ciblant directement les sols generees
   par la contrainte CSP Ctopo (Phase E) confirmerait independamment ce %PLAN
   sans passer par C1, mais n'a pas encore ete realise sur tout h9.
2. **h6-h8 : C3 reste imbattable en purete** (97% vs 87%). Ctopo n'est
   superieure que sur h9.
3. **L'angle max plafonne a 89-90° sur h7+** : meme Ctopo garde des outliers.
   Mais la mediane chute fortement (h9 : C1 = 19.8°, Ctopo = 0.4°). C'est la
   distribution qui compte, pas le maximum.
4. **Le pre-check n_peri >= 4 est un filtre sur le SQUELETTE, pas sur
   l'affectation 5/6/7** : il s'applique avant le CSP (cf. `count_peri_atoms`
   dans `csp_solver/utils/model.py`). En revanche, la blacklist rayon-2 EST
   bien une contrainte CSP solveur exprimee sur les variables x_v (Phase E,
   juin 2026). Ce decoupage est volontaire : la topologie du squelette n'est
   pas exprimable comme contrainte sur l'affectation, donc on la traite en
   amont. Aucun benzenoide d'entree au n_peri insuffisant ne lancera de
   resolution CSP Ctopo.

---

## 6. Pistes pour la suite

- **Validation xTB de Ctopo** : lancer un run xTB sur l'ensemble des sols
  Ctopo h9 (43 k sols) pour confirmer le %PLAN de 71.4%.
- **Selection des squelettes h10/h11** : filtrer en amont les squelettes par
  `n_peri >= 3` avant generation CSP.
- **Encoder le rayon-2 comme contrainte solveur** : ajouter une table de
  voisinage rayon-2 dans PyCSP3. Probablement gros (10^5-10^6 tuples) mais
  applicable sur cluster.

---

## 7. Fichiers et scripts cles

| Domaine                       | Chemin                                         |
|-------------------------------|------------------------------------------------|
| Configs CSP                   | `csp_solver/final/configs.py`                       |
| det-opt xTB                   | `csp_solver/xtb/det_opt.py`                         |
| DB unifiee                    | `experiments/final/final_h3_h9.db`                  |
| Features rayon-2 + topologie  | `csp_solver/analysis/compute_combined_features.py`  |
| Materialisation Ctopo         | `csp_solver/analysis/materialize_ctopo.py`          |
| Analyse motifs bord (annexe)  | `csp_solver/analysis/extract_boundary_motifs.py`    |
| Viewer Flask                  | `viewer/server.py`                                  |
| Descriptions configs (front)  | `viewer/static/config_descriptions.js`              |
