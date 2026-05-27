"""
Acces aux fichiers XYZ stockes dans db_v2.xyz_files (gzippes).

Convention de rel_path (cf ingest_xyz.py) :
  <sol_dir>/md_validation/md_final_opt.xyz

On lit ces fichiers depuis la table xyz_files de db_v2.db, on les
decompresse, et on construit le MolGraph via molviz.bonds.

Fallback filesystem (option) : si le xyz n'est pas en DB, on tente de
le lire depuis le projet (utile pendant la phase de migration ou
l'ingestion XYZ est en cours).
"""

import gzip
import sqlite3
from pathlib import Path
from typing import Optional

# Importe les helpers de molviz pour la construction du graphe.
# On evite tout import circulaire : molviz n'importe jamais analysis.
from ..molviz.bonds import MolGraph, build_mol_graph_from_text


_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent.parent


def xyz_relpath_for_solution(sol_dir: str) -> str:
    """Construit le rel_path du md_final_opt.xyz depuis le sol_dir.

    Convention identique a ingest_xyz.py : forward-slashes, sans leading /.
    """
    rel = sol_dir.replace("\\", "/").rstrip("/")
    return f"{rel}/md_validation/md_final_opt.xyz"


def load_xyz_text(conn: sqlite3.Connection,
                  rel_path: str,
                  fallback_filesystem: bool = True) -> Optional[str]:
    """Retourne le contenu texte du XYZ correspondant a rel_path.

    1. Cherche dans xyz_files (table embarquee, content_gz).
    2. Si absent et fallback_filesystem=True, tente filesystem.
    3. Retourne None si introuvable.
    """
    row = conn.execute(
        "SELECT content_gz FROM xyz_files WHERE rel_path = ?",
        (rel_path,),
    ).fetchone()
    if row is not None:
        try:
            return gzip.decompress(row[0]).decode("utf-8", errors="replace")
        except (OSError, EOFError):
            return None

    if not fallback_filesystem:
        return None

    fs_path = _PROJECT_ROOT / rel_path
    if not fs_path.exists():
        return None
    try:
        return fs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def load_molgraph_from_solution(conn: sqlite3.Connection,
                                sol_dir: str,
                                fallback_filesystem: bool = True
                                ) -> Optional[MolGraph]:
    """Charge le squelette carbone (MolGraph) d'une solution.

    Args:
        conn       : connexion SQLite ouverte sur db_v2.db
        sol_dir    : chemin relatif du sol_dir (= solutions.sol_dir)
        fallback_filesystem : si True, tente FS en cas d'echec DB

    Returns:
        MolGraph si on a pu charger et parser le xyz, None sinon.
        MolGraph peut avoir atoms vide si le parsing a echoue.
    """
    rel = xyz_relpath_for_solution(sol_dir)
    text = load_xyz_text(conn, rel, fallback_filesystem=fallback_filesystem)
    if text is None:
        return None
    mol = build_mol_graph_from_text(text)
    if not mol.atoms:
        return None
    return mol
