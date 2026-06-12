"""Parser des metriques xTB depuis stdout.

xTB ecrit ses metriques importantes (energie totale, gap HOMO-LUMO, temps
CPU/wall) dans le stdout standard. Le code csp_solver/xtb/md.py actuel
ne les extrait pas ; on le fait ici pour enrichir la DB Final.

Tous les parsers sont tolerants : si une ligne attendue manque, on
retourne None pour ce champ (au lieu de lever).
"""

import re
from typing import Optional


# === Patterns regex sur stdout xTB ===

# ":: total energy   -42.345678  Eh   ::"
# ":: total energy             -73.345768109538 Eh    ::"
_RE_ENERGY = re.compile(
    r"::\s*total\s+energy\s+(-?\d+\.\d+)\s+Eh", re.IGNORECASE
)

# ":: HOMO-LUMO GAP   3.4567 eV ::"
# ":: HOMO-LUMO gap             3.456 eV    ::"
_RE_HOMO_LUMO = re.compile(
    r"::\s*HOMO-LUMO\s+(?:gap|GAP)\s+(-?\d+\.\d+)\s+eV", re.IGNORECASE
)

# "* wall-time:     0 d,  0 h,  0 min, 12.345 sec"
_RE_WALL_TIME = re.compile(
    r"\*\s*wall-time:\s*(\d+)\s*d,\s*(\d+)\s*h,\s*(\d+)\s*min,\s*([\d.]+)\s*sec",
    re.IGNORECASE,
)

# "*  cpu-time:     0 d,  0 h,  0 min, 12.345 sec"
_RE_CPU_TIME = re.compile(
    r"\*\s*cpu-time:\s*(\d+)\s*d,\s*(\d+)\s*h,\s*(\d+)\s*min,\s*([\d.]+)\s*sec",
    re.IGNORECASE,
)

_RE_CONVERGED = re.compile(r"GEOMETRY\s+OPTIMIZATION\s+CONVERGED", re.IGNORECASE)


def _time_to_seconds(d: str, h: str, m: str, s: str) -> float:
    return float(d) * 86400 + float(h) * 3600 + float(m) * 60 + float(s)


def parse_xtb_stdout(stdout: str) -> dict:
    """Extrait les metriques d'un stdout xTB complet.

    Retourne dict avec cles (None si non trouve) :
      energy_eh     : float, energie totale en Hartree
      homo_lumo_ev  : float, gap HOMO-LUMO en eV
      cpu_time_s    : float, temps CPU en secondes
      wall_time_s   : float, temps wall en secondes
      converged     : bool, True si GEOMETRY OPTIMIZATION CONVERGED present
    """
    out = {
        "energy_eh": None,
        "homo_lumo_ev": None,
        "cpu_time_s": None,
        "wall_time_s": None,
        "converged": False,
    }
    if not stdout:
        return out

    # On prend la DERNIERE occurence de chaque (final, apres optimisation)
    matches = list(_RE_ENERGY.finditer(stdout))
    if matches:
        try:
            out["energy_eh"] = float(matches[-1].group(1))
        except ValueError:
            pass

    matches = list(_RE_HOMO_LUMO.finditer(stdout))
    if matches:
        try:
            out["homo_lumo_ev"] = float(matches[-1].group(1))
        except ValueError:
            pass

    matches = list(_RE_WALL_TIME.finditer(stdout))
    if matches:
        try:
            d, h, m, s = matches[-1].groups()
            out["wall_time_s"] = _time_to_seconds(d, h, m, s)
        except ValueError:
            pass

    matches = list(_RE_CPU_TIME.finditer(stdout))
    if matches:
        try:
            d, h, m, s = matches[-1].groups()
            out["cpu_time_s"] = _time_to_seconds(d, h, m, s)
        except ValueError:
            pass

    out["converged"] = bool(_RE_CONVERGED.search(stdout))
    return out


def parse_xtb_logfile(path: str) -> dict:
    """Wrapper qui lit un fichier log xTB et retourne les metriques."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return parse_xtb_stdout(f.read())
    except FileNotFoundError:
        return parse_xtb_stdout("")
