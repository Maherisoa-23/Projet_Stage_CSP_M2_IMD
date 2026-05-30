"""Configuration centralisee du solveur CSP.

Tous les seuils, timeouts, chemins et parametres par defaut sont ici.
Importer avec :

    from config import CONFIG
    threshold = CONFIG.planarity_threshold_deg
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple


# ======================================================================
# Chemins du projet
# ======================================================================

_CSP_ROOT = Path(__file__).parent
_PROJECT_ROOT = _CSP_ROOT.parent


@dataclass(frozen=True)
class Paths:
    """Chemins absolus du projet."""
    project_root: Path = _PROJECT_ROOT
    csp_root: Path = _CSP_ROOT
    data_dir: Path = _CSP_ROOT / "data"
    output_dir: Path = _CSP_ROOT / "output"
    table_voisinage: Path = _CSP_ROOT / "data" / "table_voisinage.json"


# ======================================================================
# Parametres geometriques
# ======================================================================

@dataclass(frozen=True)
class GeometryConfig:
    """Constantes geometriques pour la reconstruction 3D."""
    bond_cc_length: float = 1.42          # Angstrom, distance C-C
    bond_ch_length: float = 1.08          # Angstrom, distance C-H
    z_plane_tolerance: float = 1e-6       # tolerance pour considerer z=0


# ======================================================================
# Parametres CSP et resolution
# ======================================================================

@dataclass(frozen=True)
class CSPConfig:
    """Parametres du solveur CSP."""
    ace_timeout_sec: int = 60             # timeout pour ACE (subprocess java)
    max_block_variants: int = 50          # limite combinatoire pour b(v)>=2
    cycle_sizes: Tuple[int, ...] = (5, 6, 7)


# ======================================================================
# Parametres xTB et test de planarite
# ======================================================================

@dataclass(frozen=True)
class XTBConfig:
    """Parametres d'optimisation xTB."""
    opt_level: str = "tight"              # niveau de convergence xTB
    timeout_sec: int = 300                # timeout par run xTB
    perturbation_amplitude: float = 0.1   # amplitude ±A du bruit z avant xTB


@dataclass(frozen=True)
class PlanarityConfig:
    """Parametres du test de planarite (ACP)."""
    threshold_deg: float = 10.0           # angle max acceptable (seuil du chimiste)
    min_atoms: int = 3                    # nb min d'atomes pour ACP


# ======================================================================
# Classification multi-runs (pour extension future)
# ======================================================================

@dataclass(frozen=True)
class ClassificationConfig:
    """Seuils pour la classification de stabilite inter-runs."""
    always_planar_max_mean: float = 5.0           # deg
    mostly_planar_min_pct: float = 70.0           # %
    mostly_planar_max_std: float = 3.0            # deg
    unstable_min_pct: float = 30.0                # %
    unstable_max_pct: float = 70.0                # %
    unstable_min_std: float = 5.0                 # deg
    mostly_non_planar_max_pct: float = 30.0       # %


# ======================================================================
# Configuration globale
# ======================================================================

@dataclass(frozen=True)
class Config:
    """Configuration globale du solveur CSP."""
    paths: Paths = field(default_factory=Paths)
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    csp: CSPConfig = field(default_factory=CSPConfig)
    xtb: XTBConfig = field(default_factory=XTBConfig)
    planarity: PlanarityConfig = field(default_factory=PlanarityConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)


# Instance globale (utiliser : `from config import CONFIG`)
CONFIG = Config()
