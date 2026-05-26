"""
Enumeration des couvertures de Clar (sextets aromatiques).

Definition (convention chimistes Hagebaum-Reignier / Carissan) :
  Une couverture de Clar est definie a partir d'une structure de Kekule K
  de la molecule :
    - Un hexagone est un "sextet" dans K ssi il a exactement 3 doubles
      parmi ses 6 aretes (motif benzenique local), MEME SI ces doubles
      sont partagees avec des hexagones voisins.
    - Le score d'une couverture = nombre d'hex avec 3 doubles dans K.
    - Le nombre de Clar de la molecule = max score sur toutes les K.

Difference avec la definition classique de Clar 1972 (these Varet 2.4.5) :
  Clar exige que les sextets soient vertex-disjoints (aucun atome partage
  entre 2 sextets). Cette contrainte est LEVEE dans notre implementation,
  conformement a la convention pratique des chimistes : visuellement,
  toute aromaticite locale (3 doubles dans un hex) merite d'etre marquee
  par un rond, meme si les doubles sont partagees.

Consequences pratiques :
  - Naphtalene : Clar=2 (les 2 hex peuvent etre sextets simultanement
    dans la Kekule avec doubles aux positions alternees).
  - Phenanthrene : Clar=3 (les 3 hex sextets simultanement).
  - Coronene-like : l'hex central peut etre marque sextet s'il a 3
    doubles dans la Kekule choisie.

Algorithme :
  1. enumerate_kekule(mol, DEFAULT_MAX_KEKULE) -> liste de Kekule.
  2. Pour chaque K, identifier les hex avec exactement 3 doubles.
  3. Garder les K avec score max (= nombre de Clar).
  4. Dedup par sextet set : plusieurs K peuvent donner les memes sextets
     avec des bond_orders differents (dans les parties non-sextet ou
     dans les choix d'alternance internes aux sextets). On conserve une
     seule representante par sextet set (la premiere dans l'ordre
     canonique d'enumerate_kekule).

Pour les molecules radicalaires (pas de matching parfait) : enumerate_kekule
retourne des matchings de cardinalite max avec radicaux. L'algo fonctionne
identiquement : les sextets sont detectes par leurs 3 doubles dans la
Kekule, et les radicaux sont conserves dans la couverture.
"""

from dataclasses import dataclass, field
from typing import List, Set, Tuple

from .bonds import MolGraph, bond_index_map, cycle_edge_indices
from .kekule import enumerate_kekule


# Plafond d'enumeration interne des Kekule pour le calcul Clar. Doit etre
# >= au nombre reel de Kekule de la molecule pour garantir l'exhaustivite.
# Pour h3-h9 (5/7 contraignent fortement), 10000 est largement suffisant.
DEFAULT_MAX_KEKULE = 10000


@dataclass
class ClarCover:
    """Une couverture de Clar.

    sextets       : indices des cycles porteurs d'un rond de Clar.
                    Tous sont des hexagones avec 3 doubles dans la Kekule
                    sous-jacente.
    bond_orders   : longueur len(mol.bonds), 1 ou 2.
                    Bond orders NATURELS de la Kekule (pas une alternance
                    canonique forcee) : les liaisons partagees entre 2
                    sextets sont effectivement dessinees comme doubles
                    quand elles le sont dans la Kekule choisie.
    radicals      : indices d'atomes non couverts par le matching.
                    Typiquement vide pour molecule non-radicalaire.
    n_sextets     : len(sextets) = score Clar de cette couverture.
    """
    sextets: List[int] = field(default_factory=list)
    bond_orders: List[int] = field(default_factory=list)
    radicals: Set[int] = field(default_factory=set)
    n_sextets: int = 0


def enumerate_clar_covers(mol: MolGraph,
                          max_count: int = 200) -> Tuple[List[ClarCover], bool]:
    """Enumere les couvertures de Clar de score MAXIMUM.

    Args:
        mol       : MolGraph (squelette carbone).
        max_count : nombre maximum de couvertures a retourner APRES dedup
                    par sextet set. Au-dela on s'arrete (is_exact=False).

    Returns:
        (covers, is_exact)
          - covers   : List[ClarCover], toutes avec le meme n_sextets.
          - is_exact : True ssi (a) enumerate_kekule a tout enumere ET
                       (b) on n'a pas plafonne notre liste de couvertures.

    Note : retourne [] uniquement si la molecule n'a aucune Kekule (cas
    degenere : mol vide). Une molecule sans hexagone retourne 1
    couverture avec sextets=[] et n_sextets=0.
    """
    if not mol.bonds:
        return [], True

    # Enumere toutes les Kekule (cap haut pour avoir la vraie valeur max).
    kekule_list, is_exact_kekule = enumerate_kekule(
        mol, max_count=DEFAULT_MAX_KEKULE,
    )
    if not kekule_list:
        return [], True

    # Identifie les hexagones et leurs aretes (en indices de mol.bonds).
    hex_indices = [i for i, c in enumerate(mol.cycles) if len(c.atoms) == 6]
    bond_idx = bond_index_map(mol)
    all_cycle_edges = cycle_edge_indices(mol, bond_idx)
    hex_bond_indices = {hi: all_cycle_edges[hi] for hi in hex_indices}

    # Pour chaque Kekule, calcule le set d'hex sextets (= ceux avec 3
    # doubles dans leurs 6 aretes).
    candidates: List[Tuple[List[int], "KekuleAssignment"]] = []
    for k in kekule_list:
        bo = k.bond_orders
        sextets = [
            hi for hi in hex_indices
            if sum(1 for e in hex_bond_indices[hi] if bo[e] == 2) == 3
        ]
        candidates.append((sextets, k))

    # Score max parmi toutes les Kekule. max() sur generator vide impossible
    # ici car kekule_list non-vide -> candidates non-vide.
    best_score = max(len(s) for s, _ in candidates)

    # Filtre score max + dedup par sextet set. Ordre canonique preserve
    # (premiere Kekule rencontree avec un sextet set donne est conservee).
    seen_sextet_sets = set()
    covers: List[ClarCover] = []
    capped = False
    for sextets, k in candidates:
        if len(sextets) != best_score:
            continue
        key = tuple(sorted(sextets))
        if key in seen_sextet_sets:
            continue
        seen_sextet_sets.add(key)
        covers.append(ClarCover(
            sextets=list(sextets),
            bond_orders=list(k.bond_orders),
            radicals=set(k.radicals),
            n_sextets=best_score,
        ))
        if len(covers) >= max_count:
            capped = True
            break

    return covers, (is_exact_kekule and not capped)
