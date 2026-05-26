"""
Tests des couvertures de Clar (clar.enumerate_clar_covers).

Convention testee : Kekule-based (un hex est un sextet ssi 3 doubles dans
ses 6 aretes, doubles partagees autorisees). Voir docstring de clar.py.

Valeurs de reference calculees a la main :
  benzene       : Clar=1, 1 cover  (les 2 K donnent meme sextet set {hex0})
  naphtalene    : Clar=2, 1 cover  (K1 = (0,1)(2,3)(4,5)(6,7)(8,9) :
                                    les 2 hex ont 3 doubles, dont (0,1)
                                    partagee)
  anthracene    : Clar=2, 2 covers ({hex1,hex2} via K_A et {hex2,hex3}
                                    via K_C2a, NB. en utilisant la
                                    notation interne des Kekule)
  phenanthrene  : Clar=3, 1 cover  (K_A : les 3 hex en sextets simultanes,
                                    arete partagee (6,7) double pour
                                    hex2 ET hex3, idem (1,2) pour hex1
                                    ET hex2)
  pentagone     : Clar=0, 1 cover  (pas d'hex, residu avec 1 radical)

Usage :
    python -m csp_solver.experiments.csp_viewer.molviz.test_clar
"""

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "csp_solver.experiments.csp_viewer.molviz"

from csp_solver.experiments.csp_viewer.molviz.bonds import Atom, Cycle, MolGraph
from csp_solver.experiments.csp_viewer.molviz.clar import enumerate_clar_covers


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


def anthracene():
    return _make_mol(
        14,
        [
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
            (2, 6), (6, 7), (7, 8), (8, 9), (9, 1),
            (8, 10), (10, 11), (11, 12), (12, 13), (13, 7),
        ],
        cycles=[
            [0, 1, 2, 3, 4, 5],
            [1, 2, 6, 7, 8, 9],
            [7, 8, 10, 11, 12, 13],
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


def pentagone_seul():
    return _make_mol(
        5,
        [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)],
        cycles=[[0, 1, 2, 3, 4]],
    )


def assert_clar(name, mol, expected_clar, expected_n_covers):
    """Verifie le nombre de Clar et le nb de covers (apres dedup)."""
    covers, is_exact = enumerate_clar_covers(mol, max_count=1000)
    actual_clar = covers[0].n_sextets if covers else 0
    n_covers = len(covers)
    ok = (actual_clar == expected_clar) and (n_covers == expected_n_covers) and is_exact
    status = "OK   " if ok else "ECHEC"
    print(f"  {status} {name:14s} Clar={actual_clar} (attendu {expected_clar}), "
          f"{n_covers} covers (attendu {expected_n_covers}), is_exact={is_exact}")
    return ok


def assert_invariants(name, mol):
    """Verifie : sextets sont des hex, ont 3 doubles dans leurs aretes,
    toutes les covers ont meme score."""
    covers, _ = enumerate_clar_covers(mol, max_count=1000)
    if not covers:
        print(f"  SKIP  {name:14s} : aucune couverture")
        return True
    n_bonds = len(mol.bonds)
    same_score = len({c.n_sextets for c in covers}) == 1
    if not same_score:
        print(f"  ECHEC {name:14s} : scores differents")
        return False
    # Pre-calcul des aretes par cycle
    bond_idx = {tuple(sorted(p)): i for i, p in enumerate(mol.bonds)}
    cycle_edges_map = {}
    for ci, c in enumerate(mol.cycles):
        edges = []
        for k in range(len(c.atoms)):
            u, v = c.atoms[k], c.atoms[(k + 1) % len(c.atoms)]
            key = (min(u, v), max(u, v))
            if key in bond_idx:
                edges.append(bond_idx[key])
        cycle_edges_map[ci] = edges
    results = [True]
    for ki, c in enumerate(covers):
        # Tous les sextets sont des hexagones
        for s in c.sextets:
            if len(mol.cycles[s].atoms) != 6:
                print(f"  ECHEC {name:14s} cover {ki} : sextet {s} pas hex")
                results.append(False)
        # Chaque sextet a 3 doubles dans ses 6 aretes (selon bond_orders)
        for s in c.sextets:
            n_d = sum(1 for e in cycle_edges_map[s] if c.bond_orders[e] == 2)
            if n_d != 3:
                print(f"  ECHEC {name:14s} cover {ki} : sextet {s} a {n_d} doubles (attendu 3)")
                results.append(False)
        # bond_orders dans {1, 2}
        for bi, bo in enumerate(c.bond_orders):
            if bo not in (1, 2):
                print(f"  ECHEC {name:14s} cover {ki} : bond_order[{bi}]={bo}")
                results.append(False)
        # Longueur correcte
        if len(c.bond_orders) != n_bonds:
            print(f"  ECHEC {name:14s} cover {ki} : len(bond_orders) != n_bonds")
            results.append(False)
    ok = all(results)
    print(f"  {'OK   ' if ok else 'ECHEC'} {name:14s} : {len(covers)} cover(s) "
          f"score {covers[0].n_sextets}, invariants {'OK' if ok else 'CASSES'}")
    return ok


def test_radicalaire():
    """Pentagone seul : pas d'hex, score 0, 1 cover dedupliquee, 1 radical."""
    print("Pentagone seul :")
    covers, is_exact = enumerate_clar_covers(pentagone_seul(), max_count=10)
    n_covers = len(covers)
    score = covers[0].n_sextets if covers else -1
    n_rad = len(covers[0].radicals) if covers else -1
    ok = (n_covers == 1) and (score == 0) and (n_rad == 1) and is_exact
    status = "OK   " if ok else "ECHEC"
    print(f"  {status} pentagone : score=0, 1 cover, 1 radical "
          f"(got n_covers={n_covers}, score={score}, radicaux={n_rad})")
    return ok


def main():
    print("=" * 60)
    print("Test 1 : nombres de Clar (convention Kekule-based)")
    print("=" * 60)
    results = []
    results.append(assert_clar("benzene",      benzene(),      expected_clar=1, expected_n_covers=1))
    results.append(assert_clar("naphtalene",   naphtalene(),   expected_clar=2, expected_n_covers=1))
    results.append(assert_clar("anthracene",   anthracene(),   expected_clar=2, expected_n_covers=2))
    results.append(assert_clar("phenanthrene", phenanthrene(), expected_clar=3, expected_n_covers=1))

    print()
    print("=" * 60)
    print("Test 2 : invariants (sextets hex, 3 doubles, bond_orders 1/2)")
    print("=" * 60)
    for name, mol in [
        ("benzene", benzene()),
        ("naphtalene", naphtalene()),
        ("anthracene", anthracene()),
        ("phenanthrene", phenanthrene()),
    ]:
        results.append(assert_invariants(name, mol))

    print()
    print("=" * 60)
    print("Test 3 : cas radicalaire (pentagone seul)")
    print("=" * 60)
    results.append(test_radicalaire())

    print()
    print("=" * 60)
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
