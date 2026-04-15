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


def build_and_solve(graph, preprocessed, enumerate_all=True):
    """Construit le modele CSP, genere le XML, et appelle ACE.

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
    print(f"  Solutions trouvees: {len(solutions_list)}")

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
        if len(values) == h:
            sol = {i: values[i] for i in range(h)}
            solutions.append(sol)

    return solutions


def format_solution(sol: dict, index: int = None) -> str:
    """Formate une solution pour l'affichage."""
    prefix = f"solution {index}: " if index is not None else ""
    assignments = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
    return f"{prefix}{assignments}"
