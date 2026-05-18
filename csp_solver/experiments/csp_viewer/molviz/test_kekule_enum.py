"""
Tests de l'enumeration des structures de Kekule (kekule.enumerate_kekule).

Verifie le compte sur des molecules de reference dont le nombre de Kekule
est etabli en chimie / theorie des graphes :

  benzene       : 2
  naphtalene    : 3
  anthracene    : 4
  phenanthrene  : 5

On construit les graphes a la main (squelette carbone, pas besoin de .xyz)
pour ne pas dependre du pipeline de detection de bonds par distance.

Test additionnel : verifie qu'aucun Kekule n'est genere en double, et que
tous ont la meme cardinalite (= cardinalite max).

Usage :
    python -m csp_solver.experiments.csp_viewer.molviz.test_kekule_enum
ou directement :
    python csp_solver/experiments/csp_viewer/molviz/test_kekule_enum.py
"""

import sys
from pathlib import Path

# Permet l'execution directe en ajoutant la racine projet au sys.path.
if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "csp_solver.experiments.csp_viewer.molviz"

from csp_solver.experiments.csp_viewer.molviz.bonds import Atom, MolGraph
from csp_solver.experiments.csp_viewer.molviz.kekule import enumerate_kekule


def _make_mol(n_atoms, bonds):
    """Construit un MolGraph minimal pour les tests.
    Les coordonnees ne sont pas utilisees par enumerate_kekule, on met (0,0,0).
    """
    atoms = [Atom(element="C", x=0.0, y=0.0, z=0.0) for _ in range(n_atoms)]
    return MolGraph(atoms=atoms, bonds=list(bonds), cycles=[])


# ----- Topologies des molecules de reference -----
#
# Convention : on commence par un hexagone (vertices 0..5, cycliques) puis on
# fusionne les hexagones suivants en partageant des aretes. Chaque arete partagee
# n'est listee qu'une seule fois.

def benzene():
    """C6H6 : 6 atomes, 1 hexagone. # Kekule = 2."""
    return _make_mol(6, [
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
    ])


def naphtalene():
    """C10H8 : 2 hexagones partageant l'arete 0-1. # Kekule = 3.

    Cycle 1 : 0-1-2-3-4-5
    Cycle 2 : 0-1-6-7-8-9 (partage l'arete 0-1)
    """
    return _make_mol(10, [
        # Cycle 1
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
        # Cycle 2 (sans repeter 0-1)
        (1, 6), (6, 7), (7, 8), (8, 9), (9, 0),
    ])


def anthracene():
    """C14H10 : 3 hexagones lineairement fusionnes. # Kekule = 4.

    Cycle 1 : 0-1-2-3-4-5
    Cycle 2 : 1-2-6-7-8-9  (partage 1-2 avec C1)
    Cycle 3 : 7-8-10-11-12-13 (partage 7-8 avec C2, oppose a 1-2 -> lineaire)
    """
    return _make_mol(14, [
        # Cycle 1
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
        # Cycle 2 (sans 1-2)
        (2, 6), (6, 7), (7, 8), (8, 9), (9, 1),
        # Cycle 3 (sans 7-8)
        (8, 10), (10, 11), (11, 12), (12, 13), (13, 7),
    ])


def phenanthrene():
    """C14H10 : 3 hexagones en zigzag. # Kekule = 5.

    Cycle 1 : 0-1-2-3-4-5
    Cycle 2 : 1-2-6-7-8-9  (partage 1-2 avec C1)
    Cycle 3 : 6-7-10-11-12-13 (partage 6-7 avec C2)

    Subtilite : pour avoir le \"vrai\" phenanthrene (zigzag), l'arete partagee
    entre C2 et C3 doit etre en position META de l'arete partagee entre C1 et
    C2 dans C2, c'est-a-dire separee par exactement UNE arete. Si on prenait
    une arete adjacente (e.g. 2-6), le sommet 2 aurait degre 4 (impossible
    en PAH). Si on prenait l'arete opposee (3 aretes d'ecart), ce serait
    l'anthracene.
    """
    return _make_mol(14, [
        # Cycle 1
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
        # Cycle 2 (sans 1-2)
        (2, 6), (6, 7), (7, 8), (8, 9), (9, 1),
        # Cycle 3 (sans 6-7)
        (7, 10), (10, 11), (11, 12), (12, 13), (13, 6),
    ])


# ----- Helpers de test -----

def assert_count(name, mol, expected_count):
    """Verifie le nombre de Kekule. Retourne True si OK."""
    kekules, is_exact = enumerate_kekule(mol, max_count=1000)
    n = len(kekules)
    ok = (n == expected_count) and is_exact
    status = "OK   " if ok else "ECHEC"
    print(f"  {status} {name:14s} -> {n} Kekule (attendu {expected_count})  "
          f"exact={is_exact}")
    return ok


def assert_invariants(name, mol):
    """Verifie : pas de doublons, meme cardinalite pour tous les Kekule."""
    kekules, _ = enumerate_kekule(mol, max_count=1000)
    if not kekules:
        print(f"  SKIP  {name:14s} : pas de Kekule")
        return True

    # Pas de doublons (bond_orders identiques)
    signatures = set()
    for k in kekules:
        sig = tuple(k.bond_orders)
        if sig in signatures:
            print(f"  ECHEC {name:14s} : doublon dans l'enumeration !")
            return False
        signatures.add(sig)

    # Tous les matchings ont la meme cardinalite (= cardinalite max)
    n_doubles_set = {k.n_doubles for k in kekules}
    if len(n_doubles_set) != 1:
        print(f"  ECHEC {name:14s} : cardinalites differentes {n_doubles_set}")
        return False

    print(f"  OK    {name:14s} : {len(kekules)} Kekule uniques, "
          f"tous a {kekules[0].n_doubles} doubles")
    return True


def assert_cap(name, mol, cap):
    """Verifie que le cap fonctionne et que is_exact est False."""
    kekules, is_exact = enumerate_kekule(mol, max_count=cap)
    n = len(kekules)
    # On veut n <= cap, et si on a atteint le cap on veut is_exact=False
    ok = (n <= cap) and (n < cap or not is_exact)
    status = "OK   " if ok else "ECHEC"
    print(f"  {status} {name:14s} : cap={cap}, retourne={n}, is_exact={is_exact}")
    return ok


def main():
    print("=" * 60)
    print("Test 1 : comptes connus")
    print("=" * 60)
    results = []
    results.append(assert_count("benzene",      benzene(),      2))
    results.append(assert_count("naphtalene",   naphtalene(),   3))
    results.append(assert_count("anthracene",   anthracene(),   4))
    results.append(assert_count("phenanthrene", phenanthrene(), 5))

    print()
    print("=" * 60)
    print("Test 2 : invariants (pas de doublons, meme cardinalite)")
    print("=" * 60)
    for name, mol in [
        ("benzene",      benzene()),
        ("naphtalene",   naphtalene()),
        ("anthracene",   anthracene()),
        ("phenanthrene", phenanthrene()),
    ]:
        results.append(assert_invariants(name, mol))

    print()
    print("=" * 60)
    print("Test 3 : cap a 2 sur phenanthrene (devrait avoir is_exact=False)")
    print("=" * 60)
    results.append(assert_cap("phenanthrene", phenanthrene(), cap=2))

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
