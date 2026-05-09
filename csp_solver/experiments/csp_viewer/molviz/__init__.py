"""Module de visualisation 3D des molecules generees.

Composants :
  - bonds.py   : detection des liaisons C-C par distance, identification
                 des cycles (5/6/7 atomes).
  - kekule.py  : matching maximum (Edmonds blossom) pour assigner les
                 doubles bonds + identification des sites radicalaires.
  - api.py     : endpoint Flask /api/mol3d sert un JSON consomme par 3Dmol.js
                 cote frontend.
  - static/    : molviz.js (wrapper 3Dmol.js) et molviz.css (modal viewer).
"""
