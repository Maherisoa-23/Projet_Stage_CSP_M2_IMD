"""Oracle MMFF : predit la planarite que xTB donnerait sur le meme graphe.

Workflow (un seul appel) :
  1. xyz_text -> Mol RDKit (perception de liaisons par distance)
  2. EmbedMolecule + MMFFOptimizeMolecule (geometrie d'equilibre mecanique)
  3. PCA sur les positions C/N/O et calcul de l'angle max au plan moyen
     (meme metrique que csp_solver/experiments_v2/db_helpers.py)

Strategie :
  - on parse l'xyz pour recuperer les atomes + positions
  - on essaie d'abord la perception RDKit (DetermineBonds)
  - en fallback (radicaux, valences impossibles), on construit le graphe
    nous-meme par distance (cutoff ~ 1.8 A pour C-C aromatique elargi)
    puis on passe en EmbedMolecule avec contraintes

L'API publique est : mmff_planarity(xyz_text, threshold_deg=10.0)
"""

from __future__ import annotations

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdDetermineBonds

# Suppress RDKit warnings (radicals, valence)
from rdkit import RDLogger
RDLogger.DisableLog("rdApp.*")


# ---------------- Parsing xyz ----------------

def _parse_xyz(xyz_text: str):
    """Renvoie (symbols, coords_array Nx3) ou (None, None)."""
    lines = xyz_text.splitlines()
    if len(lines) < 3:
        return None, None
    try:
        n = int(lines[0].strip())
    except ValueError:
        return None, None
    symbols = []
    coords = []
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            symbols.append(parts[0])
            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
        except ValueError:
            continue
    if len(symbols) != n:
        return None, None
    return symbols, np.array(coords, dtype=float)


# ---------------- PCA-planarite ----------------

def _planarity_metrics(coords: np.ndarray) -> dict | None:
    """Reproduit utils/planarity.py : angle max entre vecteur point-centroide
    et plan moyen ACP. Retourne aussi rmsd, height."""
    if len(coords) < 3:
        return None
    centroid = coords.mean(axis=0)
    centered = coords - centroid
    try:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    normal = vh[2]  # axe de plus petite variance
    dists = centered @ normal
    height = float(np.max(np.abs(dists)))
    rmsd = float(np.sqrt(np.mean(dists ** 2)))
    norms = np.linalg.norm(centered, axis=1)
    norms = np.where(norms > 1e-9, norms, 1e-9)
    sin_a = np.clip(np.abs(dists) / norms, 0, 1)
    angles_deg = np.degrees(np.arcsin(sin_a))
    return {
        "max_angle_deg": float(np.max(angles_deg)),
        "rmsd_plane": rmsd,
        "height": height,
    }


# ---------------- Build RDKit Mol (avec fallback) ----------------

def _mol_from_xyz_text(xyz_text: str) -> Chem.Mol | None:
    """Construit un Mol RDKit avec perception de bonds + bond orders.

    Strategie : MolFromXYZBlock puis rdDetermineBonds.DetermineBonds qui assigne
    aussi les ordres (necessaire pour que MMFF94 reconnaisse l'aromaticite).
    Essaye plusieurs charges (0, +1, -1) pour les radicaux.
    """
    try:
        mol = Chem.MolFromXYZBlock(xyz_text)
    except Exception:
        return None
    if mol is None:
        return None

    for charge in (0, 1, -1):
        try:
            m = Chem.RWMol(mol)
            rdDetermineBonds.DetermineBonds(m, charge=charge)
            return m.GetMol()
        except Exception:
            continue

    # Fallback : connectivite seule (single bonds), pour MMFF/UFF sans
    # information d'aromaticite -- moins fiable mais ne crashe pas
    try:
        m = Chem.RWMol(mol)
        rdDetermineBonds.DetermineConnectivity(m)
        return m.GetMol()
    except Exception:
        return None


def _mol_from_graph(symbols: list[str], coords: np.ndarray,
                    bond_cutoff: float = 1.8) -> Chem.Mol | None:
    """Fallback : construit un Mol avec bonds par distance (single par defaut).
    Suffit pour MMFF qui re-perce l'aromaticite via les angles/cycles."""
    n = len(symbols)
    rwmol = Chem.RWMol()
    for sym in symbols:
        rwmol.AddAtom(Chem.Atom(sym))
    # bonds par distance
    for i in range(n):
        for j in range(i + 1, n):
            d = float(np.linalg.norm(coords[i] - coords[j]))
            if d <= bond_cutoff:
                rwmol.AddBond(i, j, Chem.BondType.SINGLE)
    # injecter les coords comme conformer initial
    conf = Chem.Conformer(n)
    for i in range(n):
        conf.SetAtomPosition(i, (float(coords[i, 0]),
                                  float(coords[i, 1]),
                                  float(coords[i, 2])))
    rwmol.AddConformer(conf, assignId=True)
    mol = rwmol.GetMol()
    try:
        Chem.SanitizeMol(mol, sanitizeOps=Chem.SANITIZE_ALL ^
                        Chem.SANITIZE_SETAROMATICITY ^
                        Chem.SANITIZE_KEKULIZE ^
                        Chem.SANITIZE_PROPERTIES ^
                        Chem.SANITIZE_ADJUSTHS)
    except Exception:
        pass
    return mol


# ---------------- Optimisation MMFF ----------------

def _optimize_mmff(mol: Chem.Mol, max_iters: int = 500) -> tuple[bool, np.ndarray | None]:
    """Optimise par MMFF94 si possible, sinon UFF. Renvoie (success, coords)."""
    try:
        # MMFFOptimize a besoin que les types MMFF soient connus pour tous
        # les atomes. Pour des radicaux carbones (typiques non-benzenoides), ca
        # peut echouer => fallback UFF qui marche toujours.
        props = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94")
        if props is not None:
            ff = AllChem.MMFFGetMoleculeForceField(mol, props)
            if ff is not None:
                ff.Minimize(maxIts=max_iters)
                conf = mol.GetConformer()
                pos = np.array([list(conf.GetAtomPosition(i))
                                for i in range(mol.GetNumAtoms())])
                return True, pos
    except Exception:
        pass

    try:
        AllChem.UFFOptimizeMolecule(mol, maxIters=max_iters)
        conf = mol.GetConformer()
        pos = np.array([list(conf.GetAtomPosition(i))
                        for i in range(mol.GetNumAtoms())])
        return True, pos
    except Exception:
        return False, None


# ---------------- API publique ----------------

def _write_xyz_text(symbols: list[str], coords: np.ndarray,
                      comment: str = "") -> str:
    """Helper : formate symbols+coords en xyz texte (style standard)."""
    lines = [str(len(symbols)), comment]
    for s, (x, y, z) in zip(symbols, coords):
        lines.append(f"{s:<3s} {x:>16.10f} {y:>16.10f} {z:>16.10f}")
    return "\n".join(lines) + "\n"


def mmff_planarity_with_coords(
        xyz_text: str,
        threshold_deg: float = 10.0,
        randomize: bool = False,
        seed: int = 42,
) -> tuple[dict | None, str | None]:
    """Idem mmff_planarity, mais renvoie en plus le xyz MMFF-optimise (texte).

    Returns:
        (metrics_dict, opt_xyz_text)
        - metrics_dict est le meme dict que mmff_planarity (None si echec)
        - opt_xyz_text est l'xyz MMFF-optimise (None si MMFF a echoue)
    """
    symbols, coords = _parse_xyz(xyz_text)
    if symbols is None:
        return None, None

    mol = _mol_from_xyz_text(xyz_text)
    if mol is None:
        mol = _mol_from_graph(symbols, coords)
    if mol is None:
        return None, None

    if mol.GetNumConformers() == 0:
        try:
            params = AllChem.ETKDGv3()
            params.randomSeed = seed
            rc = AllChem.EmbedMolecule(mol, params)
            if rc < 0:
                return None, None
        except Exception:
            return None, None

    if randomize:
        rng = np.random.default_rng(seed)
        conf = mol.GetConformer()
        n = mol.GetNumAtoms()
        noise = rng.normal(0, 0.5, size=n)
        for i in range(n):
            p = conf.GetAtomPosition(i)
            conf.SetAtomPosition(i, (p.x, p.y, p.z + float(noise[i])))

    ok, opt_coords = _optimize_mmff(mol)
    if not ok or opt_coords is None:
        return None, None

    syms_full = [a.GetSymbol() for a in mol.GetAtoms()]
    heavy_mask = np.array([s != "H" for s in syms_full])
    metrics = _planarity_metrics(opt_coords[heavy_mask])
    if metrics is None:
        return None, None

    result = {
        "planar": metrics["max_angle_deg"] <= threshold_deg,
        "angle_deg": metrics["max_angle_deg"],
        "rmsd": metrics["rmsd_plane"],
        "height": metrics["height"],
        "ok": True,
    }
    opt_xyz = _write_xyz_text(syms_full, opt_coords, comment="MMFF94-optimized")
    return result, opt_xyz


def mmff_planarity(xyz_text: str,
                    threshold_deg: float = 10.0,
                    randomize: bool = False,
                    seed: int = 42) -> dict | None:
    """Predit la planarite d'une molecule donnee son xyz initial.

    Args:
        xyz_text       : contenu xyz brut (1ere ligne = N, 2eme = commentaire)
        threshold_deg  : seuil de l'angle max pour declarer 'plan'
        randomize      : si True, randomise la position initiale (test plus
                          severe : MMFF doit retrouver le plan depuis le bruit)
        seed           : reproductibilite (pour randomize=True ou EmbedMolecule)

    Returns:
        dict {planar(bool), angle_deg, rmsd, height, force_field, ok}
        ou None si tout echoue
    """
    symbols, coords = _parse_xyz(xyz_text)
    if symbols is None:
        return None

    # 1. Construire le Mol
    mol = _mol_from_xyz_text(xyz_text)
    if mol is None:
        mol = _mol_from_graph(symbols, coords)
    if mol is None:
        return None

    # 2. Si pas de conformer, embedder ; sinon partir des coords donnees
    if mol.GetNumConformers() == 0:
        try:
            params = AllChem.ETKDGv3()
            params.randomSeed = seed
            rc = AllChem.EmbedMolecule(mol, params)
            if rc < 0:
                return None
        except Exception:
            return None

    # 3. Si randomize : ajouter du bruit ~0.5 A en z pour tester si MMFF
    #    retrouve le plan depuis une geometrie buclee
    if randomize:
        rng = np.random.default_rng(seed)
        conf = mol.GetConformer()
        n = mol.GetNumAtoms()
        noise = rng.normal(0, 0.5, size=n)
        for i in range(n):
            p = conf.GetAtomPosition(i)
            conf.SetAtomPosition(i, (p.x, p.y, p.z + float(noise[i])))

    # 4. Optimiser
    ok, opt_coords = _optimize_mmff(mol)
    if not ok or opt_coords is None:
        return None

    # 5. Planarite PCA sur atomes lourds uniquement (cohere avec build_db)
    heavy_mask = np.array([s != "H" for s in symbols])
    metrics = _planarity_metrics(opt_coords[heavy_mask])
    if metrics is None:
        return None

    return {
        "planar": metrics["max_angle_deg"] <= threshold_deg,
        "angle_deg": metrics["max_angle_deg"],
        "rmsd": metrics["rmsd_plane"],
        "height": metrics["height"],
        "ok": True,
    }
