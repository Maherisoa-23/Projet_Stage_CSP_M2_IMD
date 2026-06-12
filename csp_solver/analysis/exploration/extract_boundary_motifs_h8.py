"""Extrait les motifs de bord (fenetres glissantes de 4 et 5 cycles consecutifs)
sur le bord externe du graphe dual pour tous les sols h8 C1 done.

PROBLEME : ordonner les cycles le long du bord externe.

APPROCHE : on travaille sur les ATOMES de la frontiere. Le bord externe d'un
benzenoide planaire est un cycle d'atomes (chacun appartient a 1 ou 2 cycles
mais aucun a 3). On ordonne les atomes de la frontiere en parcourant ce cycle,
et pour chaque pas on note le cycle "exterieur" auquel l'atome appartient.

La sequence de cycles obtenue est cyclique. On extrait toutes les fenetres
glissantes de longueur 4 et 5 sur cette sequence en supprimant les doublons
consecutifs (un meme cycle apparait sur plusieurs atomes consecutifs du bord
quand il a plusieurs aretes externes).

Chaque fenetre = tuple ordonne de tailles. On canonise par :
  canonical = min(window, reversed(window))  # symetrie miroir
puis on accumule les comptes plan / non-plan par motif canonique.

Output : tmp/motifs_h8_w4.csv, tmp/motifs_h8_w5.csv
  cols : motif (str), n_total, n_plan, n_nonplan, pct_plan, sols_plan_sample,
         sols_nonplan_sample
"""

import gzip
import json
import multiprocessing
import sqlite3
import sys
import time
from collections import Counter, defaultdict


def _parse_hexs(graph_content):
    hexs = []
    for line in graph_content.strip().split("\n"):
        line = line.strip()
        if line.startswith("h "):
            hexs.append(line.split()[1:])
    return hexs


def _boundary_cycle_atoms(hexs):
    """Ordonne les atomes du bord externe en sequence cyclique.

    Strategie :
    1. Identifier atomes frontiere : ceux appartenant a un seul cycle.
       (NB : sur un benzenoide planaire les peri-atomes appartiennent a >=3
        cycles mais ne sont pas sur la frontiere ; les atomes "deep bay" sont
        partages par 2 cycles voisins mais sont sur la frontiere.)
       En realite : un atome est sur la frontiere s'il a une arete pendante.
       Plus simple : compter les ARETES.
    2. Pour chaque arete : compter combien de cycles la contiennent.
       Une arete sur la frontiere appartient a EXACTEMENT 1 cycle.
       Une arete interne appartient a 2 cycles.
    3. Construire le graphe des aretes-frontieres : c'est un cycle simple
       d'atomes (le bord externe).
    4. Parcourir ce cycle.

    Pour chaque atome du parcours, retourner aussi l'indice du cycle qui
    contient l'arete sortante (= cycle exterieur a cet endroit).
    """
    n_hex = len(hexs)
    sets = [set(h) for h in hexs]

    # Construire la liste des aretes par cycle (ordre cyclique dans la liste)
    edges_by_cycle = []
    for h in hexs:
        edges = [tuple(sorted([h[i], h[(i+1) % len(h)]])) for i in range(len(h))]
        edges_by_cycle.append(edges)

    # Compter dans combien de cycles apparait chaque arete
    edge_cycles = defaultdict(list)  # edge -> [cycle_idx]
    for ci, edges in enumerate(edges_by_cycle):
        for e in edges:
            edge_cycles[e].append(ci)

    # Aretes-frontiere = celles dans 1 seul cycle
    boundary_edges = {e for e, cyc in edge_cycles.items() if len(cyc) == 1}
    if not boundary_edges:
        return None

    # Construire le graphe : sommet = atome, arete = arete-frontiere
    bd_neighbors = defaultdict(list)  # atom -> [atom]
    bd_edge_cycle = {}  # (a,b) -> cycle_idx du cycle contenant cette arete
    for e in boundary_edges:
        a, b = e
        bd_neighbors[a].append(b)
        bd_neighbors[b].append(a)
        bd_edge_cycle[e] = edge_cycles[e][0]

    # Chaque atome de la frontiere doit avoir exactement 2 voisins (cycle simple)
    if any(len(v) != 2 for v in bd_neighbors.values()):
        # Bord non-simple (deux composantes ou bifurcation) : on retombe sur
        # le composant le plus grand
        pass  # On accepte quand meme, on fait un parcours best-effort

    # Parcours : partir d'un atome arbitraire, suivre les aretes-frontiere
    start = next(iter(bd_neighbors))
    visited = {start}
    order = [start]
    cycle_seq = []  # le cycle attache a l'arete sortante
    cur = start
    prev = None
    while True:
        nbrs = bd_neighbors[cur]
        nxt = None
        for n in nbrs:
            if n != prev:
                nxt = n
                break
        if nxt is None:
            break
        edge = tuple(sorted([cur, nxt]))
        cycle_seq.append(bd_edge_cycle[edge])
        if nxt == start:
            break
        if nxt in visited:
            break  # garde-fou : eventuelle bifurcation
        visited.add(nxt)
        order.append(nxt)
        prev = cur
        cur = nxt

    return cycle_seq


def _dedup_consecutive(seq):
    """Supprime les repetitions consecutives. Sequence cyclique :
    on traite aussi la jonction fin-debut."""
    if not seq:
        return seq
    out = [seq[0]]
    for x in seq[1:]:
        if x != out[-1]:
            out.append(x)
    # Jonction cyclique
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def _canonical_window(w):
    """Renvoie la forme canonique d'une fenetre : min des rotations + miroir.
    Comme on n'a pas de rotation (fenetre courte sur sequence longue), on
    canonise seulement par symetrie miroir.
    """
    rev = tuple(reversed(w))
    return min(w, rev)


def _extract_motifs(args):
    sol_id, graph_gz, csp_json, verdict = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        hexs = _parse_hexs(graph)
        n_hex = len(hexs)
        sizes = [int(sol.get(str(i), 6)) for i in range(n_hex)]

        cycle_seq = _boundary_cycle_atoms(hexs)
        if cycle_seq is None or len(cycle_seq) < 4:
            return (sol_id, verdict, [], [])

        # Sequence de cycles (avec doublons consecutifs si meme cycle a plusieurs
        # aretes externes)
        ddup = _dedup_consecutive(cycle_seq)
        if len(ddup) < 4:
            return (sol_id, verdict, [], [])

        # Sequence de TAILLES dans l'ordre cyclique
        size_seq = [sizes[c] for c in ddup]
        L = len(size_seq)

        # Fenetres glissantes longueur 4 et 5 (cyclique)
        motifs_w4 = set()
        motifs_w5 = set()
        for i in range(L):
            w4 = tuple(size_seq[(i + k) % L] for k in range(4))
            motifs_w4.add(_canonical_window(w4))
            if L >= 5:
                w5 = tuple(size_seq[(i + k) % L] for k in range(5))
                motifs_w5.add(_canonical_window(w5))

        return (sol_id, verdict, list(motifs_w4), list(motifs_w5))
    except Exception as e:
        return (sol_id, verdict, [], [])


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.row_factory = sqlite3.Row
    sys.stdout.reconfigure(encoding="utf-8")

    print("=== extract_boundary_motifs_h8 START ===")

    # Charger : (sol_id, graph_gz, csp_json, verdict) pour h8 C1 done
    # verdict 'plan' / 'non_plan' uniquement (exclut xtb_failed)
    cur = conn.execute("""
        SELECT sol_id, graph_content_gz, csp_solution_json, verdict
        FROM final_solutions
        WHERE size_h=8 AND config='C1' AND status='done'
          AND verdict IN ('PLAN', 'NON_PLAN')
    """)
    tasks = [(r["sol_id"], r["graph_content_gz"], r["csp_solution_json"], r["verdict"])
             for r in cur]
    print(f"  sols h8 C1 done: {len(tasks)}")

    t0 = time.perf_counter()
    pool = multiprocessing.Pool(processes=10)

    # Accumulateurs : motif -> [n_plan, n_nonplan]
    counts_w4 = defaultdict(lambda: [0, 0])
    counts_w5 = defaultdict(lambda: [0, 0])
    # exemples : motif -> {'plan': set(sol_id), 'nonplan': set(sol_id)} max 5 chaque
    examples_w4 = defaultdict(lambda: {"plan": [], "nonplan": []})
    examples_w5 = defaultdict(lambda: {"plan": [], "nonplan": []})

    n_done = 0
    try:
        for r in pool.imap_unordered(_extract_motifs, tasks, chunksize=200):
            sol_id, verdict, m4_list, m5_list = r
            is_plan = (verdict == "PLAN")
            key_idx = 0 if is_plan else 1
            tag = "plan" if is_plan else "nonplan"
            for m in m4_list:
                counts_w4[m][key_idx] += 1
                if len(examples_w4[m][tag]) < 5:
                    examples_w4[m][tag].append(sol_id)
            for m in m5_list:
                counts_w5[m][key_idx] += 1
                if len(examples_w5[m][tag]) < 5:
                    examples_w5[m][tag].append(sol_id)
            n_done += 1
            if n_done % 10000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s ({n_done/dt:.0f}/s)  |  w4 motifs={len(counts_w4)} w5={len(counts_w5)}")
    finally:
        pool.close()
        pool.join()

    print(f"=== Extraction terminee en {time.perf_counter()-t0:.1f}s ===")
    print(f"  motifs distincts w4 : {len(counts_w4)}")
    print(f"  motifs distincts w5 : {len(counts_w5)}")

    # Baseline %PLAN h8 C1
    n_plan_total = sum(c[0] for c in counts_w4.values())
    n_nonplan_total = sum(c[1] for c in counts_w4.values())
    # NB : ces totaux sont la somme MOTIF-PONDEREE, pas le nombre de sols.
    # Pour calculer P(plan|motif) on n'a pas besoin du baseline absolu (chaque
    # motif a sa propre P(plan|motif)). Pour le ranking, on utilisera comme
    # baseline le %PLAN observe sur l'ensemble des sols.
    n_sol_plan = sum(1 for t in tasks if t[3] == "PLAN")
    n_sol_total = len(tasks)
    baseline = 100 * n_sol_plan / n_sol_total
    print(f"  baseline h8 C1 : {n_sol_plan}/{n_sol_total} = {baseline:.2f}% PLAN")

    # Ecrire CSV w4
    out4 = "tmp/motifs_h8_w4.csv"
    with open(out4, "w", encoding="utf-8") as f:
        f.write("motif\tn_total\tn_plan\tn_nonplan\tpct_plan\tdelta_pp\tex_plan\tex_nonplan\n")
        rows = []
        for m, (np_, nnp_) in counts_w4.items():
            tot = np_ + nnp_
            pct = 100 * np_ / tot if tot else 0
            delta = pct - baseline
            rows.append((m, tot, np_, nnp_, pct, delta,
                         examples_w4[m]["plan"], examples_w4[m]["nonplan"]))
        rows.sort(key=lambda r: -r[1])  # par freq decroissante
        for r in rows:
            m, tot, np_, nnp_, pct, delta, exp, exn = r
            m_str = "-".join(str(x) for x in m)
            f.write(f"{m_str}\t{tot}\t{np_}\t{nnp_}\t{pct:.2f}\t{delta:+.2f}\t{','.join(str(x) for x in exp)}\t{','.join(str(x) for x in exn)}\n")
    print(f"  ecrit {out4}")

    # Ecrire CSV w5
    out5 = "tmp/motifs_h8_w5.csv"
    with open(out5, "w", encoding="utf-8") as f:
        f.write("motif\tn_total\tn_plan\tn_nonplan\tpct_plan\tdelta_pp\tex_plan\tex_nonplan\n")
        rows = []
        for m, (np_, nnp_) in counts_w5.items():
            tot = np_ + nnp_
            pct = 100 * np_ / tot if tot else 0
            delta = pct - baseline
            rows.append((m, tot, np_, nnp_, pct, delta,
                         examples_w5[m]["plan"], examples_w5[m]["nonplan"]))
        rows.sort(key=lambda r: -r[1])
        for r in rows:
            m, tot, np_, nnp_, pct, delta, exp, exn = r
            m_str = "-".join(str(x) for x in m)
            f.write(f"{m_str}\t{tot}\t{np_}\t{nnp_}\t{pct:.2f}\t{delta:+.2f}\t{','.join(str(x) for x in exp)}\t{','.join(str(x) for x in exn)}\n")
    print(f"  ecrit {out5}")

    print(f"=== DONE en {time.perf_counter()-t0:.1f}s ===")
    conn.close()


if __name__ == "__main__":
    main()
