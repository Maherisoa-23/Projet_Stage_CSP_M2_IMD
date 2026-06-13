"""Pipeline d'analyse post-run : extraction de features topologiques sur
les solutions C1 done de la DB du run final, et materialisation de la
configuration Ctopo (recommandee dans doc/experimentation.md).

Ordre d'execution (apres run cluster final) :
  1. compute_adjacencies        : table sol_features (adj_55, adj_57, adj_77, n_sum)
  2. compute_combined_features  : table sol_combined_features (rayon-2 + topologie squelette)
  3. extract_boundary_motifs    : motifs de bord (annexe memoire, fenetres w=4 w=5)
  4. materialize_ctopo          : INSERT Ctopo dans tables solutions / molecules / configs
                                  (filtre post-DB equivalent a la contrainte CSP de Phase E)
  5. postprocess_clar_rbo       : ajoute colonnes Clar / RBO dans solutions

Voir doc/experimentation_complete.md pour le detail des features et leur
mecanisme.

Le sous-package exploration/ contient les scripts data-mining ayant servi
a identifier les blacklists / favors utilises par Ctopo. Ils ne sont pas
necessaires pour reproduire le pipeline final, mais conserves pour
tracabilite scientifique.
"""
