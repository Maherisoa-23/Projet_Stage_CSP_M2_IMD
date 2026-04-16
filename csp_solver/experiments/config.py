"""
Configuration globale pour l'infrastructure d'experimentation.
"""

from pathlib import Path

# --- Chemins ---
EXPERIMENTS_ROOT = Path(__file__).parent
CSP_SOLVER_ROOT = EXPERIMENTS_ROOT.parent
PROJECT_ROOT = CSP_SOLVER_ROOT.parent

BENZENOIDS_DIR = EXPERIMENTS_ROOT / "benzenoids"
RESULTS_DIR = EXPERIMENTS_ROOT / "results"
LOGS_DIR = RESULTS_DIR / "logs"
DOCS_DIR = EXPERIMENTS_ROOT / "docs"

# --- Seuils de planarite ---
PLANARITY_ANGLE_THRESHOLD = 10.0  # degres, seuil du chimiste

# --- CSP solver ---
CSP_TIMEOUT = 60  # secondes, timeout ACE par defaut
XTB_OPT_LEVEL = "tight"

# --- BenzDB ---
BENZDB_URL = "https://benzenoids.lis-lab.fr"
BENZDB_MAX_H = 9  # max hexagones dans BenzDB

# --- Comptages attendus (these Varet 2022, table 3.7) ---
# Pour verification apres import BenzDB
EXPECTED_COUNTS = {
    1: 1,
    2: 1,
    3: 3,
    4: 7,
    5: 22,
    6: 81,
    7: 331,
    8: 1436,
    9: 6510,
}

# --- Solutions sauvegardees (JSON) ---
SOLUTIONS_DIR = RESULTS_DIR / "solutions"

# --- Fichiers de resultats ---
STRUCTURAL_CSV = RESULTS_DIR / "structural.csv"
# JSON : results/benzdb/h4/0-5-6-11.json (un fichier par benzenoide)
RESULTS_BENZDB_DIR = RESULTS_DIR / "benzdb"
# HTML : results/rapport_h4.html (un rapport par serie)
HTML_DIR = RESULTS_DIR
