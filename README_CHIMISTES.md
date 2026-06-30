# Designer de molécules non-benzénoïdes — guide d'utilisation

Cet outil permet de dessiner une grille d'hexagones, de générer automatiquement
des solutions (substitution de cycles 5/6/7), puis de visualiser chaque
solution en 3D avec plusieurs analyses chimiques (Kekulé, RBO, Clar, graphe
dual).

## Installation (une seule fois)

1. Installer **Docker Desktop** : <https://www.docker.com/products/docker-desktop/>
   (Windows, Mac ou Linux). Suivre les instructions par défaut.
2. Démarrer Docker Desktop et attendre qu'il soit prêt (icône stable dans la
   barre des tâches).
3. Récupérer ce dossier (`Projet_Stage_CSP_M2_IMD`) sur votre machine.

## Démarrer l'outil

- **Windows** : double-cliquer sur `start.bat`
- **Mac / Linux** : double-cliquer sur `start.sh` (ou `./start.sh` dans un terminal)

Le premier démarrage prend plusieurs minutes (téléchargement et construction
de l'image). Les démarrages suivants sont rapides (quelques secondes).

Un navigateur s'ouvre automatiquement sur l'outil. Si ce n'est pas le cas,
ouvrez manuellement : <http://localhost:8765/designer>

## Arrêter l'outil

- **Windows** : double-cliquer sur `stop.bat`
- **Mac / Linux** : double-cliquer sur `stop.sh`

Vos molécules et résultats restent sauvegardés pour la prochaine fois.

## Utilisation

1. **Dessiner** une grille d'hexagones en cliquant sur les cases.
2. Choisir une **configuration** (preset C1 à Ctopo, ou personnalisée).
3. Choisir la **méthode** :
   - **Skip** : très rapide, géométrie approximative (pour explorer beaucoup
     d'idées rapidement).
   - **Validation xTB** : optimise réellement la géométrie 3D et vérifie la
     planarité (~5-15 secondes par solution). Recommandé pour les conclusions
     finales.
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

## Remarques importantes

- En mode **Skip**, la géométrie 3D est une approximation rapide qui peut
  parfois sembler déformée (un cycle qui semble être un hexagone alors que
  ce n'est pas le cas). Un bandeau d'avertissement jaune apparaît dans ce cas.
  Le **graphe dual** (à droite du viewer) montre toujours la vraie structure
  topologique. Pour une géométrie fiable, relancer en **Validation xTB**.
- Les molécules à 9 hexagones ou plus peuvent prendre plus de temps en
  validation xTB.

## En cas de problème

- **Le navigateur n'affiche rien** : vérifier que Docker Desktop est bien
  démarré, puis relancer `start.bat` / `start.sh`.
- **"Validation xTB" échoue tout le temps** : ouvrir un terminal et taper
  `docker compose logs designer` depuis ce dossier pour voir le détail de
  l'erreur (peut être transmis à l'équipe technique).
- **Mettre à jour l'outil** (nouvelle version reçue) : relancer simplement
  `start.bat` / `start.sh`, il reconstruit automatiquement si besoin. Vos
  molécules déjà créées sont conservées.
