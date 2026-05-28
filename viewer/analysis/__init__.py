"""Module d'analyse cross-data : planeite x topologie.

Distinct de molviz/ qui est focalise sur la visualisation interactive
d'UNE molecule. Ici on calcule les indicateurs topologiques
(n_kekule, n_radicals, clar_number, RBO agrege) pour toutes les
solutions de la DB et on les croise avec la planeite.

Composants :
  - schema.sql  : table topology_metrics (additif, ne touche pas l'existant)
  - loader.py   : extraction XYZ depuis db_v2.xyz_files
  - compute.py  : pipeline batch (CLI : python -m analysis.compute --h h6)
  - queries.py  : requetes SQL d'analyse (joins, stats, top-K)
  - plots.py    : generation SVG (pas de dep externe)
  - output/     : plots et CSV exports

Dependances : molviz/{bonds,kekule,rbo,clar}.py pour les fonctions de
calcul. Aucune dependance inverse (molviz n'importe pas analysis).
"""

__version__ = "1.0.0"
