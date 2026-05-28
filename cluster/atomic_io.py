"""
Ecriture atomique de fichiers (typiquement JSON) sur NFS.

Probleme cible : sur NFS, plusieurs scenarios peuvent corrompre un fichier
ecrit en une seule passe :
  - process killed/segfault au milieu d'un open(path, 'w') -> fichier tronque
  - lecteur concurrent qui voit le fichier a moitie ecrit
  - flock NFS notoirement instable (selon implem NFSv3 vs NFSv4 et serveur)

Solution : write tmp + os.replace.
  - L'ecriture se fait dans <path>.tmp.<pid> (meme dossier -> meme FS)
  - os.replace() est garanti atomique sur le meme FS (Windows + POSIX + NFS)
  - Le lecteur ne voit JAMAIS un fichier partiel : soit l'ancien, soit le nouveau

Limitations :
  - Atomique seulement si tmp et target sont sur le meme filesystem (sinon
    os.replace fait copy+delete). On respecte cette contrainte en mettant
    le tmp a cote de la cible.
  - Si 2 process ecrivent en concurrence, le dernier qui replace gagne.
    C'est OK pour notre usage : un seul process ecrit job_status.json par
    job (le worker qui le tient), un seul ecrit cluster_meta.json (finalize).
"""

import json
import os
from pathlib import Path


def write_atomic_json(path, data, indent=2, ensure_ascii=False):
    """Ecrit data en JSON dans path de maniere atomique.

    Args:
        path          : chemin du fichier de sortie (str ou Path)
        data          : objet serialisable JSON
        indent        : indentation (defaut 2)
        ensure_ascii  : si True, echappe les non-ASCII (defaut False = UTF-8)

    Comportement :
        1. Cree le dossier parent si besoin (mkdir -p).
        2. Ecrit dans <dir>/.<name>.tmp.<pid>
        3. Renomme atomiquement vers path final (os.replace).
        4. Sur erreur, le fichier final n'est pas modifie.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            # fsync pour forcer le flush sur NFS avant le rename. Sur cluster
            # avec serveur NFS chargé, sans ca, le rename peut "voir" un fichier
            # vide cote client meme si l'ecriture a ete acceptee.
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync peut echouer sur certains FS exotiques (pas critique)
                pass
        os.replace(str(tmp_path), str(path))
    except Exception:
        # Nettoyage du tmp si quelque chose a foire avant le replace
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
