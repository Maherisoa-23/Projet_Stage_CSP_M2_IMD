# Documentation du projet

Ordre de lecture suggere :

1. **[memoire.pdf](memoire.pdf)** -- vue d'ensemble scientifique (resultat final).
2. **[PIPELINE.md](PIPELINE.md)** -- parcours d'un job (CSP -> reconstruction -> det-opt xTB).
3. **[CONTRAINTES.md](CONTRAINTES.md)** -- modele CSP (table de voisinage, Pb1, adj_57, tau_gb).
4. **[ARCHITECTURE_FINAL_RUN.md](ARCHITECTURE_FINAL_RUN.md)** -- orchestration du run cluster.
5. **[DESIGNER_CLUSTER_DB.md](DESIGNER_CLUSTER_DB.md)** -- designer interactif (mode cluster).
6. **[ANALYSE_ELECTRONIQUE.md](ANALYSE_ELECTRONIQUE.md)** -- Kekule / Clar / RBO dans le viewer.
7. **[experimentation.md](experimentation.md)** -- **synthese des resultats (C1/C2/C3/Ctopo)**.
8. **[experimentation_complete.md](experimentation_complete.md)** -- journal detaille de toutes les pistes explorees.

## Source LaTeX

- `memoire.tex` -- source du memoire (rendu PDF en `memoire.pdf`).

## Artefacts gitignored

- `captures/` -- captures 3D top-down generees par `scripts/figures/capture_motif_views.py`.
- `motifs_bord_h8.tex` + `motifs_bord_h8.pdf` -- annexe figures motifs (regenerable
  via `scripts/figures/gen_motifs_latex_with_images.py`).
