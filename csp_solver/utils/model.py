"""
Construction et resolution du modele CSP avec PyCSP3 + ACE.

PyCSP3 est utilise pour generer le fichier XCSP3 (XML).
ACE est appele directement via subprocess (plus fiable que
le mecanisme interne de PyCSP3 qui pose des problemes avec sys.argv).
"""

import subprocess
import re
import os
from pathlib import Path
from pycsp3 import *


# Chemin vers le jar ACE (dans l'installation de pycsp3)
def _find_ace_jar():
    """Localise le jar ACE dans l'installation de pycsp3."""
    import pycsp3
    pycsp3_dir = Path(pycsp3.__file__).parent
    jar = pycsp3_dir / "solvers" / "ace" / "ACE-2.5.jar"
    if jar.exists():
        return str(jar)
    # Fallback : chercher n'importe quel ACE-*.jar
    for f in (pycsp3_dir / "solvers" / "ace").glob("ACE-*.jar"):
        return str(f)
    raise FileNotFoundError("ACE jar introuvable dans pycsp3")


def build_and_solve(graph, preprocessed, enumerate_all=True,
                    adj_57=False, no_table=False, count_hexagon=False):
    """Construit le modele CSP, genere le XML, et appelle ACE.

    Args:
        graph: BenzenoidGraph
        preprocessed: dict du pre-traitement
        enumerate_all: enumerer toutes les solutions
        adj_57: activer la contrainte C5 (adjacence 5-7)
        no_table: desactiver la contrainte C3 (table de voisinage)
        count_hexagon: si True, garder la solution tout-hexagones (le
            benzenoide d'origine, x_v = 6 pour tout v) dans la liste.
            Defaut False : on l'exclut puisque l'objectif du solveur est
            d'enumerer les substitutions non-benzenoides. Le benzenoide
            d'origine reste teste separement par test.py (champ "original"
            du data.json).

    Returns:
        Liste de solutions, chaque solution est un dict {v: taille}
    """
    clear()

    domains = preprocessed['domains']
    tables = preprocessed['tables']
    generators = preprocessed['generators']
    free = preprocessed['free']
    h = graph.h

    # --- Variables ---
    x = VarArray(size=h, dom=lambda i: domains[i])

    # --- Contrainte C1 : conservation du carbone ---
    satisfy(
        Sum(x) == 6 * h
    )

    # --- Contrainte C3 : voisinage admissible (tables extensionnelles) ---
    if not no_table:
        for v in free:
            if v in tables and tables[v]:
                neighbors_v = graph.neighbors(v)
                scope = [x[v]] + [x[u] for u in neighbors_v]
                satisfy(
                    scope in tables[v]
                )

    # --- Rupture de symetrie : lex-leader ---
    for gen in generators:
        permuted = [x[gen[i]] for i in range(h)]
        satisfy(
            LexIncreasing(x, permuted)
        )

    # --- Contrainte C5 : adjacence 5-7 (optionnelle) ---
    if adj_57:
        for v in range(h):
            neighbors_v = graph.neighbors(v)
            if neighbors_v:
                # x[v]=5 => au moins un voisin vaut 7
                satisfy(
                    If(x[v] == 5, Then=Sum(x[u] == 7 for u in neighbors_v) >= 1)
                )
                # x[v]=7 => au moins un voisin vaut 5
                satisfy(
                    If(x[v] == 7, Then=Sum(x[u] == 5 for u in neighbors_v) >= 1)
                )

    # --- Generer le XML ---
    xml_path = str(Path.cwd() / "model.xml")
    compile(filename=xml_path)
    print(f"  Modele XCSP3 genere: {xml_path}")

    # --- Appeler ACE directement ---
    ace_jar = _find_ace_jar()
    cmd = ["java", "-jar", ace_jar, xml_path]
    if enumerate_all:
        cmd.extend(["-s=all", "-xe"])

    print(f"  Lancement d'ACE...")
    print(f"  Commande: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    # Debug : afficher la sortie brute d'ACE
    print("  --- Sortie ACE (stdout) ---")
    for line in result.stdout.splitlines():
        print(f"  | {line}")
    if result.stderr.strip():
        print("  --- Sortie ACE (stderr) ---")
        for line in result.stderr.splitlines():
            print(f"  | {line}")
    print("  --- Fin sortie ACE ---")

    # --- Parser la sortie ACE ---
    solutions_list = _parse_ace_output(result.stdout, h)

    print(f"  Statut ACE: {'SAT' if solutions_list else 'UNSAT'}")
    print(f"  Solutions trouvees (brut): {len(solutions_list)}")

    # --- Post-filtre : exclure la solution tout-hexagones (benzenoide d'origine) ---
    # Choix architectural : post-filtre plutot qu'une contrainte CSP globale, car
    # une contrainte "Sum(x[v] != 6) >= 1" devient infaisable si tous les sommets
    # sont geles a {6}, ce qui est genant a gerer en amont. Le post-filtre marche
    # toujours et le surcout est negligeable (1 solution a filtrer dans le pire cas).
    if not count_hexagon and solutions_list:
        before = len(solutions_list)
        solutions_list = [s for s in solutions_list
                          if not all(v == 6 for v in s.values())]
        if len(solutions_list) < before:
            print(f"  Filtre tout-hexagones : {before} -> {len(solutions_list)} "
                  f"(--count-hexagon pour la conserver)")

    # Nettoyage
    if os.path.exists(xml_path):
        os.remove(xml_path)

    return solutions_list


def _parse_ace_output(output: str, h: int) -> list:
    """Parse la sortie texte d'ACE pour extraire les solutions.

    ACE avec -xe affiche chaque solution en XML :
        v  <instantiation id='sol1'> <list> x[] </list> <values> 5 6 7 </values> </instantiation>
    """
    solutions = []

    # Parser les elements <instantiation> (format principal avec -xe)
    pattern_xml = r'<values>\s*(.+?)\s*</values>'
    for match in re.finditer(pattern_xml, output):
        vals_str = match.group(1).strip()
        values = []
        for token in vals_str.split():
            if "x" in token:
                # Format compact : "6x3" = 6 6 6
                val, count = token.split("x")
                values.extend([int(val)] * int(count))
            else:
                values.append(int(token))
        if len(values) >= h:
            # Prendre seulement les h premieres valeurs (variables x[])
            # Les suivantes sont des variables auxiliaires (aux_gb, _ax_, etc.)
            sol = {i: values[i] for i in range(h)}
            solutions.append(sol)

    return solutions


def format_solution(sol: dict, index: int = None) -> str:
    """Formate une solution pour l'affichage."""
    prefix = f"solution {index}: " if index is not None else ""
    assignments = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
    return f"{prefix}{assignments}"
