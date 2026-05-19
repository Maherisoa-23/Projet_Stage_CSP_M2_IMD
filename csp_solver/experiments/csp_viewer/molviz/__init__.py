"""Module de visualisation 3D des molecules generees.

Composants :
  - bonds.py   : detection des liaisons C-C par distance, identification
                 des cycles (5/6/7 atomes).
  - kekule.py  : assign_kekule (un matching max) + enumerate_kekule (liste
                 canonique des matchings max, plafonnee). Identifie les
                 sites radicalaires (atomes non couverts).
  - rbo.py     : compute_rbo : bond orders par arete (Pauling) et Ring
                 Bond Order par cycle, etendu aux cycles 5 et 7. S'appuie
                 sur l'enumeration des Kekule.
  - clar.py    : enumerate_clar_covers : couvertures de Clar (sextets
                 aromatiques vertex-disjoints + matching du residu).
                 Enumeration exhaustive sur les 2^n_hex sous-ensembles
                 d'hexagones (trivial pour h3-h9).
  - api.py     : endpoints Flask /api/mol3d, /api/kekule_list, /api/rbo,
                 /api/clar_list.
  - static/    : molviz.js (modes Defaut / Kekule / RBO / Clar) et molviz.css.
"""
