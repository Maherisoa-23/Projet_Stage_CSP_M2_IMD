"""
Construction et resolution du modele CSP avec PyCSP3 + Choco (defaut)
ou ACE (LEGACY, conserve pour reproductibilite du run final).

PyCSP3 est utilise pour generer le fichier XCSP3 (XML), puis le solveur
choisi est appele directement via subprocess. Le solveur par defaut est
Choco depuis la migration de juin 2026 (cf. doc/choco_vs_ace.md) :
Choco est en moyenne plus rapide sur ce corpus et toujours en accord
avec ACE sur les petits squelettes h3-h6, avec une difference marginale
(<= 0.26%) liee a la propagation de LexIncreasing sur les grands
squelettes (Choco garde quelques solutions equivalentes par
automorphisme). Le post-filtre dedup_by_orbit() applique en sortie
neutralise cette difference.
"""

import subprocess
import re
import os
from pathlib import Path
from pycsp3 import *


# =====================================================================
#  Localisation des jars solveurs (bundle dans pycsp3)
# =====================================================================

def _find_ace_jar():
    """[LEGACY] Localise le jar ACE dans l'installation de pycsp3.

    Conserve pour reproductibilite du run final cluster (lance avec ACE).
    Le pipeline designer utilise maintenant Choco par defaut.
    """
    import pycsp3
    pycsp3_dir = Path(pycsp3.__file__).parent
    jar = pycsp3_dir / "solvers" / "ace" / "ACE-2.5.jar"
    if jar.exists():
        return str(jar)
    for f in (pycsp3_dir / "solvers" / "ace").glob("ACE-*.jar"):
        return str(f)
    raise FileNotFoundError("ACE jar introuvable dans pycsp3")


def _find_choco_jar():
    """Localise le jar Choco (bundle avec pycsp3)."""
    import pycsp3
    pycsp3_dir = Path(pycsp3.__file__).parent
    for f in (pycsp3_dir / "solvers" / "choco").glob("choco-parsers-*.jar"):
        return str(f)
    raise FileNotFoundError("Choco jar introuvable dans pycsp3")


# =====================================================================
#  Contrainte Ctopo : blacklist de motifs rayon-2 du graphe dual
# =====================================================================
# Definition : pour chaque cycle v, le motif rayon-2 est
# (taille_v, multiset(tailles des voisins dans le dual)).
# La blacklist liste les motifs identifies comme deleteres pour la
# planarite par l'analyse exploratoire (cf. doc/experimentation.md).
# Source : csp_solver/analysis/exploration/analyze_radius2_motifs.py.
#
# Implementation CSP : pour chaque cycle v de degre d, on filtre la
# blacklist pour ne garder que les motifs de longueur d, puis on
# enumere toutes les permutations du multiset et on interdit chaque
# tuple ordonne via une contrainte negative.

# Multiset blacklist (taille_centrale, tuple_trie_des_tailles_voisines)
CTOPO_BLACKLIST_R2 = {
    # Motifs universels (top defavorisants h7/h8/h9) -- strict
    (7, (5, 7, 7)),
    (7, (7, 7)),
    (7, (6, 7, 7)),
    (7, (5, 6, 7, 7)),
    (5, (5,)),
    (7, (7,)),
    # Loose : ajout des motifs forts h-specifiques
    (7, (5, 5, 7, 7)),
    (5, (5, 5)),
    (7, (6, 6, 7, 7)),
    (6, (6, 7, 7)),
}


def _multiset_permutations(items):
    """Genere toutes les permutations distinctes d'un multiset.

    Ex : _multiset_permutations([5, 7, 7]) -> [(5,7,7), (7,5,7), (7,7,5)]
    """
    from itertools import permutations
    return sorted(set(permutations(items)))


def _ctopo_forbidden_tuples(degree, center_size_in_blacklist):
    """Pour un cycle de degre `degree` et une taille centrale donnee,
    retourne la liste des tuples ordonnes (x_v, x_n1, ..., x_nd) a
    interdire selon la blacklist Ctopo.
    """
    forbidden = []
    for center, nbr_multiset in CTOPO_BLACKLIST_R2:
        if center != center_size_in_blacklist:
            continue
        if len(nbr_multiset) != degree:
            continue
        for perm in _multiset_permutations(nbr_multiset):
            forbidden.append((center,) + perm)
    return forbidden


def count_peri_atoms(graph) -> int:
    """Compte les atomes du benzenoide partages par >=3 cycles.

    Utilise pour le pre-check Ctopo : la contrainte n'a de sens que sur
    des squelettes assez compacts (n_peri >= 4 par defaut).
    """
    from collections import Counter
    atom_count = Counter()
    for hexagon in graph.hexagons:
        for a in hexagon:
            atom_count[a] += 1
    return sum(1 for c in atom_count.values() if c >= 3)


def build_and_solve(graph, preprocessed, enumerate_all=True,
                    adj_57=False, no_table=False, count_hexagon=False,
                    K_sym=None, K_pb=None, K_hb=None, K_tot=None,
                    tau_gb=None, radius_gb=2,
                    ctopo_filter=False, ctopo_min_n_peri=4,
                    solver="choco"):
    """Construit le modele CSP, genere le XML, et appelle le solveur.

    Args:
        graph: BenzenoidGraph
        preprocessed: dict du pre-traitement
        enumerate_all: enumerer toutes les solutions
        adj_57: activer la contrainte C5 (adjacence 5-7)
        no_table: desactiver la contrainte C3 (table de voisinage)
        count_hexagon: si True, garder la solution tout-hexagones (le
            benzenoide d'origine, x_v = 6 pour tout v) dans la liste.
            Defaut False : on l'exclut puisque l'objectif du solveur est
            d'enumerer les substitutions non-benzenoides.
        K_sym: si non-None, contrainte C-SYM |n_pent - n_hept| <= K_sym
        K_pb : si non-None, contrainte C-PB nb_pent_au_bord <= K_pb
        K_hb : si non-None, contrainte C-HB nb_hept_au_bord <= K_hb
        K_tot: si non-None, contrainte C-TOT nb_pent + nb_hept <= K_tot
        tau_gb: contrainte Gauss-Bonnet locale (rayon radius_gb)
        ctopo_filter: si True, applique la contrainte Ctopo (blacklist
            rayon-2 du graphe dual). Necessite ctopo_min_n_peri verifie
            en amont (sinon le solveur ne retourne rien).
        ctopo_min_n_peri: nombre minimal d'atomes peri-condenses dans le
            squelette pour considerer Ctopo applicable. Defaut 4. Si le
            squelette en a moins, la contrainte est silencieusement
            desactivee (retourne liste vide via pre-check dans main.py).
        solver: "choco" (defaut) ou "ace" (LEGACY). Choco est plus rapide
            sur ce corpus (cf. doc/choco_vs_ace.md). ACE est conserve pour
            reproductibilite du run final cluster.

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

    # --- Contraintes additionnelles (issues d'experiments_v2/v3) ---
    # Sommets de bord = sommets de degre dual < 6 (non entoures par 6 voisins)
    boundary = sorted(v for v in range(h) if graph.degree(v) < 6)

    if K_sym is not None and K_sym >= 0:
        # |n_pent - n_hept| <= K_sym
        n_pent_global = Sum(x[v] == 5 for v in range(h))
        n_hept_global = Sum(x[v] == 7 for v in range(h))
        satisfy(n_pent_global - n_hept_global <= K_sym)
        satisfy(n_hept_global - n_pent_global <= K_sym)

    if K_pb is not None and boundary:
        # nb_pent_au_bord <= K_pb
        satisfy(Sum(x[v] == 5 for v in boundary) <= K_pb)

    if K_hb is not None and boundary:
        # nb_hept_au_bord <= K_hb
        satisfy(Sum(x[v] == 7 for v in boundary) <= K_hb)

    if K_tot is not None:
        # nb_pent + nb_hept <= K_tot (= au moins (h - K_tot) hexagones)
        satisfy(Sum(x[v] != 6 for v in range(h)) <= K_tot)

    # --- Contrainte C-LC : Gauss-Bonnet locale (issue de experiments_v3) ---
    # Pour chaque hexagone h0, dans son voisinage de rayon r dans le dual,
    # la courbure cumulee |#pent - #hept| <= tau_gb.
    if tau_gb is not None and tau_gb >= 0:
        import networkx as nx
        for h0 in range(h):
            nbrs = sorted(nx.single_source_shortest_path_length(
                graph.dual, h0, cutoff=radius_gb).keys())
            if not nbrs:
                continue
            pents = Sum(x[v] == 5 for v in nbrs)
            hepts = Sum(x[v] == 7 for v in nbrs)
            satisfy(pents - hepts <= tau_gb)
            satisfy(hepts - pents <= tau_gb)

    # --- Contrainte Ctopo : blacklist de motifs rayon-2 du graphe dual ---
    # Pour chaque cycle v de degre d, on interdit que (x_v, x_voisins_ordonnes)
    # forme un tuple correspondant a un motif blacklist (apres canonisation
    # par multiset). Cf. CTOPO_BLACKLIST_R2 en haut du module.
    #
    # Pre-check n_peri : si le squelette n'a pas assez d'atomes peri-condenses,
    # Ctopo ne s'applique pas et on retourne une liste vide (la contrainte
    # serait trivialement inutile sur un squelette etale).
    if ctopo_filter:
        n_peri = count_peri_atoms(graph)
        if n_peri < ctopo_min_n_peri:
            print(f"  Ctopo : squelette trop etale (n_peri={n_peri} < {ctopo_min_n_peri}), "
                  f"aucune solution attendue.")
            return []
        print(f"  Ctopo active : n_peri={n_peri} >= {ctopo_min_n_peri}, "
              f"application de la blacklist rayon-2.")
        for v in range(h):
            nbrs = graph.neighbors(v)
            d = len(nbrs)
            if d == 0:
                continue
            scope = [x[v]] + [x[u] for u in nbrs]
            # Pour chaque taille centrale candidate (5, 6 ou 7), construire
            # la liste des tuples ordonnes a interdire (deduplique via dict)
            forbidden_set = {}
            for center_size in (5, 6, 7):
                for t in _ctopo_forbidden_tuples(d, center_size):
                    forbidden_set[t] = True
            forbidden = list(forbidden_set.keys())
            if not forbidden:
                continue
            # PyCSP3 : pour chaque tuple interdit, exprimer "au moins une
            # coordonnee differente" via Sum(scope[i] != tup[i]) >= 1.
            # C'est strictement equivalent a "le tuple complet est different"
            # (logique du OR sur des comparaisons).
            #
            # On evite `scope not in tuples` qui demande la syntaxe
            # NegativeTable de PyCSP3, et qui plante avec `set(forbidden)`
            # car Python essaie de hash scope (qui est une list).
            #
            # Pour d=2 (scope de taille 3) : ~5 tuples interdits typiques.
            # Pour d=4 (scope de taille 5) : ~10-20 tuples max.
            for tup in forbidden:
                satisfy(
                    Sum(scope[i] != tup[i] for i in range(len(tup))) >= 1
                )

    # --- Generer le XML ---
    xml_path = str(Path.cwd() / "model.xml")
    compile(filename=xml_path)
    print(f"  Modele XCSP3 genere: {xml_path}")

    # =================================================================
    # [LEGACY] Invocation ACE -- conservee pour reference (run final
    # cluster lance avec ACE). Le pipeline designer utilise Choco par
    # defaut (cf. doc/choco_vs_ace.md : Choco gagne ~96 % du corpus en
    # temps median, ecart de solutions <= 0.26 % corrige par
    # _dedup_by_orbit). Pour reactiver ACE, passer solver="ace" :
    #
    #     ace_jar = _find_ace_jar()
    #     cmd = ["java", "-jar", ace_jar, xml_path]
    #     if enumerate_all:
    #         cmd.extend(["-s=all", "-xe"])
    #     print(f"  Lancement d'ACE...")
    #     print(f"  Commande: {' '.join(cmd)}")
    #     result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    #     print("  --- Sortie ACE (stdout) ---")
    #     for line in result.stdout.splitlines():
    #         print(f"  | {line}")
    #     solutions_list = _parse_ace_output(result.stdout, h)
    # =================================================================

    if solver == "ace":
        # Branche LEGACY : reactive le bloc commente ci-dessus.
        ace_jar = _find_ace_jar()
        cmd = ["java", "-jar", ace_jar, xml_path]
        if enumerate_all:
            cmd.extend(["-s=all", "-xe"])
        print(f"  Lancement d'ACE [LEGACY]...")
        print(f"  Commande: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("  --- Sortie ACE (stdout) ---")
        for line in result.stdout.splitlines():
            print(f"  | {line}")
        if result.stderr.strip():
            print("  --- Sortie ACE (stderr) ---")
            for line in result.stderr.splitlines():
                print(f"  | {line}")
        print("  --- Fin sortie ACE ---")
        solutions_list = _parse_ace_output(result.stdout, h)
        print(f"  Statut ACE: {'SAT' if solutions_list else 'UNSAT'}")
        print(f"  Solutions trouvees (brut): {len(solutions_list)}")
    else:
        # --- Appeler Choco (defaut) ---
        # -a : all solutions
        # -p 1 : single thread (comparaison juste avec ACE single-thread,
        #        identique a l'usage du bench)
        # -limit 60s : timeout solveur cote Choco (en plus du timeout python)
        choco_jar = _find_choco_jar()
        _limit = os.environ.get("CHOCO_LIMIT", "60s")
        _pytimeout = int(os.environ.get("CHOCO_PY_TIMEOUT", "60"))
        cmd = [
            "java", "-cp", choco_jar,
            "org.chocosolver.parser.xcsp.ChocoXCSP",
            xml_path, "-a", "-p", "1", "-limit", _limit,
        ]
        print(f"  Lancement de Choco...")
        print(f"  Commande: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_pytimeout)
        print("  --- Sortie Choco (stdout, dernieres lignes) ---")
        for line in result.stdout.splitlines()[-10:]:
            print(f"  | {line}")
        if result.stderr.strip():
            print("  --- Sortie Choco (stderr) ---")
            for line in result.stderr.splitlines():
                print(f"  | {line}")
        print("  --- Fin sortie Choco ---")
        solutions_list = _parse_choco_output(result.stdout, h)
        print(f"  Statut Choco: {'SAT' if solutions_list else 'UNSAT'}")
        print(f"  Solutions brutes Choco: {len(solutions_list)}")

        # --- Post-filtre : dedup par orbite d'automorphisme ---
        # Choco propage LexIncreasing un peu moins strictement qu'ACE,
        # acceptant parfois (~0.26 % du corpus) des sols equivalentes par
        # automorphisme du graphe dual. On les dedup ici cote Python pour
        # obtenir le meme nombre de sols qu'ACE.
        if generators and solutions_list:
            before = len(solutions_list)
            solutions_list = _dedup_by_orbit(solutions_list, generators, h)
            if len(solutions_list) < before:
                print(f"  Dedup orbite (Choco) : {before} -> {len(solutions_list)}")

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


def _parse_choco_output(output: str, h: int) -> list:
    """Parse la sortie texte de Choco pour extraire les solutions.

    Choco affiche chaque sol en XCSP3 :
        v <instantiation id='solN' type='solution' >
        v     <list>x[0] x[1] ... </list>
        v     <values>5 6 7 ...</values>
        v </instantiation>
    Et termine par :
        d FOUND SOLUTIONS N

    Choco peut aussi afficher la derniere sol 2 fois en fin de stdout
    (une fois dans la boucle puis une fois apres "s SATISFIABLE").
    On deduplique en respectant l'ordre.
    """
    solutions = []
    seen = set()
    pattern_xml = r'<values>\s*(.+?)\s*</values>'
    for match in re.finditer(pattern_xml, output):
        vals_str = match.group(1).strip()
        values = []
        for token in vals_str.split():
            try:
                values.append(int(token))
            except ValueError:
                # Choco ne devrait pas produire de format compact "Nx3", mais
                # par defense on skip les tokens non-numeriques.
                continue
        if len(values) >= h:
            sol_tuple = tuple(values[:h])
            if sol_tuple in seen:
                continue
            seen.add(sol_tuple)
            sol = {i: sol_tuple[i] for i in range(h)}
            solutions.append(sol)
    return solutions


def _dedup_by_orbit(solutions: list, generators: list, h: int) -> list:
    """Dedup les solutions par orbite du groupe d'automorphismes.

    Pour chaque solution, calcule son orbite sous les generateurs et
    garde le min lex comme representant canonique. Deux solutions dans
    la meme orbite sont considerees identiques.

    Choco propage LexIncreasing moins strictement qu'ACE et garde
    parfois plusieurs representants d'une meme orbite -- ce filtre
    Python les ramene a une seule representante (le min lex), ce qui
    aligne le nombre de solutions Choco sur celui d'ACE.

    Si `generators` est vide, retourne `solutions` tel quel.
    """
    if not generators:
        return solutions

    def _to_tuple(sol_dict):
        return tuple(sol_dict[i] for i in range(h))

    def _to_dict(sol_tuple):
        return {i: sol_tuple[i] for i in range(h)}

    def _apply_perm(sol_tuple, perm):
        # perm est un dict v -> pi(v). RHS = (x[pi(0)], ..., x[pi(h-1)])
        return tuple(sol_tuple[perm[v]] for v in range(h))

    def _canonical(sol_tuple):
        """Retourne le min lex de l'orbite de sol_tuple."""
        orbit = {sol_tuple}
        queue = [sol_tuple]
        while queue:
            cur = queue.pop()
            for gen in generators:
                new = _apply_perm(cur, gen)
                if new not in orbit:
                    orbit.add(new)
                    queue.append(new)
        return min(orbit)

    seen_canonical = set()
    out = []
    for sol_dict in solutions:
        sol_t = _to_tuple(sol_dict)
        can = _canonical(sol_t)
        if can in seen_canonical:
            continue
        seen_canonical.add(can)
        # On garde la SOL min lex comme representante canonique, pas la
        # sol originale (qui peut ne pas etre min lex chez Choco).
        out.append(_to_dict(can))
    return out


def format_solution(sol: dict, index: int = None) -> str:
    """Formate une solution pour l'affichage."""
    prefix = f"solution {index}: " if index is not None else ""
    assignments = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
    return f"{prefix}{assignments}"
