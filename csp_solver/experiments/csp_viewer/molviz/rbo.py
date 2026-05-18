"""
Calcul des Ring Bond Orders (RBO) — extension non-benzenoide.

Definition (these Varet, def 2.4.14, 2.4.15) :
  - bond_order(e) = (# Kekule ou e est double) / (# Kekule total)
  - RBO(cycle) = somme des bond_orders des aretes du cycle

Pour les molecules benzenoides (hexagones uniquement), RBO d'un hex ∈ [0, 3].
Extension naturelle pour 5/7 cycles : meme formule appliquee aux aretes
de chaque cycle. Bornes chimiques :
  - pentagone : [0, 2]  (au plus 2 doubles dans un pentagone d'un PAH)
  - hexagone  : [0, 3]
  - heptagone : [0, 3]

Le "max possible" est calcule a posteriori : on prend la valeur max
observee sur toutes les Kekule enumerees. C'est plus honnete que de
coder en dur des bornes theoriques (lesquelles dependent du contexte).

Calcul :
  1. enumerate_kekule(mol, max_count) -> liste de Kekule (matchings parfaits)
  2. Pour chaque arete : bond_order = (nb Kekule la marquant double) / N
  3. Pour chaque cycle : CBO = somme des bond_orders des aretes du cycle
  4. cbo_max = max sur les Kekule du nb de doubles dans le cycle

Cas particulier radicalaire : si la molecule n'admet aucun matching
parfait (n_radicals > 0 dans tous les matchings max), RBO n'est PAS
defini au sens strict (Pauling/Randic ne traitent que les Kekule
strictes). On retourne available=False avec un message clair.

Plafond : DEFAULT_MAX_KEKULE = 10000. Si la molecule a plus de Kekule,
on signale is_exact=False et le RBO est approxime sur les 10000
premieres (ordre canonique de enumerate_kekule).
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .bonds import MolGraph
from .kekule import enumerate_kekule


# Plafond pour l'enumeration. Au-dela, RBO est approxime.
DEFAULT_MAX_KEKULE = 10000


@dataclass
class RboResult:
    """Resultat du calcul RBO d'une molecule.

    available     : True si RBO defini (>=1 Kekule stricte).
    bond_orders   : longueur len(mol.bonds), valeurs in [0, 1].
                    bond_orders[i] = fraction de Kekule ou bonds[i] est double.
    cbo           : longueur len(mol.cycles), valeurs >= 0.
                    cbo[i] = somme des bond_orders des aretes du cycle i.
    cbo_max       : longueur len(mol.cycles), entiers >= 0.
                    cbo_max[i] = max nb de doubles dans le cycle i sur
                    toutes les Kekule enumerees. Sert de denominateur pour
                    l'affichage "cbo / cbo_max" (chimiquement honnete).
    n_kekule      : nombre de Kekule effectivement enumerees.
    is_exact      : True si on a tout enumere, False si plafonne.
    n_radicals    : nombre de radicaux du matching max (0 si Kekule stricte).
    reason        : si available=False, raison textuelle (pour l'UI).
    """
    available: bool = True
    bond_orders: List[float] = field(default_factory=list)
    cbo: List[float] = field(default_factory=list)
    cbo_max: List[int] = field(default_factory=list)
    n_kekule: int = 0
    is_exact: bool = True
    n_radicals: int = 0
    reason: Optional[str] = None


def compute_rbo(mol: MolGraph,
                max_count: int = DEFAULT_MAX_KEKULE) -> RboResult:
    """Calcule les bond orders et RBO d'une molecule.

    Args:
        mol       : MolGraph (squelette carbone)
        max_count : plafond du nombre de Kekule a enumerer. Au-dela
                    on s'arrete et le RBO est approxime (is_exact=False).

    Returns:
        RboResult. Voir docstring de la classe.

    Note : si la molecule est radicalaire (pas de matching parfait),
    le resultat a available=False et reason explique pourquoi.
    """
    n_bonds = len(mol.bonds)
    n_cycles = len(mol.cycles)

    if n_bonds == 0:
        return RboResult(available=False, reason="molecule sans liaisons")

    kekule_list, is_exact = enumerate_kekule(mol, max_count=max_count)

    if not kekule_list:
        return RboResult(available=False, reason="aucune Kekule trouvee")

    # Si la molecule est radicalaire, tous les matchings max ont le meme
    # nombre de radicaux > 0. Dans ce cas, RBO n'est pas defini.
    n_radicals = len(kekule_list[0].radicals)
    if n_radicals > 0:
        return RboResult(
            available=False,
            n_kekule=len(kekule_list),
            is_exact=is_exact,
            n_radicals=n_radicals,
            reason=("molecule radicalaire : pas de structure de Kekule "
                    "stricte, RBO non defini"),
        )

    N = len(kekule_list)

    # Index des aretes pour les retrouver dans les cycles.
    # mol.bonds = liste de tuples (i,j) avec i<j (cf bonds.py).
    bond_idx = {tuple(sorted(p)): i for i, p in enumerate(mol.bonds)}

    # Pre-calcule les indices d'aretes de chaque cycle (atomes consecutifs).
    # Une arete d'un cycle qui n'est pas dans mol.bonds est ignoree
    # (peut arriver si bonds.py a rate une liaison, mais robuste).
    cycle_edges: List[List[int]] = []
    for c in mol.cycles:
        edges: List[int] = []
        atoms = c.atoms
        for k in range(len(atoms)):
            u, v = atoms[k], atoms[(k + 1) % len(atoms)]
            key = (min(u, v), max(u, v))
            if key in bond_idx:
                edges.append(bond_idx[key])
        cycle_edges.append(edges)

    # Agregation en une seule passe sur les Kekule.
    double_count = [0] * n_bonds
    cbo_max = [0] * n_cycles
    for k in kekule_list:
        bo = k.bond_orders
        for i in range(n_bonds):
            if bo[i] == 2:
                double_count[i] += 1
        for ci, eis in enumerate(cycle_edges):
            n_d = sum(1 for e in eis if bo[e] == 2)
            if n_d > cbo_max[ci]:
                cbo_max[ci] = n_d

    bond_orders = [c / N for c in double_count]
    cbo = [sum(bond_orders[e] for e in eis) for eis in cycle_edges]

    return RboResult(
        available=True,
        bond_orders=bond_orders,
        cbo=cbo,
        cbo_max=cbo_max,
        n_kekule=N,
        is_exact=is_exact,
        n_radicals=0,
    )
