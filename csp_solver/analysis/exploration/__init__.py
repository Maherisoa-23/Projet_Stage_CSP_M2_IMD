"""Scripts d'exploration data-mining ayant servi a identifier la
configuration Ctopo. Conserves pour tracabilite scientifique du memoire,
mais hors du pipeline canonique (csp_solver/analysis/).

Ordre indicatif d'execution (le memoire suit cette chronologie) :
  1. analyze_h9_top10                : analyse manuelle des 10 sols h9 les plus non-planes
  2. compute_c9_features + test_c9_virtual : tentative C9 (echec, conserve pour info)
  3. extract_boundary_motifs_h8 + rank_motifs_h8 : motifs de bord h8
  4. compare_motifs_h7h8h9           : validation universalite motifs h7/h8/h9
  5. test_config_motifs              : config C-motifs (echec, dominee par Pb1)
  6. analyze_radius2_motifs          : motifs rayon-2 dual (signal plus fort)
  7. analyze_skeleton_topology       : topologie du squelette (n_peri, shape)
  8. analyze_h8_c1_patterns + enrich_features_h8 + test_virtual_configs_h8 :
                                       configs virtuelles initiales (C4/C5/C8/C48, obsoletes)
  9. materialize_virtual_configs     : ancien materializer pour C4/C5/C8/C48
                                       (remplace par csp_solver/analysis/materialize_ctopo.py)
"""
