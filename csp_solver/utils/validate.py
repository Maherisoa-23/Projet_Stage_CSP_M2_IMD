"""
Validation d'une molecule complete : xTB + test de planarite.

Ce module prend un fichier XYZ, l'optimise avec xTB, et teste
si la molecule est plane (angle max <= seuil).
"""

import sys
from pathlib import Path

# Ajouter le generateur au path pour que ses imports internes marchent
_gen_root = Path(__file__).parent.parent.parent / "non_benzenoid_generator"
_gen_str = str(_gen_root)
if _gen_str not in sys.path:
    sys.path.insert(0, _gen_str)

from core.optimizer import optimize_xtb, read_optimized_coords

# Import direct du module planarity par chemin (evite conflit avec utils/ local)
import importlib.util
_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_gen_root / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar


def validate_xyz(xyz_path, opt_path=None, threshold=10.0, opt_level="tight"):
    """Optimise un XYZ avec xTB et teste la planarite.

    Args:
        xyz_path: chemin du fichier XYZ a valider
        opt_path: chemin de sortie pour le XYZ optimise (defaut: *_opt.xyz)
        threshold: seuil de planarite en degres
        opt_level: niveau de convergence xTB

    Returns:
        dict avec les resultats
    """
    xyz_path = Path(xyz_path)
    if opt_path is None:
        opt_path = xyz_path.parent / f"{xyz_path.stem}_opt.xyz"

    result = {
        'xyz': str(xyz_path),
        'optimized': False,
        'planar': False,
        'angle_deg': 0.0,
        'message': '',
    }

    # Optimisation xTB
    success, msg = optimize_xtb(str(xyz_path), str(opt_path),
                                opt_level=opt_level)
    if not success:
        result['message'] = f'Echec xTB: {msg}'
        return result

    result['optimized'] = True

    # Test de planarite
    coords = read_optimized_coords(str(opt_path))
    if len(coords) >= 3:
        metrics = compute_planarity(coords)
        result['angle_deg'] = metrics['max_angle_deg']
        result['rmsd'] = metrics['rmsd_plane']
        result['height'] = metrics['height']
        result['planar'] = is_planar(metrics, threshold)

    status = "PLAN" if result['planar'] else f"NON PLAN ({result['angle_deg']:.1f} deg)"
    result['message'] = status
    return result
