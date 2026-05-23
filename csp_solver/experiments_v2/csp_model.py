"""
Modele CSP enrichi pour experiments_v2.

Reproduit utils/model.py::build_and_solve mais en ajoutant les
contraintes optionnelles de experiments_v2/constraints/.

POURQUOI UNE COPIE ET NON UN PATCH ?
PyCSP3 fonctionne par etat global (clear() / satisfy() / compile()) :
on ne peut pas "ajouter des contraintes depuis l'exterieur" proprement
sans modifier la fonction d'origine. Pour garantir ZERO REGRESSION sur
csp_solver/utils/model.py existant, on duplique ici la logique et on
intercale nos extras entre la construction des contraintes existantes
et l'appel a compile().

Les contraintes existantes (C1, C3, C5, lex-leader, post-filtre tout-hex)
sont reproduites a l'identique. Toutes les contraintes additionnelles
sont des appels a constraints/*.py.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from pycsp3 import VarArray, Sum, satisfy, If, LexIncreasing, clear, compile

from .constraints import symmetry, boundary_caps, total_caps


def _find_ace_jar():
    """Idem utils.model._find_ace_jar."""
    import pycsp3
    pycsp3_dir = Path(pycsp3.__file__).parent
    jar = pycsp3_dir / "solvers" / "ace" / "ACE-2.5.jar"
    if jar.exists():
        return str(jar)
    for f in (pycsp3_dir / "solvers" / "ace").glob("ACE-*.jar"):
        return str(f)
    raise FileNotFoundError("ACE jar introuvable dans pycsp3")


def build_and_solve_v2(graph, preprocessed,
                       enumerate_all: bool = True,
                       adj_57: bool = False,
                       no_table: bool = False,
                       count_hexagon: bool = False,
                       # --- Nouveautes experiments_v2 ---
                       K_sym: Optional[int] = None,    # |n_pent - n_hept| <= K_sym
                       K_pb: Optional[int] = None,     # n_pent_at_boundary <= K_pb
                       K_hb: Optional[int] = None,     # n_hept_at_boundary <= K_hb
                       K_tot: Optional[int] = None,    # n_pent + n_hept <= K_tot
                       ace_timeout: int = 60) -> list:
    """Construit le CSP enrichi et resout via ACE.

    Args:
        graph         : BenzenoidGraph
        preprocessed  : dict du pre-traitement (cf utils.preprocessing.preprocess)
        enumerate_all : enumerer toutes les solutions
        adj_57        : C5 (adjacence 5-7) — existant
        no_table      : disable C3 — existant
        count_hexagon : conserve la solution tout-hex — existant
        K_sym         : C-SYM si non-None
        K_pb          : C-PB si non-None
        K_hb          : C-HB si non-None
        K_tot         : C-TOT si non-None
        ace_timeout   : timeout ACE en secondes

    Returns:
        liste de solutions, chaque solution est dict {v: taille (5/6/7)}.
    """
    clear()

    domains = preprocessed['domains']
    tables = preprocessed['tables']
    generators = preprocessed['generators']
    free = preprocessed['free']
    h = graph.h

    # ===== Variables =====
    x = VarArray(size=h, dom=lambda i: domains[i])

    # ===== C1 : conservation du carbone =====
    satisfy(Sum(x) == 6 * h)

    # ===== C3 : table de voisinage =====
    if not no_table:
        for v in free:
            if v in tables and tables[v]:
                neighbors_v = graph.neighbors(v)
                scope = [x[v]] + [x[u] for u in neighbors_v]
                satisfy(scope in tables[v])

    # ===== Rupture de symetrie : lex-leader =====
    for gen in generators:
        permuted = [x[gen[i]] for i in range(h)]
        satisfy(LexIncreasing(x, permuted))

    # ===== C5 : adjacence 5-7 =====
    if adj_57:
        for v in range(h):
            neighbors_v = graph.neighbors(v)
            if neighbors_v:
                satisfy(If(x[v] == 5,
                            Then=Sum(x[u] == 7 for u in neighbors_v) >= 1))
                satisfy(If(x[v] == 7,
                            Then=Sum(x[u] == 5 for u in neighbors_v) >= 1))

    # ===== Contraintes experiments_v2 (optionnelles) =====
    symmetry.apply(x, graph, K_sym=K_sym if K_sym is not None else -1)
    boundary_caps.apply_pb(x, graph, K_pb=K_pb)
    boundary_caps.apply_hb(x, graph, K_hb=K_hb)
    total_caps.apply(x, graph, K_tot=K_tot)

    # ===== Generer le XML =====
    xml_path = str(Path.cwd() / "model_v2.xml")
    compile(filename=xml_path)
    print(f"  Modele XCSP3 (v2) genere: {xml_path}")
    # Trace des K activees pour debug
    active = []
    if K_sym is not None: active.append(f"sym={K_sym}")
    if K_pb is not None: active.append(f"pb={K_pb}")
    if K_hb is not None: active.append(f"hb={K_hb}")
    if K_tot is not None: active.append(f"tot={K_tot}")
    if active:
        print(f"  Contraintes v2 actives : {' '.join(active)}")

    # ===== ACE =====
    ace_jar = _find_ace_jar()
    cmd = ["java", "-jar", ace_jar, xml_path]
    if enumerate_all:
        cmd.extend(["-s=all", "-xe"])
    print(f"  Commande: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=ace_timeout)

    # ===== Parse =====
    solutions_list = _parse_ace_output(result.stdout, h)
    print(f"  Statut ACE: {'SAT' if solutions_list else 'UNSAT'}")
    print(f"  Solutions trouvees (brut): {len(solutions_list)}")

    # ===== Post-filtre tout-hex =====
    if not count_hexagon and solutions_list:
        before = len(solutions_list)
        solutions_list = [s for s in solutions_list
                          if not all(v == 6 for v in s.values())]
        if len(solutions_list) < before:
            print(f"  Filtre tout-hex : {before} -> {len(solutions_list)}")

    if os.path.exists(xml_path):
        os.remove(xml_path)

    return solutions_list


def _parse_ace_output(output: str, h: int) -> list:
    """Idem utils.model._parse_ace_output (duplique pour isolation)."""
    solutions = []
    pattern_xml = r'<values>\s*(.+?)\s*</values>'
    for match in re.finditer(pattern_xml, output):
        vals_str = match.group(1).strip()
        values = []
        for token in vals_str.split():
            if "x" in token:
                val, count = token.split("x")
                values.extend([int(val)] * int(count))
            else:
                values.append(int(token))
        if len(values) >= h:
            sol = {i: values[i] for i in range(h)}
            solutions.append(sol)
    return solutions
