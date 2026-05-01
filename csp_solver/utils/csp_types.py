"""Structures de donnees typees pour le solveur CSP.

Ces dataclasses remplacent les dict heteroclites utilises auparavant
et permettent de tracer proprement les metadonnees (index, variant,
run_id, seed, etc.) qui seront necessaires pour les multi-runs xTB.

NB : ce module s'appelle csp_types.py (et non types.py) pour ne pas
masquer le module standard `types`. Sinon, lancer un script depuis
csp_solver/utils/ casse l'import de la stdlib (le _weakrefset interne
fait un `from types import GenericAlias` qui retombe sur ce fichier).

Utilisation :
    from utils.csp_types import CSPSolution, ValidationResult

    sol = CSPSolution(hex_assignments={0: 6, 1: 5, 2: 7}, index=1)
    print(sol.sizes_str)  # "6_5_7"
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


# ======================================================================
# CSP : solutions et contraintes
# ======================================================================

@dataclass
class CSPConstraints:
    """Configuration des contraintes CSP (flags de la ligne de commande)."""
    freeze_b2: bool = True                # C2 : geler si b(v)>=2 (--no-freeze pour desactiver)
    use_neighborhood_table: bool = True   # C3 : table de voisinage (--no-table pour desactiver)
    restrict_5_7_adjacency: bool = False  # C5 : adjacence 5-7 (--adj-57 pour activer)

    @classmethod
    def from_argv(cls, argv: list) -> "CSPConstraints":
        """Parse les flags depuis sys.argv."""
        return cls(
            freeze_b2=("--no-freeze" not in argv),
            use_neighborhood_table=("--no-table" not in argv),
            restrict_5_7_adjacency=("--adj-57" in argv),
        )

    def summary(self) -> str:
        """Resume textuel des contraintes actives."""
        active = ["C1", "C4"]
        if self.freeze_b2:
            active.append("C2")
        if self.use_neighborhood_table:
            active.append("C3")
        if self.restrict_5_7_adjacency:
            active.append("C5")
        return "+".join(active)


@dataclass
class CSPSolution:
    """Une solution du solveur CSP : assignation de tailles aux hexagones.

    Attributes
    ----------
    hex_assignments : dict {v_idx: taille 5/6/7}
    index           : numero de la solution (1-indexed pour affichage)
    variant_id      : index de la variante de bloc (pour hexagones multi-blocs)
    block_choices   : choix de bloc pour chaque hexagone multi-bloc
    """
    hex_assignments: Dict[int, int]
    index: int = 0
    variant_id: Optional[int] = None
    block_choices: Dict[int, int] = field(default_factory=dict)

    @property
    def sizes_str(self) -> str:
        """Retourne la chaine '6_5_7_6' (tailles dans l'ordre des hexagones)."""
        return "_".join(str(self.hex_assignments[v])
                        for v in sorted(self.hex_assignments))

    @property
    def n_carbons(self) -> int:
        """Nombre total de carbones (valable pour benzenoides : somme x_v)."""
        return sum(self.hex_assignments.values())

    def pretty(self) -> str:
        """Representation lisible : 'v0=6 v1=5 v2=7'."""
        return " ".join(f"v{v}={self.hex_assignments[v]}"
                        for v in sorted(self.hex_assignments))

    def to_dict(self) -> dict:
        """Serialisation pour JSON."""
        return {
            "index": self.index,
            "variant_id": self.variant_id,
            "hex_assignments": {str(k): v for k, v in self.hex_assignments.items()},
            "block_choices": {str(k): v for k, v in self.block_choices.items()},
            "sizes": self.sizes_str,
        }


# ======================================================================
# Validation : resultat d'un run xTB + test planarite
# ======================================================================

@dataclass
class ValidationResult:
    """Resultat d'une validation xTB + test de planarite pour UN run.

    Attributes
    ----------
    xyz_path      : fichier XYZ optimise (sortie)
    optimized     : xTB a converge (ou au moins produit un fichier)
    planar        : angle_deg <= seuil
    angle_deg     : deviation angulaire maximale au plan moyen
    rmsd_plane    : RMSD au plan moyen (Angstrom)
    height        : epaisseur totale (Angstrom)
    max_deviation : deviation max lineaire (Angstrom)
    xtb_level     : niveau de convergence xTB utilise
    seed          : seed de perturbation utilise (pour multi-runs)
    message       : statut humain ('OK', 'ECHEC xTB', etc.)
    """
    xyz_path: str = ""
    optimized: bool = False
    planar: bool = False
    angle_deg: float = 0.0
    rmsd_plane: float = 0.0
    height: float = 0.0
    max_deviation: float = 0.0
    xtb_level: str = "tight"
    seed: Optional[int] = None
    message: str = ""

    def to_dict(self) -> dict:
        """Serialisation pour JSON (compatible avec l'ancien format)."""
        return asdict(self)

    def to_legacy_dict(self) -> dict:
        """Format retrocompatible avec l'ancien code (cles : planar, angle_deg, ...)."""
        return {
            "xyz": self.xyz_path,
            "optimized": self.optimized,
            "planar": self.planar,
            "angle_deg": self.angle_deg,
            "rmsd": self.rmsd_plane,
            "height": self.height,
            "message": self.message,
        }


# ======================================================================
# Multi-runs : resultat agrege de N runs xTB pour une meme solution
# ======================================================================

@dataclass
class MultiRunResult:
    """Resultats agreges de N runs xTB pour une meme solution.

    Format aligne avec le `data.json` enrichi :
      n, planar_count, non_planar_count, planar_pct,
      angle_mean, angle_std, angle_min, angle_max,
      angles, classification
    """
    solution: CSPSolution
    runs: List[ValidationResult] = field(default_factory=list)
    n_attempted: int = 0   # nombre de runs lances (inclut les echecs)

    @property
    def n_successful(self) -> int:
        """Nombre de runs qui ont reussi (xTB a converge)."""
        return sum(1 for r in self.runs if r.optimized)

    @property
    def planar_count(self) -> int:
        return sum(1 for r in self.runs if r.optimized and r.planar)

    @property
    def non_planar_count(self) -> int:
        return sum(1 for r in self.runs if r.optimized and not r.planar)

    @property
    def planar_pct(self) -> float:
        n = self.n_successful
        return (100.0 * self.planar_count / n) if n > 0 else 0.0

    @property
    def angles(self) -> List[float]:
        return [r.angle_deg for r in self.runs if r.optimized]

    @property
    def angle_mean(self) -> float:
        a = self.angles
        return sum(a) / len(a) if a else 0.0

    @property
    def angle_std(self) -> float:
        a = self.angles
        if len(a) < 2:
            return 0.0
        m = self.angle_mean
        var = sum((x - m) ** 2 for x in a) / len(a)
        return var ** 0.5

    @property
    def angle_min(self) -> float:
        a = self.angles
        return min(a) if a else 0.0

    @property
    def angle_max(self) -> float:
        a = self.angles
        return max(a) if a else 0.0

    def classify(self,
                 always_planar_max_mean: float = 5.0,
                 mostly_planar_min_pct: float = 70.0,
                 mostly_planar_max_std: float = 3.0,
                 unstable_min_pct: float = 30.0,
                 unstable_max_pct: float = 70.0,
                 unstable_min_std: float = 5.0,
                 mostly_non_planar_max_pct: float = 30.0) -> str:
        """Classifie la stabilite inter-runs.

        Retourne une chaine parmi :
          'always_planar', 'mostly_planar', 'unstable',
          'mostly_non_planar', 'always_non_planar', 'ambiguous'
        """
        n = self.n_successful
        if n < 3:
            return "ambiguous"
        pct = self.planar_pct
        mean = self.angle_mean
        std = self.angle_std

        if pct == 100.0 and mean < always_planar_max_mean:
            return "always_planar"
        if pct == 0.0:
            return "always_non_planar"
        if pct >= mostly_planar_min_pct and std < mostly_planar_max_std:
            return "mostly_planar"
        if (unstable_min_pct <= pct <= unstable_max_pct) or std > unstable_min_std:
            return "unstable"
        if pct < mostly_non_planar_max_pct and pct > 0.0:
            return "mostly_non_planar"
        return "ambiguous"

    def to_runs_dict(self,
                     classification_params: Optional[dict] = None) -> dict:
        """Serialise au format `runs` du data.json enrichi."""
        cls_params = classification_params or {}
        return {
            "n": self.n_successful,
            "planar_count": self.planar_count,
            "non_planar_count": self.non_planar_count,
            "planar_pct": round(self.planar_pct, 1),
            "angle_mean": round(self.angle_mean, 3),
            "angle_std": round(self.angle_std, 3),
            "angle_min": round(self.angle_min, 3),
            "angle_max": round(self.angle_max, 3),
            "angles": [round(a, 3) for a in self.angles],
            "classification": self.classify(**cls_params),
        }
