"""Module commun pour bench ACE vs Choco.

Construit un modele XCSP3 a partir d'un graph + config, puis l'invoque
successivement avec ACE et Choco. Mesure le temps wall-clock de chaque
invocation et le nombre de solutions trouvees.

Identique a build_and_solve() de utils/model.py mais sans la partie
solveur (genere juste le XML), puis 2 fonctions run_ace / run_choco
appelees separement.
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Tuple


# Localisation des jars
_PYCSP3_DIR = None


def _find_pycsp3_dir() -> Path:
    global _PYCSP3_DIR
    if _PYCSP3_DIR is not None:
        return _PYCSP3_DIR
    import pycsp3
    _PYCSP3_DIR = Path(pycsp3.__file__).parent
    return _PYCSP3_DIR


def find_ace_jar() -> str:
    p = _find_pycsp3_dir() / "solvers" / "ace"
    j = p / "ACE-2.5.jar"
    if j.exists():
        return str(j)
    for f in p.glob("ACE-*.jar"):
        return str(f)
    raise FileNotFoundError("ACE jar not found")


def find_choco_jar() -> str:
    p = _find_pycsp3_dir() / "solvers" / "choco"
    for f in p.glob("choco-parsers-*.jar"):
        return str(f)
    raise FileNotFoundError("Choco jar not found")


# =====================================================================
#  Construction du modele XCSP3 (sans appel solveur)
# =====================================================================

def build_xml(graph, preprocessed, config: dict, xml_path: str) -> None:
    """Construit le modele PyCSP3 selon `config` et compile en XCSP3.

    Reproduit exactement les contraintes de build_and_solve() de
    utils/model.py, sans l'invocation ACE.

    config keys utilisees :
      adj_57 (bool), no_table (bool), count_hexagon (bool, defaut False),
      K_sym, K_pb, K_hb, K_tot (int or None),
      tau_gb (int or None), radius_gb (int, defaut 2),
      ctopo_filter (bool), ctopo_min_n_peri (int, defaut 4).
    """
    from pycsp3 import (clear, VarArray, satisfy, Sum, LexIncreasing, If,
                        compile)

    clear()

    domains = preprocessed["domains"]
    tables = preprocessed["tables"]
    generators = preprocessed["generators"]
    free = preprocessed["free"]
    h = graph.h

    x = VarArray(size=h, dom=lambda i: domains[i])

    # C1 : conservation
    satisfy(Sum(x) == 6 * h)

    # C3 : table de voisinage
    if not config.get("no_table", False):
        for v in free:
            if v in tables and tables[v]:
                neighbors_v = graph.neighbors(v)
                scope = [x[v]] + [x[u] for u in neighbors_v]
                satisfy(scope in tables[v])

    # Rupture de symetrie
    for gen in generators:
        permuted = [x[gen[i]] for i in range(h)]
        satisfy(LexIncreasing(x, permuted))

    # C5 : adjacence 5-7
    if config.get("adj_57", False):
        for v in range(h):
            nbrs = graph.neighbors(v)
            if nbrs:
                satisfy(If(x[v] == 5, Then=Sum(x[u] == 7 for u in nbrs) >= 1))
                satisfy(If(x[v] == 7, Then=Sum(x[u] == 5 for u in nbrs) >= 1))

    boundary = sorted(v for v in range(h) if graph.degree(v) < 6)
    K_sym = config.get("K_sym")
    K_pb = config.get("K_pb")
    K_hb = config.get("K_hb")
    K_tot = config.get("K_tot")
    if K_sym is not None and K_sym >= 0:
        n_pent = Sum(x[v] == 5 for v in range(h))
        n_hept = Sum(x[v] == 7 for v in range(h))
        satisfy(n_pent - n_hept <= K_sym)
        satisfy(n_hept - n_pent <= K_sym)
    if K_pb is not None and boundary:
        satisfy(Sum(x[v] == 5 for v in boundary) <= K_pb)
    if K_hb is not None and boundary:
        satisfy(Sum(x[v] == 7 for v in boundary) <= K_hb)
    if K_tot is not None:
        satisfy(Sum(x[v] != 6 for v in range(h)) <= K_tot)

    # C-LC : Gauss-Bonnet locale
    tau_gb = config.get("tau_gb")
    radius_gb = config.get("radius_gb", 2)
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

    # Ctopo : blacklist rayon-2
    if config.get("ctopo_filter", False):
        from utils.model import (
            CTOPO_BLACKLIST_R2, _ctopo_forbidden_tuples, count_peri_atoms
        )
        n_peri_min = config.get("ctopo_min_n_peri", 4)
        n_peri = count_peri_atoms(graph)
        # Si squelette trop etale : on n'ajoute aucune contrainte (sera UNSAT
        # potentiellement). On laisse passer pour que le solveur tranche.
        if n_peri >= n_peri_min:
            for v in range(h):
                nbrs = graph.neighbors(v)
                d = len(nbrs)
                if d == 0:
                    continue
                scope = [x[v]] + [x[u] for u in nbrs]
                forbidden_set = {}
                for center_size in (5, 6, 7):
                    for t in _ctopo_forbidden_tuples(d, center_size):
                        forbidden_set[t] = True
                forbidden = list(forbidden_set.keys())
                for tup in forbidden:
                    satisfy(Sum(scope[i] != tup[i] for i in range(len(tup))) >= 1)

    compile(filename=xml_path)


# =====================================================================
#  Invocations solveurs
# =====================================================================

def run_ace(xml_path: str, timeout_s: int = 300) -> Tuple[int, int, str]:
    """Lance ACE en enumeration complete sur xml_path.

    Retourne (n_sols, wall_ms, status) ou status ∈ {'ok', 'timeout',
    'error', 'unsat'}.
    """
    ace_jar = find_ace_jar()
    cmd = ["java", "-jar", ace_jar, xml_path, "-s=all", "-xe"]
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, int(timeout_s * 1000), "timeout"
    wall_ms = int((time.perf_counter() - t0) * 1000)

    if r.returncode != 0:
        return -1, wall_ms, "error"

    # Compte le nombre de solutions via les balises <values>
    # (Note : pour les sols compactes "Nx3" = 3 fois la valeur N, ce qui
    # compte UNE seule sol -- on compte les blocs <values>, pas les nombres).
    n_sols = len(re.findall(r"<values>", r.stdout))
    if n_sols == 0 and "UNSAT" in r.stdout.upper():
        return 0, wall_ms, "unsat"
    return n_sols, wall_ms, "ok"


def run_choco(xml_path: str, timeout_s: int = 300) -> Tuple[int, int, str]:
    """Lance Choco en enumeration complete sur xml_path.

    Retourne (n_sols, wall_ms, status).
    """
    choco_jar = find_choco_jar()
    # -a : all solutions
    # -p 1 : 1 thread (fair vs ACE single-thread)
    # -limit "{N}s" : timeout cote solveur (en plus du timeout python)
    cmd = [
        "java", "-cp", choco_jar,
        "org.chocosolver.parser.xcsp.ChocoXCSP",
        xml_path,
        "-a",
        "-p", "1",
        "-limit", f"{int(timeout_s)}s",
    ]
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s + 10, encoding="utf-8",
                           errors="replace")
    except subprocess.TimeoutExpired:
        return -1, int(timeout_s * 1000), "timeout"
    wall_ms = int((time.perf_counter() - t0) * 1000)

    if r.returncode != 0:
        return -1, wall_ms, "error"

    # Choco affiche "d FOUND SOLUTIONS N" en fin de stdout
    m = re.search(r"d FOUND SOLUTIONS\s+(\d+)", r.stdout)
    if m:
        return int(m.group(1)), wall_ms, "ok"
    # Fallback : compte les blocs <values>
    n_sols = len(re.findall(r"<values>", r.stdout))
    if n_sols == 0 and "UNSATISFIABLE" in r.stdout.upper():
        return 0, wall_ms, "unsat"
    if n_sols == 0:
        # Si stdout vide ou pas standard -> error
        return -1, wall_ms, "error"
    return n_sols, wall_ms, "ok"


# =====================================================================
#  Benchmark complet (1 instance)
# =====================================================================

def benchmark_one(graph_path: str, config: dict, timeout_s: int = 300,
                  tmp_dir: str = None) -> dict:
    """Pour 1 (graph, config) : genere XML + run ACE + run Choco.

    Retourne dict avec :
      n_sols_ace, t_ace_ms, status_ace,
      n_sols_choco, t_choco_ms, status_choco,
      build_ms (temps pour generer le XML)
    """
    import sys
    here = Path(__file__).resolve().parent
    csp_root = here.parent
    if str(csp_root) not in sys.path:
        sys.path.insert(0, str(csp_root))

    from utils.parser import parse
    from utils.preprocessing import preprocess

    # XML temporaire
    if tmp_dir is None:
        tmp_dir = os.environ.get("TMPDIR") or "/tmp"
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)
    xml_path = str(Path(tmp_dir) / f"bench_{os.getpid()}_{int(time.time()*1000)}.xml")

    # Build XML
    t0 = time.perf_counter()
    graph = parse(graph_path)
    preprocessed = preprocess(graph, freeze_b2=config.get("freeze_b2", False))
    build_xml(graph, preprocessed, config, xml_path)
    build_ms = int((time.perf_counter() - t0) * 1000)

    # Run solvers
    try:
        n_ace, t_ace, st_ace = run_ace(xml_path, timeout_s=timeout_s)
    except Exception as e:
        n_ace, t_ace, st_ace = -1, 0, f"exc:{type(e).__name__}"
    try:
        n_choco, t_choco, st_choco = run_choco(xml_path, timeout_s=timeout_s)
    except Exception as e:
        n_choco, t_choco, st_choco = -1, 0, f"exc:{type(e).__name__}"

    # Cleanup XML
    try:
        os.remove(xml_path)
    except OSError:
        pass

    return {
        "n_sols_ace": n_ace,
        "t_ace_ms": t_ace,
        "status_ace": st_ace,
        "n_sols_choco": n_choco,
        "t_choco_ms": t_choco,
        "status_choco": st_choco,
        "build_ms": build_ms,
    }
