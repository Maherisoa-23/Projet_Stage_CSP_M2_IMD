"""Filtre Huckel pour predire la planarite via les orbitales pi.

Theorie
-------
Pour un systeme conjugue de N atomes sp2 (carbones notre cas), Huckel donne :
   H_ij = alpha si i=j ; beta si lies ; 0 sinon
En unites reduites (alpha=0, beta=-1) :
   H = -A   ou A est la matrice d'adjacence du squelette C.
Diagonalisation -> N energies. Les N/2 plus basses sont occupees (peuplees par
les N electrons pi). HOMO = N/2-1, LUMO = N/2 en indexation 0.

L'observation cle (theoreme de Lieb sur les graphes bipartis,
generalisation aux non-bipartis empirique) : si HOMO-LUMO GAP est faible ou
nul, la mol est anti-aromatique / radical / open-shell -> elle se buckle
pour casser sa degenerescence (effet Jahn-Teller en symetrie 2D).

Empiriquement, sur les PAH classiques (benzene, naphtalene, ...), gap > 1.0|beta|.
Pour nos non-benzenoides, on s'attend a :
   gap > 0.5 -> probablement plan (aromatique stable)
   gap < 0.1 -> probablement non-plan (degenere / anti-aromatique)
   0.1-0.5  -> zone grise

Cette fonction est INDEPENDANTE de la geometrie 3D et tres rapide (~1 ms),
contrairement a MMFF qui depend de la perception de bonds. Elle voit
exactement les effets electroniques qui font defaut a MMFF.
"""

from __future__ import annotations

import numpy as np


# Distance maximale pour considerer 2 C comme lies (sp2 aromatic C-C ~ 1.42 A)
DEFAULT_BOND_CUTOFF = 1.6


def _parse_xyz_text(xyz_text: str):
    """Renvoie (symbols, coords). Filtrage hors atomes invalides."""
    lines = xyz_text.splitlines()
    if len(lines) < 3:
        return None, None
    try:
        n = int(lines[0].strip())
    except ValueError:
        return None, None
    syms, coords = [], []
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                syms.append(parts[0])
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                continue
    if not syms:
        return None, None
    return syms, np.array(coords, dtype=float)


def build_c_adjacency(symbols: list[str], coords: np.ndarray,
                       bond_cutoff: float = DEFAULT_BOND_CUTOFF) -> np.ndarray | None:
    """Construit la matrice d'adjacence du squelette C.

    Args:
        symbols     : liste d'elements ('C', 'H', ...)
        coords      : Nx3 array de positions
        bond_cutoff : distance max pour C-C bond (defaut 1.6 A)

    Returns:
        adjacency  : matrice Nc x Nc (Nc = nombre de C) ou None si <3 C
    """
    c_mask = np.array([s == "C" for s in symbols])
    c_coords = coords[c_mask]
    Nc = len(c_coords)
    if Nc < 3:
        return None
    # Distances pairwise
    diff = c_coords[:, None, :] - c_coords[None, :, :]
    dists = np.sqrt(np.sum(diff * diff, axis=2))
    adj = ((dists > 0.1) & (dists <= bond_cutoff)).astype(np.float64)
    # Symetrisation par securite
    adj = np.maximum(adj, adj.T)
    return adj


def huckel_orbitals(adjacency: np.ndarray) -> np.ndarray:
    """Eigenvalues de -A (matrice de Huckel en unites de beta).

    Les valeurs sont les energies des orbitales pi en unites de beta.
    Triees ascendant : les plus basses sont les orbitales liantes.
    """
    # H = -A en unites beta. Mais conventionnellement on rapporte
    # E/|beta| avec |beta| ~ 2.5 eV. Ici on garde l'unite beta.
    H = -adjacency
    eigvals = np.linalg.eigvalsh(H)
    return eigvals


def huckel_score(xyz_text: str,
                  bond_cutoff: float = DEFAULT_BOND_CUTOFF,
                  n_electrons: int | None = None) -> dict | None:
    """Calcule HOMO, LUMO, gap pour un xyz donne.

    Args:
        xyz_text     : contenu xyz brut (souvent source.xyz)
        bond_cutoff  : seuil distance C-C (A)
        n_electrons  : si None, suppose un electron pi par C (PAH neutre)

    Returns:
        dict {nc, n_electrons, homo, lumo, gap, predicted_planar}
        ou None si parsing/build a echoue.
    """
    syms, coords = _parse_xyz_text(xyz_text)
    if syms is None:
        return None
    adj = build_c_adjacency(syms, coords, bond_cutoff)
    if adj is None:
        return None
    Nc = len(adj)
    eigvals = huckel_orbitals(adj)

    # Nb d'electrons pi : par defaut 1 par C (PAH neutre)
    if n_electrons is None:
        n_electrons = Nc
    # Nb d'orbitales occupees (paire d'electrons par orbitale)
    n_occ = n_electrons // 2
    if n_occ <= 0 or n_occ >= Nc:
        # cas degenere
        return {
            "Nc": Nc, "n_electrons": n_electrons,
            "homo": None, "lumo": None, "gap": 0.0,
            "predicted_planar": False, "reason": "no_valid_homo_lumo",
        }

    # En convention triee ascendant : les plus basses sont occupees
    homo = float(eigvals[n_occ - 1])
    lumo = float(eigvals[n_occ])
    gap = lumo - homo

    # Heuristique de prediction : gap > 0.5 |beta| -> plan
    # (a calibrer empiriquement sur nos donnees)
    predicted_planar = gap >= 0.5

    return {
        "Nc": Nc,
        "n_electrons": n_electrons,
        "homo": homo,
        "lumo": lumo,
        "gap": gap,
        "predicted_planar": predicted_planar,
    }
