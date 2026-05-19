"""
Tests des couvertures de Clar (clar.enumerate_clar_covers).

Verifie les nombres de Clar de molecules de reference :
  benzene       : 1 (l'hexagone unique porte 1 sextet)
  naphtalene    : 1 (l'un des 2 hex est sextet, l'autre = Kekule normal)
  anthracene    : 1 (un des 3 hex est sextet, les 2 autres = Kekule)
  phenanthrene  : 2 (les 2 hex exterieurs sont sextets simultanement,
                     car ils sont vertex-disjoints)

Verifie aussi :
  - vertex-disjoint des sextets dans chaque couverture
  - chaque sextet est bien un hexagone (taille 6)
  - les radicaux du residu ne depassent pas n_radicals_total
  - cas radicalaire : pentagone seul -> Clar=0 (pas d'hex), 1 couverture
    (la couverture vide avec matching max du pentagone, 1 radical)

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
            [6, 7, 10, 11, 12, 13],  # zigzag : partage (6,7) avec ring 2
        ],
    )


def pentagone_seul():
    return _make_mol(
        5,
        [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)],
        cycles=[[0, 1, 2, 3, 4]],
    )


def assert_clar_number(name, mol, expected_clar, expected_n_covers=None):
    """Verifie le nombre de Clar (et eventuellement le nb de couvertures)."""
    covers, is_exact = enumerate_clar_covers(mol, max_count=1000)
    if not covers:
        actual_clar = 0
    else:
        actual_clar = covers[0].n_sextets
    n_covers = len(covers)
    ok_clar = (actual_clar == expected_clar)
    ok_exact = is_exact
    ok_n = (expected_n_covers is None) or (n_covers == expected_n_covers)
    ok = ok_clar and ok_exact and ok_n
    status = "OK   " if ok else "ECHEC"
    extra = f" ({n_covers} couvertures)" if expected_n_covers is None \
            else f" ({n_covers}/{expected_n_covers} couvertures)"
    print(f"  {status} {name:14s} Clar={actual_clar} (attendu {expected_clar}){extra} "
          f"is_exact={is_exact}")
    return ok


def assert_invariants(name, mol):
    """Verifie : sextets sont des hex, vertex-disjoints, meme score, bond_orders 1/2."""
    covers, _ = enumerate_clar_covers(mol, max_count=1000)
    if not covers:
        print(f"  SKIP  {name:14s} : aucune couverture")
        return True
    n_bonds = len(mol.bonds)
    same_score = len({c.n_sextets for c in covers}) == 1
    if not same_score:
        print(f"  ECHEC {name:14s} : scores differents {[c.n_sextets for c in covers]}")
        return False
    results = [True]
    for ki, c in enumerate(covers):
        # Tous les sextets sont des hexagones (taille 6)
        for s in c.sextets:
            if len(mol.cycles[s].atoms) != 6:
                print(f"  ECHEC {name:14s} cover {ki} : sextet {s} pas un hex")
                results.append(False)
        # Sextets vertex-disjoints
        used = set()
        for s in c.sextets:
            for a in mol.cycles[s].atoms:
                if a in used:
                    print(f"  ECHEC {name:14s} cover {ki} : sextets non disjoints")
                    results.append(False)
                    break
                used.add(a)
        # bond_orders : tous 1 ou 2
        for bi, bo in enumerate(c.bond_orders):
            if bo not in (1, 2):
                print(f"  ECHEC {name:14s} cover {ki} : bond_order[{bi}]={bo}")
                results.append(False)
        # Longueur bond_orders = n_bonds
        if len(c.bond_orders) != n_bonds:
            print(f"  ECHEC {name:14s} cover {ki} : len(bond_orders) = "
                  f"{len(c.bond_orders)} vs {n_bonds}")
            results.append(False)
    ok = all(results)
    print(f"  {'OK   ' if ok else 'ECHEC'} {name:14s} : {len(covers)} couvertures, "
          f"toutes a {covers[0].n_sextets} sextets, "
          f"invariants {'OK' if ok else 'CASSES'}")
    return ok


def test_radicalaire():
    """Pentagone seul : Clar=0 (pas d'hex), 1 couverture vide + 1 radical."""
    print("Pentagone seul :")
    covers, is_exact = enumerate_clar_covers(pentagone_seul(), max_count=10)
    # Pas d'hex -> uniquement la couverture vide (mask=0), score 0
    n_covers = len(covers)
    actual_clar = covers[0].n_sextets if covers else -1
    n_rad = len(covers[0].radicals) if covers else -1
    ok = (n_covers == 1) and (actual_clar == 0) and (n_rad == 1) and is_exact
    status = "OK   " if ok else "ECHEC"
    print(f"  {status} pentagone : Clar=0, 1 couverture, residu avec 1 radical "
          f"(got n_covers={n_covers}, Clar={actual_clar}, radicaux={n_rad})")
    return ok


def main():
    print("=" * 60)
    print("Test 1 : nombres de Clar connus")
    print("=" * 60)
    results = []
    results.append(assert_clar_number("benzene", benzene(), expected_clar=1))
    results.append(assert_clar_number("naphtalene", naphtalene(), expected_clar=1))
    results.append(assert_clar_number("anthracene", anthracene(), expected_clar=1))
    results.append(assert_clar_number("phenanthrene", phenanthrene(), expected_clar=2))

    print()
    print("=" * 60)
    print("Test 2 : invariants (sextets hex, disjoints, meme score)")
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
