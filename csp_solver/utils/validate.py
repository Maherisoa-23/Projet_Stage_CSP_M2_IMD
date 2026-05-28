"""
Validation d'une molecule complete : xTB + test de planarite.

Ce module prend un fichier XYZ, l'optimise avec xTB, et teste
si la molecule est plane (angle max <= seuil).
"""

from pathlib import Path

from csp_solver.xtb.optimizer import optimize_xtb, read_optimized_coords
from csp_solver.planarity.pca import compute_planarity, is_planar


def test_planarity_from_xyz(xyz_path, threshold=10.0):
    """Lit un XYZ deja optimise et teste sa planarite (ACP + seuil).

    Helper independant : utile pour tester la planarite d'une geometrie
    sans la re-optimiser. Utilise par les strategies multi-runs (apres
    --opt) et MD (apres --md + --opt).

    Returns:
        dict avec les cles 'planar', 'angle_deg', 'rmsd', 'height'.
        Si moins de 3 atomes, retourne planar=False et angle 0.
    """
    coords = read_optimized_coords(str(xyz_path))
    if len(coords) < 3:
        return {'planar': False, 'angle_deg': 0.0, 'rmsd': 0.0, 'height': 0.0}
    metrics = compute_planarity(coords)
    return {
        'planar': is_planar(metrics, threshold),
        'angle_deg': metrics['max_angle_deg'],
        'rmsd': metrics['rmsd_plane'],
        'height': metrics['height'],
    }


def validate_xyz(xyz_path, opt_path=None, threshold=10.0, opt_level="tight", seed=None):
    """Optimise un XYZ avec xTB (--opt) et teste la planarite.

    Strategy "multi-runs" : passe par optimize_xtb (un run --opt avec
    perturbation aleatoire en z) puis test ACP de la geometrie obtenue.

    Args:
        xyz_path: chemin du fichier XYZ a valider
        opt_path: chemin de sortie pour le XYZ optimise (defaut: *_opt.xyz)
        threshold: seuil de planarite en degres
        opt_level: niveau de convergence xTB
        seed: seed du generateur de perturbation (deterministe si fourni)

    Returns:
        dict avec 'optimized', 'planar', 'angle_deg', 'rmsd', 'height', 'message'.
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
                                opt_level=opt_level, seed=seed)
    if not success:
        result['message'] = f'Echec xTB: {msg}'
        return result

    result['optimized'] = True

    # Test de planarite (helper partage)
    plan = test_planarity_from_xyz(str(opt_path), threshold)
    result.update(plan)

    status = "PLAN" if result['planar'] else f"NON PLAN ({result['angle_deg']:.1f} deg)"
    result['message'] = status
    return result
