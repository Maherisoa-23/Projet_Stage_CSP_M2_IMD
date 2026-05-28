#!/usr/bin/env python
"""Point d'entree Flask du projet (option C, mai 2026).

Lance le viewer + designer sur le port choisi. Wrapper one-liner sur
viewer/server.py pour rendre l'entry-point visible a la racine.

Usage :
    python server.py [--db DB_PATH] [--host HOST] [--port PORT]

Defaults :
    --db    experiments/v1/db_v2.db   (base la plus complete : h6..h9 + designer_jobs)
    --host  127.0.0.1
    --port  8765

URLs :
    http://127.0.0.1:8765/           viewer principal
    http://127.0.0.1:8765/designer    interface dessin de benzenoide + presets CSP
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
# Ajout du dossier viewer/ au path pour que server.py s'importe comme module
sys.path.insert(0, str(_PROJECT_ROOT / "viewer"))

# Default DB si non fourni
if "--db" not in sys.argv:
    default_db = _PROJECT_ROOT / "experiments" / "v1" / "db_v2.db"
    sys.argv.extend(["--db", str(default_db)])

# Delegue au server.py du package viewer
import server as viewer_server  # type: ignore  # noqa: E402

if __name__ == "__main__":
    viewer_server.main()
