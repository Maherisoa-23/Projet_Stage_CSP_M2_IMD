"""experiments_v3 : pipeline a etages pour generer principalement des structures planes.

MOTIVATION
==========
Les experiments_v2 ont montre que les contraintes CSP combinatoires seules
(sym/pb/hb) ne suffisent pas a depasser ~50% de planarite sur h7. La planarite
est une propriete *geometrique* (resultat d'une minimisation d'energie) que le
CSP, par construction, ne peut decider qu'imparfaitement.

L'approche v3 est un PIPELINE A ETAGES, chaque etage rejetant les candidats
qui ne survivront pas a l'etage suivant, par ordre de cout croissant :

  [1] CSP combinatoire (rapide)
        + contraintes v2 (sym/pb/hb)
        + nouvelle contrainte de Gauss-Bonnet local (interdit la
          concentration de courbure dans un voisinage)
       -> rejette les non-planaires "evidents"
  [2] Embedding MMFF + test plan PCA (10-50 ms)
       -> rejette les non-planaires geometriques
  [3] xTB final, seulement sur les survivants
       -> validation chimique haute fidelite

GAIN ATTENDU
============
Pour 1000 candidats CSP :
  - avant : 1000 x xTB ~ 17 h
  - apres : 1000 x MMFF + ~150 x xTB ~ 2.5 h  (memes plans en sortie)

PHASE ACTUELLE : VALIDATION DE MMFF COMME ORACLE
================================================
Avant de tout cabler, on doit verifier que MMFF predit bien la planarite que
xTB donnerait. Procedure (validate_mmff.py) :
  - echantillonner N solutions deja calculees (plan + non_plan) dans db_v2.db
  - pour chacune : reconstruire le Mol RDKit, MMFF embed+optimize, test PCA
  - matrice de confusion MMFF-plan vs verdict xTB
Si l'accord >= 90%, on continue le pipeline complet.
Si < 80%, retour discussion (Huckel ? GNN ? autre).

ARCHITECTURE
============
- isole de experiments/ et experiments_v2/
- mmff_oracle.py    : MMFF embed + planarite (sans dependance projet)
- validate_mmff.py  : pipeline validation contre db_v2.db (sortie CSV/console)
- (plus tard)
    curvature_helper.py        : Gauss-Bonnet discret local
    constraints/local_curvature.py
    csp_model.py
    configs.py
    main.py
    db_helpers.py / run_one_job.py / cluster/
"""

__version__ = "0.0.1"
