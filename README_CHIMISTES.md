# Designer de molécules non-benzénoïdes — guide d'utilisation

Cet outil permet de dessiner une grille d'hexagones, de générer automatiquement
des solutions (substitution de cycles 5/6/7), puis de visualiser chaque
solution en 3D avec plusieurs analyses chimiques (Kekulé, RBO, Clar, graphe
dual).

## Installation (une seule fois)

1. Installer **Docker Desktop** : <https://www.docker.com/products/docker-desktop/>
   (Windows, Mac ou Linux). Suivre les instructions par défaut.
   - Sur Windows, l'installateur peut demander un **redémarrage du PC** :
     c'est normal (activation de WSL2), acceptez-le.
2. Après l'installation, **lancer Docker Desktop manuellement** une première
   fois et attendre que son icône (barre des tâches / menu barre en haut à
   droite sur Mac) devienne stable — ça peut prendre 1-2 minutes au premier
   démarrage. Vous n'aurez plus besoin de rouvrir cette fenêtre ensuite, les
   scripts ci-dessous s'en chargent.
3. Récupérer ce dossier (`Projet_Stage_CSP_M2_IMD`) sur votre machine.

Vous n'aurez besoin d'aucune autre installation (pas de Python, pas de xTB à
installer séparément — tout est inclus dans l'outil).

## Démarrer l'outil

- **Windows** : double-cliquer sur `start.bat`
- **Mac / Linux** : double-cliquer sur `start.sh` (ou `./start.sh` dans un terminal)

Le premier démarrage prend **plusieurs minutes** (téléchargement et
construction de l'image — normal, ne rien interrompre même si ça semble
long). Les démarrages suivants sont rapides (quelques secondes).

Un navigateur s'ouvre automatiquement sur la page d'accueil de l'outil. Si ce
n'est pas le cas, ouvrez manuellement : <http://localhost:8765/>

## Arrêter l'outil

- **Windows** : double-cliquer sur `stop.bat`
- **Mac / Linux** : double-cliquer sur `stop.sh`

Vos molécules et résultats restent sauvegardés pour la prochaine fois.

## Page d'accueil

La page d'accueil donne accès à tout :

- **✏️ Designer** — dessiner et lancer une génération
- **📁 Mes tests** — retrouver, renommer et regrouper vos jobs précédents en
  collections
- **🔗 Tables de voisinage** — consulter, dupliquer et personnaliser les
  contraintes de forme utilisées par le solveur (voir l'explication intégrée
  sur cette page, avec exemple)

## Explorer les résultats déjà calculés (optionnel)

En plus du Designer (dessiner ses propres molécules), l'outil peut afficher
un corpus de plusieurs millions de solutions déjà calculées pendant le
stage (tailles h3 à h9, plusieurs configurations de contraintes). Les
scripts d'intégration (`merge_corpus.py`, `integrate_corpus.bat`/`.sh`)
sont déjà dans ce dossier, à côté de `start.bat` — seule la donnée elle-même
(`corpus_only_for_chimiste.db`, ~11 Go) n'est **pas incluse via GitHub**
(trop volumineuse) et doit être reçue à part (clé USB) :

1. Récupérer `corpus_only_for_chimiste.db` — fourni à part — et le copier
   dans ce dossier, **à côté de `start.bat`**.
2. Démarrer l'outil si ce n'est pas déjà fait (`start.bat`/`start.sh`).
3. Double-cliquer sur `integrate_corpus.bat` (Windows) ou lancer
   `./integrate_corpus.sh` (Mac/Linux). Le script s'occupe de tout
   (détection automatique, copie, intégration, nettoyage, redémarrage) —
   ça prend plusieurs minutes, ne rien interrompre.
4. Une fois terminé, la carte **🔎 Explorer** de la page d'accueil (visible
   dès le départ, mais vide tant que cette étape n'est pas faite) donne
   accès aux solutions pré-calculées (filtres par taille, configuration,
   planéité).

Cette étape ne touche jamais aux molécules déjà créées dans le Designer —
elles restent toutes disponibles après l'intégration.

> Note : le README technique mentionne un fichier `final_h3_h9.db` — c'est
> la base de travail **interne** du stage (même corpus, format brut, côté
> développeur). Vous n'en avez pas besoin : `corpus_only_for_chimiste.db`
> est la seule base à récupérer, déjà préparée au bon format pour l'outil.

## Utilisation du Designer

1. **Dessiner** une grille d'hexagones en cliquant sur les cases.
2. Choisir une **configuration** (preset C1 à Ctopo, ou personnalisée), et
   éventuellement une **table de voisinage** alternative dans l'onglet
   Avancé si vous en avez créé une.
3. Choisir la **méthode** :
   - **Skip** : très rapide, géométrie approximative (pour explorer beaucoup
     d'idées rapidement).
   - **Validation xTB** : optimise réellement la géométrie 3D et vérifie la
     planarité (~5-15 secondes par solution ; instantané si une solution
     identique a déjà été calculée — badge "⚡ cache" dans ce cas).
     Recommandé pour les conclusions finales.
4. Cliquer sur **Générer**.
5. Cliquer sur le bouton **3D** d'une solution pour l'ouvrir dans le viewer
   interactif :
   - **Défaut** : structure 3D avec un assignment de doubles liaisons
   - **Radicalaires / Kekulé** : navigue parmi toutes les structures de Kekulé
   - **RBO** : indice d'aromaticité locale par cycle
   - **Clar** : couvertures maximales de sextets aromatiques
   - À droite : le **graphe dual**, une vue 2D schématique qui montre les
     vraies tailles de cycles de la solution (utile pour vérifier la
     cohérence si la géométrie 3D semble déformée en mode Skip).
6. **Comparer deux solutions côte à côte** (deux façons) :
   - Dans la liste des solutions d'un job : cocher exactement 2 solutions,
     puis cliquer sur **⚖ Comparer (2)**.
   - Depuis le viewer 3D : cliquer sur **📌 Comparer…** pour épingler la
     molécule affichée, ouvrir une autre solution, puis cliquer sur
     **⚖ Comparer**. Les deux vues 3D tournent ensemble (désactivable via
     la case « Synchroniser la rotation »).

## Remarques importantes

- En mode **Skip**, la géométrie 3D est une approximation rapide qui peut
  parfois sembler déformée (un cycle qui semble être un hexagone alors que
  ce n'est pas le cas). Un bandeau d'avertissement jaune apparaît dans ce cas.
  Le **graphe dual** (à droite du viewer) montre toujours la vraie structure
  topologique. Pour une géométrie fiable, relancer en **Validation xTB**.
- Les molécules à 9 hexagones ou plus peuvent prendre plus de temps en
  validation xTB.

## En cas de problème

- **`start.bat`/`start.sh` affiche "Docker n'est pas installé ou n'est pas
  démarré"** : ouvrez l'application Docker Desktop elle-même, attendez que
  son icône soit stable (pas de sablier/animation), puis relancez le script.
  C'est l'erreur la plus fréquente et elle se résout toujours ainsi.
- **Le navigateur n'affiche rien / "Ce site est inaccessible"** : le premier
  démarrage peut prendre plusieurs minutes, patientez puis rafraîchissez la
  page. Si ça persiste après 5 minutes, vérifiez que Docker Desktop est bien
  démarré et relancez `start.bat` / `start.sh`.
- **Rien ne se passe / erreur de port** : un autre programme utilise peut-être
  déjà le port 8765 sur votre machine. Fermez les autres outils similaires,
  ou contactez l'équipe technique pour changer le port.
- **"Validation xTB" échoue tout le temps** : ouvrir un terminal et taper
  `docker compose logs designer` depuis ce dossier pour voir le détail de
  l'erreur (peut être transmis à l'équipe technique).
- **Mettre à jour l'outil** (nouvelle version reçue) : relancer simplement
  `start.bat` / `start.sh`, il reconstruit automatiquement si besoin. Vos
  molécules déjà créées sont conservées.

## Retours et bugs

Cette version est en phase de test. N'importe quel comportement bizarre,
message d'erreur, ou question mérite d'être signalé — mieux vaut un
signalement de trop que de découvrir un bug plus tard. Le plus utile pour
nous : une capture d'écran + ce que vous faisiez juste avant.
