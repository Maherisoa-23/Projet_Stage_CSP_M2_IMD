"""
Tests du calcul des Ring Bond Orders (rbo.compute_rbo).

Verifie :
  - Valeurs exactes pour le benzene (BO=0.5, CBO=3.0).
  - Invariants pour naphtalene et anthracene :
      sum(bond_orders) == n_doubles_par_Kekule
      CBO d'un cycle == somme des bond_orders de ses 6 aretes
  - Pentagone seul -> available=False (pas de matching parfait).
  - Azulene (5/7 fused) -> available=True, RBO defini, valeurs coherentes.

Usage :
    python -m experiments.viewer.molviz.test_rbo
ou directement :
    python csp_solver/experiments/csp_viewer/molviz/test_rbo.py
"""

import sys
from pathlib import Path

# Permet l'execution directe en ajoutant la racine projet au sys.path.
if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "experiments.viewer.molviz"

from experiments.viewer.molviz.bonds import Atom, Cycle, MolGraph
from experiments.viewer.molviz.rbo import compute_rbo


def _make_mol(n_atoms, bonds, cycles):
    """Construit un MolGraph minimal pour les tests.
    Les coordonnees ne sont pas utilisees par compute_rbo, on met (0,0,0).
    Les cycles sont passes en parametre car bonds.py les extrait par
    plongement planaire (pas dispo sans coordonnees reelles).
    """
    atoms = [Atom(element="C", x=0.0, y=0.0, z=0.0) for _ in range(n_atoms)]
    bonds_list = [(min(u, v), max(u, v)) for (u, v) in bonds]
    cycles_list = [Cycle(atoms=list(c), anomaly=False) for c in cycles]
    return MolGraph(atoms=atoms, bonds=bonds_list, cycles=cycles_list)


# ----- Topologies des molecules de reference -----

def benzene():
    """C6H6 : 1 hexagone, 2 Kekule."""
    return _make_mol(
        6,
        [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)],
        cycles=[[0, 1, 2, 3, 4, 5]],
    )


def naphtalene():
    """C10H8 : 2 hexagones fusionnes, 3 Kekule."""
    return _make_mol(
        10,
        [
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
            (1, 6), (6, 7), (7, 8), (8, 9), (9, 0),
        ],
        # Cycles : ring 1 = 0,1,2,3,4,5 ; ring 2 = 0,1,6,7,8,9 (ordre cyclique)
        # Pour ring 2 partage l'arete 0-1, l'ordre cyclique doit etre
        # 1-6-7-8-9-0 (puis 0-1 ferme).
        cycles=[
            [0, 1, 2, 3, 4, 5],
            [1, 6, 7, 8, 9, 0],
        ],
    )


def anthracene():
    """C14H10 : 3 hexagones lineaires, 4 Kekule."""
    return _make_mol(
        14,
        [
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0),
            (2, 6), (6, 7), (7, 8), (8, 9), (9, 1),
            (8, 10), (10, 11), (11, 12), (12, 13), (13, 7),
        ],
        cycles=[
            [0, 1, 2, 3, 4, 5],
            [1, 2, 6, 7, 8, 9],     # partage 1-2 avec ring 1
            [7, 8, 10, 11, 12, 13], # partage 7-8 avec ring 2
        ],
    )


def pentagone_seul():
    """C5 : un seul pentagone. Nb impair de C -> pas de Kekule stricte."""
    return _make_mol(
        5,
        [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)],
        cycles=[[0, 1, 2, 3, 4]],
    )


def azulene():
    """C10H8 : pentagone + heptagone fusionnes, partagent une arete.

    Numerotation :
      Pent : 0-1-2-3-4 (arete 0-4 partagee)
      Hept : 0-4-5-6-7-8-9 (arete 0-4 partagee, autres : 4-5, 5-6,
             6-7, 7-8, 8-9, 9-0)
    """
    return _make_mol(
        10,
        [
            (0, 1), (1, 2), (2, 3), (3, 4), (0, 4),
            (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (0, 9),
        ],
        cycles=[
            [0, 1, 2, 3, 4],
            [0, 4, 5, 6, 7, 8, 9],  # ordre cyclique avec arete partagee 0-4
        ],
    )


# ----- Helpers de test -----

def assert_close(name, got, expected, tol=1e-9):
    """Verifie egalite numerique a tolerance."""
    ok = abs(got - expected) < tol
    status = "OK   " if ok else "ECHEC"
    print(f"  {status} {name:40s} got={got:.6f} expected={expected:.6f}")
    return ok


def test_benzene():
    """Benzene : BO=0.5 partout, CBO=3.0."""
    print("Benzene :")
    mol = benzene()
    r = compute_rbo(mol)
    results = []
    results.append(("benzene available", r.available is True))
    results.append(("benzene n_kekule", r.n_kekule == 2))
    results.append(("benzene is_exact", r.is_exact is True))
    # BO=0.5 pour les 6 aretes
    for i, bo in enumerate(r.bond_orders):
        ok = abs(bo - 0.5) < 1e-9
        results.append((f"benzene BO[{i}]=0.5", ok))
    # CBO=3.0, cbo_max=3
    ok_cbo = abs(r.cbo[0] - 3.0) < 1e-9
    ok_max = r.cbo_max[0] == 3
    results.append(("benzene CBO=3.0", ok_cbo))
    results.append(("benzene cbo_max=3", ok_max))
    for name, ok in results:
        print(f"  {'OK   ' if ok else 'ECHEC'} {name}")
    return all(ok for _, ok in results)


def test_invariants(name, mol, expected_n_kekule):
    """Invariants generaux : nb Kekule, sum(BO)=n_doubles, BO in [0,1]."""
    print(f"{name} (invariants) :")
    r = compute_rbo(mol)
    results = []
    results.append(("available", r.available is True))
    results.append((f"n_kekule={expected_n_kekule}",
                    r.n_kekule == expected_n_kekule))
    results.append(("is_exact", r.is_exact is True))
    # Tous les BO dans [0, 1]
    all_in_range = all(0.0 <= bo <= 1.0 for bo in r.bond_orders)
    results.append(("BO in [0,1]", all_in_range))
    # Aucun BO == 0 (sinon liaison jamais double, structurellement rare
    # pour ces molecules). En realite naphtalene a des aretes avec BO > 0
    # pour toutes ses aretes (chaque arete est double dans au moins 1 K).
    all_positive = all(bo > 0 for bo in r.bond_orders)
    results.append(("toutes les aretes ont BO > 0", all_positive))
    # sum(BO) = n_doubles par Kekule (constant car cardinalite max).
    # Pour naphtalene : 5 doubles, 11 aretes. Pour anthracene : 7 doubles, 16 aretes.
    sum_bo = sum(r.bond_orders)
    expected_sum = mol.bonds and (len(mol.atoms) // 2)  # n_atoms/2 si perfect matching
    ok_sum = abs(sum_bo - expected_sum) < 1e-9
    results.append((f"sum(BO)={expected_sum} (= n_doubles)", ok_sum))
    # CBO d'un cycle = somme des BO de ses 6 aretes (verification directe)
    bond_idx = {tuple(sorted(p)): i for i, p in enumerate(mol.bonds)}
    for ci, c in enumerate(mol.cycles):
        edges = []
        for k in range(len(c.atoms)):
            u, v = c.atoms[k], c.atoms[(k + 1) % len(c.atoms)]
            key = (min(u, v), max(u, v))
            if key in bond_idx:
                edges.append(bond_idx[key])
        expected_cbo = sum(r.bond_orders[e] for e in edges)
        ok = abs(r.cbo[ci] - expected_cbo) < 1e-9
        results.append((f"cycle {ci} CBO = somme des BO du cycle", ok))
        # CBO <= cbo_max
        ok_max = r.cbo[ci] <= r.cbo_max[ci] + 1e-9
        results.append((f"cycle {ci} CBO <= cbo_max", ok_max))
    for nm, ok in results:
        print(f"  {'OK   ' if ok else 'ECHEC'} {nm}")
    return all(ok for _, ok in results)


def test_radicalaire():
    """Pentagone seul : 5 atomes -> pas de matching parfait -> RBO non defini."""
    print("Pentagone seul (radicalaire) :")
    r = compute_rbo(pentagone_seul())
    results = []
    results.append(("available=False", r.available is False))
    results.append(("n_radicals > 0", r.n_radicals > 0))
    results.append(("reason non vide", bool(r.reason)))
    for name, ok in results:
        print(f"  {'OK   ' if ok else 'ECHEC'} {name}")
    return all(ok for _, ok in results)


def test_azulene():
    """Azulene : 5/7 fused, 10 atomes, doit avoir un matching parfait."""
    print("Azulene (5/7 fused) :")
    mol = azulene()
    r = compute_rbo(mol)
    results = []
    results.append(("available", r.available is True))
    results.append(("n_radicals=0", r.n_radicals == 0))
    results.append(("n_kekule > 0", r.n_kekule > 0))
    results.append(("2 cycles", len(r.cbo) == 2))
    # Cycle 0 = pentagone, cycle 1 = heptagone
    pent_cbo, hept_cbo = r.cbo[0], r.cbo[1]
    pent_max, hept_max = r.cbo_max[0], r.cbo_max[1]
    # Bornes chimiques : pent <= 2 doubles, hept <= 3 doubles
    results.append(("pent cbo_max <= 2", pent_max <= 2))
    results.append(("hept cbo_max <= 3", hept_max <= 3))
    results.append((f"pent CBO ({pent_cbo:.3f}) > 0", pent_cbo > 0))
    results.append((f"hept CBO ({hept_cbo:.3f}) > 0", hept_cbo > 0))
    print(f"  INFO  n_kekule = {r.n_kekule}")
    print(f"  INFO  pent : CBO={pent_cbo:.3f} / max={pent_max}")
    print(f"  INFO  hept : CBO={hept_cbo:.3f} / max={hept_max}")
    for name, ok in results:
        print(f"  {'OK   ' if ok else 'ECHEC'} {name}")
    return all(ok for _, ok in results)


def main():
    print("=" * 60)
    print("Test 1 : benzene (valeurs exactes)")
    print("=" * 60)
    r1 = test_benzene()
    print()

    print("=" * 60)
    print("Test 2 : invariants naphtalene/anthracene")
    print("=" * 60)
    r2 = test_invariants("naphtalene", naphtalene(), expected_n_kekule=3)
    print()
    r3 = test_invariants("anthracene", anthracene(), expected_n_kekule=4)
    print()

    print("=" * 60)
    print("Test 3 : cas radicalaire (pentagone seul)")
    print("=" * 60)
    r4 = test_radicalaire()
    print()

    print("=" * 60)
    print("Test 4 : azulene (5/7 fused, extension non-benzenoide)")
    print("=" * 60)
    r5 = test_azulene()
    print()

    results = [r1, r2, r3, r4, r5]
    n_ok = sum(1 for r in results if r)
    n_total = len(results)
    print("=" * 60)
    if n_ok == n_total:
        print(f"TOUS LES TESTS OK ({n_ok}/{n_total})")
        return 0
    else:
        print(f"ECHECS : {n_total - n_ok} / {n_total}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
