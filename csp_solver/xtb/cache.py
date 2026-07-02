"""Cache des resultats de validation xTB, indexe par (XYZ source, parametres).

Motivation : la reconstruction 3D (reconstruction/assembler.py) est
byte-deterministe (ordre des atomes/liaisons canonicalise par sorted()),
et le protocole d'optimisation det-opt (xtb/det_opt.py) est lui-meme
byte-deterministe (perturbation z structuree, pas de RNG, OMP=1/MKL=1).
Consequence : pour un meme fichier source.xyz et les memes parametres
(opt_level, amplitude, phase), le resultat xTB est garanti identique.

Deux jobs designer differents qui retombent sur la meme solution CSP
(meme graphe + meme substitution de cycles) produisent donc le meme
source.xyz -> on peut sauter l'appel xTB (le plus couteux du pipeline)
et reutiliser directement le resultat deja calcule.

Cle de cache : SHA-256 du contenu de source.xyz + opt_level + amplitude +
phase + mode de perturbation. Le seuil de planarite (threshold_deg)
N'EST PAS dans la cle : on cache l'angle diedre brut, le verdict
planar/non-planaire est redecide a la lecture avec le seuil courant
(cf. lookup_and_classify). Ainsi un changement de seuil plus tard ne
perd aucun hit de cache.

Table dediee dans la meme DB que les autres tables designer (db_all.db),
mais ce module ne depend PAS de viewer/ : il est appele depuis
csp_solver/reconstruction/pipeline.py, qui doit rester utilisable en
CLI pur (main.py) sans serveur Flask ni Zippers webapp.

API publique :
    init_cache_table(db_path)
    compute_cache_key(xyz_text, opt_level, perturb_params) -> str
    lookup(db_path, key) -> dict | None
    store(db_path, key, xyz_text, angle_deg, converged, source_job_id, source_sol_name)
"""

import hashlib
import sqlite3
from datetime import datetime
from typing import Dict, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS xtb_cache (
    cache_key       TEXT PRIMARY KEY,
    xyz_text        TEXT NOT NULL,
    angle_deg       REAL NOT NULL,
    converged       INTEGER NOT NULL,
    opt_level       TEXT,
    created_at      TEXT NOT NULL,
    source_job_id   TEXT,
    source_sol_name TEXT,
    hit_count       INTEGER NOT NULL DEFAULT 0
);
"""


def init_cache_table(db_path: str) -> None:
    """Cree la table xtb_cache si elle n'existe pas. Idempotent."""
    with sqlite3.connect(db_path, timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(_SCHEMA)
        conn.commit()


def compute_cache_key(xyz_text: str, opt_level: str,
                      perturb_params: Dict) -> str:
    """Hash SHA-256 de (XYZ source, parametres d'optimisation).

    Inclut uniquement les parametres qui influencent le resultat xTB
    (opt_level + la perturbation deterministe). Le seuil de planarite
    n'y figure pas volontairement (cf. docstring du module).
    """
    amplitude = perturb_params.get("amplitude", 0.05)
    phase = perturb_params.get("phase", 0.5)
    mode = perturb_params.get("mode", "structured")
    seed = perturb_params.get("seed", 42)
    payload = (
        f"{xyz_text}\n---\n"
        f"opt_level={opt_level}\n"
        f"amplitude={amplitude}\n"
        f"phase={phase}\n"
        f"mode={mode}\n"
        f"seed={seed}\n"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lookup(db_path: str, key: str) -> Optional[Dict]:
    """Cherche une entree de cache. Incremente hit_count si trouvee.

    Returns:
        dict avec 'xyz_text', 'angle_deg', 'converged' (bool), ou None
        si aucune entree ne correspond a cette cle.
    """
    with sqlite3.connect(db_path, timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT xyz_text, angle_deg, converged FROM xtb_cache "
            "WHERE cache_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE xtb_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (key,),
        )
        conn.commit()
    return {
        "xyz_text": row["xyz_text"],
        "angle_deg": row["angle_deg"],
        "converged": bool(row["converged"]),
    }


def store(db_path: str, key: str, xyz_text: str, angle_deg: float,
         converged: bool, source_job_id: Optional[str] = None,
         source_sol_name: Optional[str] = None,
         opt_level: Optional[str] = None) -> None:
    """Enregistre un resultat xTB dans le cache.

    INSERT OR IGNORE : si la cle existe deja (race entre deux jobs
    concurrents calculant la meme solution), on garde la premiere
    entree ecrite plutot que d'ecraser -- les deux resultats sont de
    toute facon identiques (calcul deterministe), donc aucune perte.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with sqlite3.connect(db_path, timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            "INSERT OR IGNORE INTO xtb_cache ("
            "  cache_key, xyz_text, angle_deg, converged, opt_level,"
            "  created_at, source_job_id, source_sol_name, hit_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (key, xyz_text, float(angle_deg), int(bool(converged)),
             opt_level, now, source_job_id, source_sol_name),
        )
        conn.commit()
