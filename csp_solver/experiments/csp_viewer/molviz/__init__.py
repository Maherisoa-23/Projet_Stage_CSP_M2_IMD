"""Module de visualisation 3D des molecules generees.

Composants :
  - bonds.py   : detection des liaisons C-C par distance, identification
                 des cycles (5/6/7 atomes). Helpers partages :
                 build_nx_graph(mol), bond_index_map(mol),
                 cycle_edge_indices(mol).
  - kekule.py  : assign_kekule (un matching max) + enumerate_kekule (liste
                 canonique des matchings max, plafonnee). Identifie les
                 sites radicalaires (atomes non couverts).
  - clar.py    : enumerate_clar_covers : couvertures de Clar (sextets
                 aromatiques vertex-disjoints + matching du residu).
                 Enumeration exhaustive sur les 2^n_hex sous-ensembles
                 d'hexagones (trivial pour h3-h9).
  - rbo.py     : compute_rbo : bond orders par arete (Pauling) et Ring
                 Bond Order par cycle, etendu aux cycles 5 et 7. S'appuie
                 sur l'enumeration des Kekule.
  - api.py     : endpoints Flask /api/mol3d, /api/kekule_list, /api/rbo,
                 /api/clar_list. Helpers internes _resolve_xyz_target et
                 _parse_max pour eviter le boilerplate.
  - static/    : molviz.js (modes Defaut / Kekule / RBO / Clar) et molviz.css.
                 Expose MolViz.open, MolViz.openSafe, MolViz.close.
"""
