"""experiments_v2 : phase experimentale CSP avec contraintes additionnelles.

OBJECTIF
========
Augmenter le pourcentage de structures planes apres MD/xTB en ajoutant
au modele CSP de base des contraintes derivees des resultats empiriques
de analysis_v2 sur les 890 270 solutions h6-h9.

RESULTATS QUI MOTIVENT CES CONTRAINTES
======================================
1. Symetrie 5/7 -> planeite
   Quand |n_pent - n_hept| <= 1, %plan = 25-43%
   Quand |n_pent - n_hept| >= 2, %plan = 0-7%
   -> contrainte : limiter |n_pent - n_hept|

2. Pentagones en bord -> instabilite
   0 pent en bord = 59% plan
   1 pent en bord = 41% plan
   2 pent en bord = 27% plan
   3 pent en bord = 19% plan
   4 pent en bord = 15% plan
   5 pent en bord =  2% plan
   -> contrainte : limiter n_pent_at_boundary

3. Heptagones en bord -> instabilite plus douce
   1 hept en bord = 43% plan
   4 hept en bord = 24% plan
   -> contrainte : limiter n_hept_at_boundary (cap plus eleve)

ARCHITECTURE
============
- isole totalement de experiments/ (zero regression)
- reutilise utils/, reconstruction/, utils/validation/ (modules partages)
- nouveau model CSP : csp_model.py
- contraintes modulaires : constraints/{symmetry, boundary_caps, total_caps}.py
- entry CLI : main.py (drapeaux --sym K, --pb K, --hb K, --tot K)
- pipeline cluster dedie : cluster/{build_manifest, worker, dispatcher, finalize}.py
- nouvelle DB de resultats : db_v3.db (recompose par build_db_v3.py)

Toutes les contraintes sont OPTIONNELLES : sans drapeau, comportement
identique a main.py existant.
"""

__version__ = "0.1.0"
