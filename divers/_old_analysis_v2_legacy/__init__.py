"""Etude topologie x geometrie x electronique sur h6-h9.

Package distinct de analysis/ (proto h6) et molviz/ (viewer 3D).
Aucun couplage : modifie uniquement la nouvelle table
`solution_descriptors`, ne touche pas aux tables existantes.

Composants :
  - schema.sql              : table solution_descriptors (~50 colonnes)
  - descriptors/            : un module par famille de descripteurs
      cycles.py             : compositions de cycles, fusions, motifs azulene/Stone-Wales
      boundary.py           : bordure (solo/duo/trio, irregularite, motifs 5/7)
      geometry.py           : courbure 3D, buckling, asymetrie, aspect ratio
      electronic.py         : agregat Kekule/Clar/RBO + radical localization
  - compute_one.py          : orchestrateur (calcule tous les descripteurs d'1 sol)
  - cluster/                : pipeline distribue (manifest, worker, finalize, dispatcher)
  - experiments/            : analyses croisees (un script par hypothese)
  - report/                 : generation HTML navigable

Dependances : reutilise molviz/{bonds,kekule,clar,rbo}.py pour la pipeline
existante. Aucune dep inverse (molviz n'importe pas analysis_v2).
"""

__version__ = "2.0.0"
