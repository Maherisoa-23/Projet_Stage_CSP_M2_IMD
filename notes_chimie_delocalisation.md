# Notes chimie — délocalisation, Kekulé, Clar, RBO, radicaux

Synthèse de l'éclaircissement post-réunion avec Denis et Yannick (15 mai 2026).
Objectif : poser le cadre conceptuel avant d'implémenter les fonctionnalités d'analyse électronique sur les structures 5/7.

---

## 1. La délocalisation, c'est quoi exactement

Dans un benzène, chaque carbone porte un électron π (le 4ème électron de valence, qui n'est pas engagé dans une liaison σ simple). Si on regarde une structure de Kekulé figée (3 doubles alternées), on pourrait croire que les 6 électrons π sont « rangés » par paires sur 3 liaisons précises. **Mais en réalité, ils ne sont pas attachés à une liaison** : ils tournent en continu autour du cycle. C'est ça la délocalisation. Les deux structures de Kekulé du benzène ne sont pas deux états distincts, ce sont deux **représentations limites** d'une même réalité physique où les électrons sont étalés.

Plus il y a de structures de Kekulé possibles pour une molécule, plus les électrons ont de « routes » disponibles → plus la délocalisation est étendue → plus la molécule est stable et aromatique.

---

## 2. Les ronds de Clar : où la délocalisation est *localisée*

Observation de Clar (1972) : dans certains hexagones, les **3 liaisons doubles sont toutes à l'intérieur** de l'hexagone (jamais partagées avec un voisin). Dans ce cas, les 6 électrons π de l'hexagone forment un **sextet aromatique fermé** — ils tournent uniquement dans cet hexagone, indépendamment du reste.

Concrètement : dans un sextet de Clar, les 3 doubles peuvent permuter entre les 6 arêtes de l'hexagone sans rien casser ailleurs. C'est ce que les chimistes appellent « les électrons se déplacent d'une arête à une autre ».

**Pourquoi maximiser le nombre de ronds de Clar ?** Chaque rond identifie une zone de délocalisation **autonome et stable**. Une molécule avec beaucoup de sextets de Clar = molécule très stable, avec des « îlots » d'aromaticité bien définis. C'est la règle de Clar : la structure de référence est celle qui maximise le nombre de ronds.

Subtilité : une molécule peut avoir **plusieurs couvertures de Clar maximales** (plusieurs façons distinctes d'atteindre le max). Le nombre de couvertures de Clar et leur géométrie portent aussi de l'information.

---

## 3. RBO : la version probabiliste

Le **Ring Bond Order** est un indicateur agrégé, pas lié à une couverture de Clar particulière.

Pour un hexagone :

```
RBO(hex) = Σ (bond order de ses 6 arêtes)
bond order(arête) = fraction des Kekulé où cette arête est double
```

Valeur entre 0 et 3. Interprétation intuitive : **fréquence à laquelle l'hexagone « ressemble » à un sextet aromatique** sur l'ensemble des Kekulé.

Pas exactement un Clar maximal, mais très corrélé. Un hexagone avec RBO proche de 3 = aromatique de manière robuste. RBO faible = électrons rarement présents → soit zone localisée, soit zone radicalaire.

À clarifier avec les chimistes : ils ont mentionné une variante « comme RBO mais sur la structure de Clar max ». Probablement un RBO pondéré uniquement sur les Kekulé compatibles avec une couverture de Clar maximale. Calcul facile si on a déjà toutes les Kekulé.

---

## 4. Électrons radicalaires

Un **électron radicalaire** = électron π non apparié dans la couverture de Clar (le carbone porteur n'est ni dans une double, ni dans un rond).

Deux régimes intéressants chimiquement :

- **Molécule avec beaucoup de radicaux stables** : magnétisme moléculaire, stockage d'information (cf. Allouche 2017), polarité, réactivité.
- **Molécule sans radical + beaucoup de Clar** : très stable, transport de charge, propriétés optoélectroniques.

Les deux extrêmes sont intéressants. Les chimistes nous ont confirmé : « ça peut aller dans les deux sens ».

---

## 5. Et les cycles 5/7 dans tout ça (le point central pour notre stage)

C'est là que notre travail diffère des benzénoïdes purs. La règle de Clar nécessite **6 électrons** par sextet (règle 4n+2 avec n=1). Donc :

- **Pentagone** : 5 carbones → 5 électrons π potentiels → ne peut pas former un sextet.
- **Heptagone** : 7 carbones → 7 électrons → en surnombre pour un sextet.

Conséquences :

- **Sur un pentagone**, un des carbones va naturellement porter un électron non apparié (ou un carbone partagé avec un voisin « absorbe » la parité). Donc les pentagones favorisent l'apparition de **radicaux locaux**.
- **Sur un heptagone**, inverse : un électron « en trop », ce qui pousse aussi à des réorganisations radicalaires sur les voisins.
- Une molécule mixte 5/6/7 peut quand même avoir des Kekulé valides (couplages parfaits), juste avec des sites radicalaires forcés à certains endroits. Et certains de ses hexagones peuvent porter des sextets de Clar.

**Hypothèse de travail** : nos structures 5/7 sont **naturellement candidates pour de la chimie radicalaire**, parce que la parité impaire des cycles 5/7 force des électrons à se localiser. C'est probablement ce qui intéresse les chimistes — pas la stabilité aromatique stricte, mais le fait que ces structures **produisent automatiquement des radicaux** dont on peut étudier la localisation et la stabilité.

---

## 6. Pistes concrètes sur le corpus h3-h9

Sur les 928 k structures de h9 (dont 211 k planes), on peut :

1. **Compter les Kekulé** de chaque structure (méthode de Rispoli, polynomial → faisable sur tout le corpus).
2. **Calculer les couvertures de Clar** et le nombre de Clar max. Identifier les structures où on place beaucoup de sextets malgré la présence de 5/7.
3. **Calculer les RBO** par cycle. La méthode RBO de BenzAI fonctionne pour les hexagones — à étendre aux cycles 5 et 7 (un « cycle bond order » général).
4. **Identifier les sites radicalaires** : carbones jamais couverts par une liaison double dans aucune Kekulé. Cartographier où ils tombent (pentagones ? heptagones ? hexagones adjacents ?).
5. **Croiser avec la géométrie** : est-ce que les structures planes (faible `max_angle_deg`) sont aussi celles qui ont beaucoup de Clar / peu de radicaux ? Ou indépendant ?

Le point 5 est probablement la première étude à tenter : il met en relation **ce que nous avons déjà calculé (planéité)** avec **ce que les chimistes veulent (délocalisation / radicaux)**. Un coefficient de corrélation entre `max_angle_deg` et nombre de radicaux donnerait déjà un résultat exploitable.

---

## 7. Vocabulaire : Kekulé vs Radicalaire (notre convention)

Dans le strict sens chimique, une **structure de Kekulé** est une assignation de doubles liaisons telle que **chaque carbone participe à exactement une double**. Mathématiquement = un *couplage parfait* du graphe carbone.

Si la molécule a un nombre **impair** de carbones (typique 5/7 par parité), ou si sa topologie force des électrons non appariés (cas « concealed non-Kekuléan »), aucun couplage parfait n'existe → **pas de Kekulé au sens strict**.

Pour ces molécules, on parle de **configurations radicalaires** : on place autant de doubles que possible (matching maximum), et les carbones non couverts sont des **sites radicalaires** (électron π non apparié).

### Convention dans nos outils (BenzAI / molviz / docs)

| Cas | Nombre de radicaux | Terme utilisé |
|---|---|---|
| Molécule admettant un couplage parfait | 0 | **Structures de Kekulé** |
| Molécule sans couplage parfait | > 0 | **Configurations radicalaires** |

L'algorithme sous-jacent (`enumerate_kekule`) est le même dans les deux cas — il énumère les matchings de cardinalité maximum du graphe carbone. Seul le **nom affiché** change selon le cas, pour ne pas abuser du terme « Kekulé » quand des radicaux sont présents.

Dans l'interface du viewer 3D :
- La chip de mode s'appelle **« Kekulé »** quand `n_radicals == 0`, **« Radicalaires »** sinon.
- Une icône d'aide `ⓘ` apparaît à côté du label dans le second cas, avec une explication au survol.

Cette distinction n'est pas mathématiquement nécessaire (le même calcul fonctionne), mais elle reste fidèle au vocabulaire chimique : on n'appelle pas « Kekulé » ce qui ne peut pas l'être par construction.

---

## 8. Vocabulaire récap

| Terme | Sens court |
|---|---|
| Structure de Kekulé | Étiquetage des liaisons en simple/double tel que chaque C porte exactement 1 double. Équivalent à un couplage parfait. |
| Couverture de Clar | Factorisation d'une (ou plusieurs) Kekulé où certains hexagones portent un sextet aromatique (rond). Maximise le nombre de ronds. |
| Sextet de Clar / rond de Clar | Hexagone dont les 3 doubles sont toutes internes → 6 électrons π circulent dans l'hexagone seul. |
| Électron radicalaire | Électron π non apparié = carbone non couvert par une double ou un rond dans une couverture donnée. |
| RBO (Ring Bond Order) | Somme sur un cycle des fractions « cette liaison est-elle double » sur l'ensemble des Kekulé. |
| Nombre de Clar | Nombre maximal de ronds plaçables = mesure de stabilité aromatique d'ensemble. |
| Délocalisation | Étalement spatial des électrons π au-delà d'une liaison fixe. Plus de Kekulé = plus de délocalisation possible. |
