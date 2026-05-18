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
  - api.py     : endpoints Flask /api/mol3d, /api/kekule_list, /api/rbo.
  - static/    : molviz.js (modes Defaut / Kekule / RBO) et molviz.css.
"""
