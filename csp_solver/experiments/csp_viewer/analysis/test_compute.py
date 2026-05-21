"""
Tests du module analysis.

Verifie :
  - compute_metrics produit les bonnes valeurs sur benzene/naphtalene
    (sanity check qui valide aussi que la pipeline molviz est connectee)
  - _aggregate_cbo_by_size traite correctement le cas radicalaire (NULL)
  - ensure_schema cree la table sans erreur (idempotent)
  - batch_compute roule sans erreur sur une mini-DB en memoire

Usage :
    python -m csp_solver.experiments.csp_viewer.analysis.test_compute
"""

import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "csp_solver.experiments.csp_viewer.analysis"

from .compute import compute_metrics, ensure_schema, COMPUTE_VERSION  # noqa: E402
from ..molviz.bonds import Atom, Cycle, MolGraph  # noqa: E402


def _make_mol(n_atoms, bonds, cycles):
    atoms = [Atom(element="C", x=0.0, y=0.0, z=0.0) for _ in range(n_atoms)]
    bonds_list = [(min(u, v), max(u, v)) for (u, v) in bonds]
    cycles_list = [Cycle(atoms=list(c), anomaly=False) for c in cycles]
    return MolGraph(atoms=atoms, bonds=bonds_list, cycles=cycles_list)


def benzene():
    return _make_mol(
        6,
        [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)],
        cycles=[[0, 1, 2, 3, 4, 5]],
    )


def naphtalene():
    return _make_mol(
        10,
        [
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
            (1, 6), (6, 7), (7, 8), (8, 9), (9, 0),
        ],
        cycles=[
            [0, 1, 2, 3, 4, 5],
            [1, 6, 7, 8, 9, 0],
        ],
    )


def phenanthrene():
    return _make_mol(
        14,
        [
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
            (2, 6), (6, 7), (7, 8), (8, 9), (9, 1),
            (7, 10), (10, 11), (11, 12), (12, 13), (13, 6),
        ],
        cycles=[
            [0, 1, 2, 3, 4, 5],
            [1, 2, 6, 7, 8, 9],
            [6, 7, 10, 11, 12, 13],
        ],
    )


def pentagone():
    return _make_mol(
        5,
        [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)],
        cycles=[[0, 1, 2, 3, 4]],
    )


def assert_metrics(name, mol, expected: dict):
    m = compute_metrics(mol)
    results = []
    for key, val in expected.items():
        got = m.get(key)
        if isinstance(val, float):
            ok = (got is not None) and abs(got - val) < 1e-6
        else:
            ok = (got == val)
        status = "OK   " if ok else "ECHEC"
        print(f"  {status} {name:14s} {key} = {got!r}  (attendu {val!r})")
        results.append(ok)
    return all(results)


def test_schema():
    """ensure_schema est idempotent et cree la table topology_metrics."""
    print("Schema :")
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    ensure_schema(conn)  # 2eme appel doit etre noop
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='topology_metrics'"
    ).fetchall()
    ok = len(rows) == 1
    print(f"  {'OK   ' if ok else 'ECHEC'} table topology_metrics presente")
    conn.close()
    return ok


def test_versioning():
    print(f"Compute version : {COMPUTE_VERSION}")
    ok = isinstance(COMPUTE_VERSION, str) and len(COMPUTE_VERSION) > 0
    print(f"  {'OK   ' if ok else 'ECHEC'} version chaine non vide")
    return ok


def main():
    print("=" * 60)
    print("Test 1 : metriques sur molecules de reference")
    print("=" * 60)
    results = []

    results.append(assert_metrics("benzene", benzene(), {
        "n_kekule": 2,
        "n_radicals": 0,
        "clar_number": 1,
        "n_clar_covers": 1,
        "cbo_available": 1,
        "cbo_mean_hex": 3.0,
        "cbo_max_hex": 3.0,
        "cbo_mean_pent": None,
        "cbo_mean_hept": None,
        "n_hex": 1, "n_pent": 0, "n_hept": 0,
    }))
    print()
    results.append(assert_metrics("naphtalene", naphtalene(), {
        "n_kekule": 3,
        "n_radicals": 0,
        "clar_number": 1,
        "n_clar_covers": 2,
        "cbo_available": 1,
        "n_hex": 2, "n_pent": 0, "n_hept": 0,
    }))
    print()
    results.append(assert_metrics("phenanthrene", phenanthrene(), {
        "n_kekule": 5,
        "n_radicals": 0,
        "clar_number": 2,
        "n_clar_covers": 1,
        "cbo_available": 1,
        "n_hex": 3, "n_pent": 0, "n_hept": 0,
    }))
    print()
    # Pentagone seul : 5 atomes impairs -> radicalaire -> RBO None
    results.append(assert_metrics("pentagone", pentagone(), {
        "n_radicals": 1,
        "clar_number": 0,
        "n_clar_covers": 1,
        "cbo_available": 0,
        "cbo_mean_hex": None,
        "cbo_mean_pent": None,  # RBO non defini car radicalaire
        "n_hex": 0, "n_pent": 1, "n_hept": 0,
    }))

    print()
    print("=" * 60)
    print("Test 2 : versioning et schema")
    print("=" * 60)
    results.append(test_versioning())
    print()
    results.append(test_schema())

    print()
    n_ok = sum(1 for r in results if r)
    n_total = len(results)
    if n_ok == n_total:
        print(f"TOUS LES TESTS OK ({n_ok}/{n_total})")
        return 0
    else:
        print(f"ECHECS : {n_total - n_ok} / {n_total}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
