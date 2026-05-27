"""
Tests des descripteurs : sanity check sur des molecules construites a la
main + 1 solution reelle de h6.

Usage :
    python -m experiments.viewer.analysis_v2.test_descriptors
"""

import sys
import sqlite3
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "experiments.viewer.analysis_v2"

from ..molviz.bonds import Atom, Cycle, MolGraph
from .descriptors.cycles import compute_cycle_descriptors
from .descriptors.boundary import compute_boundary_descriptors
from .descriptors.geometry import compute_geometry_descriptors
from .descriptors.electronic import compute_electronic_descriptors
from .compute_one import compute_all_descriptors
from ..analysis.loader import load_molgraph_from_solution


def _benzene_xy():
    """Benzene avec coords planes regulieres."""
    import math
    atoms = []
    for k in range(6):
        a = math.radians(60 * k)
        atoms.append(Atom("C", 1.4 * math.cos(a), 1.4 * math.sin(a), 0.0))
    bonds = [(i, (i + 1) % 6) for i in range(6)]
    return MolGraph(atoms=atoms, bonds=bonds, cycles=[Cycle(atoms=list(range(6)))])


def _phenanthrene_topo():
    """Phenanthrene : topologie seule, sans coords realistes (z=0)."""
    atoms = [Atom("C", 0.0, 0.0, 0.0) for _ in range(14)]
    bonds = [
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
        (2, 6), (6, 7), (7, 8), (8, 9), (9, 1),
        (7, 10), (10, 11), (11, 12), (12, 13), (13, 6),
    ]
    bonds = [(min(u, v), max(u, v)) for u, v in bonds]
    cycles = [
        Cycle(atoms=[0, 1, 2, 3, 4, 5]),
        Cycle(atoms=[1, 2, 6, 7, 8, 9]),
        Cycle(atoms=[6, 7, 10, 11, 12, 13]),
    ]
    return MolGraph(atoms=atoms, bonds=bonds, cycles=cycles)


def _azulene_topo():
    """Azulene : pentagone + heptagone fusionnes par arete (0-4)."""
    atoms = [Atom("C", 0.0, 0.0, 0.0) for _ in range(10)]
    bonds = [
        (0, 1), (1, 2), (2, 3), (3, 4), (0, 4),
        (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (0, 9),
    ]
    bonds = [(min(u, v), max(u, v)) for u, v in bonds]
    cycles = [
        Cycle(atoms=[0, 1, 2, 3, 4]),
        Cycle(atoms=[0, 4, 5, 6, 7, 8, 9]),
    ]
    return MolGraph(atoms=atoms, bonds=bonds, cycles=cycles)


def test_benzene():
    print("=== Benzene ===")
    mol = _benzene_xy()
    out = compute_all_descriptors(mol)
    expected = {
        "n_pent": 0, "n_hex": 1, "n_hept": 0,
        "n_cycles_total": 1,
        "n_azulene_units": 0,
        "n_stone_wales": 0,
        "n_3_fused_atoms": 0,
        "dual_n_components": 1,
        # Bordure : 6 atomes (tous), 6 aretes, 1 seul groupe taille 6
        "n_boundary_atoms": 6, "n_interior_atoms": 0,
        "boundary_length": 6,
        "n_groups_5plus": 1,
        # Geometrie : tout plat, buckling = 0
        "buckling_height": 0.0,
        "curvature_discrete_mean": 0.0,
        # Electronique : Clar=1
        "clar_number": 1, "n_clar_covers": 1,
        "n_kekule": 2, "n_radicals": 0,
        "cbo_available": 1,
    }
    ok = True
    for k, v in expected.items():
        got = out.get(k)
        if isinstance(v, float):
            match = (got is not None) and abs(got - v) < 1e-6
        else:
            match = got == v
        status = "OK   " if match else "ECHEC"
        if not match: ok = False
        print(f"  {status} {k:30s} = {got!r}  (attendu {v!r})")
    return ok


def test_phenanthrene():
    print("=== Phenanthrene (topo seul, geom triviale) ===")
    mol = _phenanthrene_topo()
    out = compute_all_descriptors(mol)
    expected = {
        "n_hex": 3, "n_pent": 0, "n_hept": 0,
        "n_66": 2,            # ring 1-ring 2 et ring 2-ring 3
        "n_3_fused_atoms": 0, # phenanthrene n'a pas d'atomes a 3 cycles
        "clar_number": 2, "n_clar_covers": 1,
        "n_kekule": 5,
        "dual_max_degree": 2,
    }
    ok = True
    for k, v in expected.items():
        got = out.get(k)
        match = got == v
        status = "OK   " if match else "ECHEC"
        if not match: ok = False
        print(f"  {status} {k:30s} = {got!r}  (attendu {v!r})")
    return ok


def test_azulene():
    print("=== Azulene (5+7 fusionnes) ===")
    mol = _azulene_topo()
    out = compute_all_descriptors(mol)
    expected = {
        "n_pent": 1, "n_hex": 0, "n_hept": 1,
        "n_57": 1,
        "n_azulene_units": 1,
        "n_stone_wales": 0,
        "clar_number": 0,  # pas d'hex donc Clar = 0
        "n_kekule": 2,
        "n_radicals": 0,
    }
    ok = True
    for k, v in expected.items():
        got = out.get(k)
        match = got == v
        status = "OK   " if match else "ECHEC"
        if not match: ok = False
        print(f"  {status} {k:30s} = {got!r}  (attendu {v!r})")
    return ok


def test_real_h6_solution():
    """Test sur 1 vraie solution de h6 lue depuis db_v2.xyz_files."""
    print("=== Solution reelle h6 (premiere disponible) ===")
    _HERE = Path(__file__).resolve().parent
    db_path = _HERE.parent / "db_v2.db"
    if not db_path.exists():
        print(f"  SKIP : db_v2.db introuvable ({db_path})")
        return True

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT h, config, mol, sol_idx, sol_dir "
        "FROM solutions WHERE h='h6' AND verdict='plan' LIMIT 1"
    ).fetchone()
    if row is None:
        print("  SKIP : aucune solution plan h6 trouvee")
        return True

    mol_graph = load_molgraph_from_solution(conn, row["sol_dir"])
    if mol_graph is None:
        print(f"  SKIP : xyz non chargeable pour {row['sol_dir']}")
        conn.close()
        return True

    out = compute_all_descriptors(mol_graph)
    conn.close()

    # Sanity checks souples (on ne connait pas les valeurs exactes,
    # mais on verifie la coherence interne)
    checks = [
        ("n_cycles_total > 0", out["n_cycles_total"] > 0),
        ("n_pent + n_hex + n_hept = n_cycles_total",
         out["n_pent"] + out["n_hex"] + out["n_hept"] == out["n_cycles_total"]),
        ("n_boundary_atoms > 0", out["n_boundary_atoms"] > 0),
        ("n_boundary + n_interior <= n_atoms",
         out["n_boundary_atoms"] + out["n_interior_atoms"] <= len(mol_graph.atoms)),
        ("buckling_height >= 0", out["buckling_height"] >= 0),
        ("0 <= plane_asymmetry <= 1",
         0 <= out["plane_asymmetry"] <= 1),
        ("max_angle_deg dans [0, 90]",
         0 <= out["max_angle_deg"] <= 90),
        ("aspect_ratio > 0 ou None",
         out["aspect_ratio"] is None or out["aspect_ratio"] > 0),
    ]
    ok = True
    for name, cond in checks:
        status = "OK   " if cond else "ECHEC"
        if not cond: ok = False
        print(f"  {status} {name}")

    print(f"  INFO h={row['h']} mol={row['mol']} sol={row['sol_idx']}")
    print(f"  INFO n_atoms={len(mol_graph.atoms)} n_cycles={out['n_cycles_total']}")
    print(f"  INFO n_pent={out['n_pent']} n_hex={out['n_hex']} n_hept={out['n_hept']}")
    print(f"  INFO clar={out['clar_number']} radicals={out['n_radicals']}")
    print(f"  INFO buckling={out['buckling_height']:.3f}A max_angle={out['max_angle_deg']:.2f}deg")
    print(f"  INFO curvature_mean={out['curvature_discrete_mean']:.2f}deg")
    print(f"  INFO irregularity={out['irregularity_param']}")
    return ok


def main():
    results = [
        test_benzene(),
        test_phenanthrene(),
        test_azulene(),
        test_real_h6_solution(),
    ]
    print()
    n_ok = sum(1 for r in results if r)
    print(f"{n_ok}/{len(results)} tests OK")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
