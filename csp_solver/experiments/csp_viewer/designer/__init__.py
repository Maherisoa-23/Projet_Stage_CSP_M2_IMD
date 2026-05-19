"""Module designer : interface de dessin de benzenoides + lancement de jobs CSP.

Composants :
  - graph_io.py : conversion JSON canvas <-> format .graph (BenzAI DIMACS-like)
  - jobs.py     : gestion du cycle de vie des jobs (table designer_jobs en DB)
  - runner.py   : wrapper subprocess de csp_solver/main.py
  - api.py      : endpoints Flask (POST /run, GET /jobs/<id>, etc.)
  - static/     : designer.js, designer.css (canvas, UI)
"""
