# implementation_csp/ — Doc LaTeX modulaire

Documentation technique de l'implémentation CSP (PyCSP3 + ACE), reconstruction
3D, validation xTB / multi-runs / MD, et infrastructure d'expérimentation.

## Structure

```
implementation_csp/
├── main.tex                 ← document racine, compile avec pdflatex
├── preamble.tex             ← packages, palette, listings, boîtes, macros
├── titlepage.tex            ← page de titre
├── journal.tex              ← Journal des évolutions (chronologie)
├── references.tex           ← bibliographie
├── sections/                ← une section par fichier
│   ├── 01_introduction.tex
│   ├── 02_outils.tex
│   ├── 03_entree_dual.tex
│   ├── 04_pretraitement.tex
│   ├── 05_modele_csp.tex
│   ├── 06_format_sortie.tex
│   ├── 07_reconstruction.tex
│   ├── 08_multi_runs.tex          [\dateblock avril 2026]
│   ├── 09_validation_md.tex       [\dateblock 1er mai 2026]
│   ├── 10_infrastructure.tex
│   ├── 11_visualisation.tex       [3 \dateblock 1er mai 2026]
│   └── 12_architecture.tex
└── README.md                ← ce fichier
```

## Compiler

```bash
cd implementation_csp/
pdflatex main.tex            # 1ère passe (génère .aux, .toc)
pdflatex main.tex            # 2e passe (résout les références du sommaire)
```

Le PDF est `main.pdf` dans le même dossier.

## Workflow recommandé

### Modifier une section existante
Éditer directement `sections/NN_xxx.tex`. Ne pas toucher `main.tex`.

### Ajouter une nouvelle section
1. Créer `sections/NN_nom.tex` en copiant un fichier existant
2. Ajouter `\input{sections/NN_nom}` dans `main.tex` à l'endroit voulu
3. Si c'est un ajout postérieur à une version précédente, mettre `\dateblock{date}`
   juste après le `\section{...}` pour signaler quand le contenu a été ajouté
4. Mettre à jour la table chronologique dans `journal.tex`

### Ajouter un package ou une macro
Tout va dans `preamble.tex`. C'est le seul endroit centralisé pour les imports.

### Ajouter une référence bibliographique
Ajouter un `\bibitem{key}` dans `references.tex`. Citer ensuite avec `\cite{key}`
dans n'importe quelle section.

## Macros utiles définies dans preamble.tex

- `\GD` — graphe dual ($G_D$)
- `\Tn` — table de voisinage ($\mathcal{T}(n)$)
- `\bucketplane{}` / `\bucketnonplane{}` — pastilles colorées vert / noir
  (substituts aux emojis 🟢 / ⚫ qui plantent avec inputenc utf8)
- `\dateblock{date}` — étiquette « AJOUT DU date » pour signaler un contenu
  ajouté lors d'une révision

## Boîtes thématiques

- `\begin{remarque} ... \end{remarque}` — fond bleu pâle, encadré bleu
- `\begin{attention} ... \end{attention}` — fond orange pâle, encadré orange
- `\begin{definition}[Nom] ... \end{definition}` — théorème numéroté

## Styles de listings

- `\begin{lstlisting}` — Python (par défaut, syntaxe colorée)
- `\begin{lstlisting}[style=benzai]` — texte brut (commandes shell, formats
  de fichiers, structures de répertoires)

## Lien avec le projet

- Le code Python décrit est dans `csp_solver/` et `non_benzenoid_generator/`
  à la racine du projet (un niveau au-dessus de ce dossier).
- Les références aux fichiers utilisent des chemins relatifs depuis la racine
  du projet, ex. `csp_solver/main.py`, `non_benzenoid_generator/core/optimizer_md.py`.

## Versions

Voir le **Journal des évolutions** (`journal.tex`) pour l'historique des ajouts.
La date de dernière mise à jour est aussi en bas de la page de titre.
