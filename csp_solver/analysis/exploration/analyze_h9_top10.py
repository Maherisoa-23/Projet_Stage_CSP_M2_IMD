"""Analyse les 10 sols h9 avec les plus grands angles hors-plan.

Pour chacune extrait : repartition des cycles, adjacences typees, position
boundary/interieur des defauts, taille max d'amas de defauts, triple junctions.
Sort un rapport texte UTF-8.
"""

import gzip
import io
import json
import sqlite3
import sys
from collections import Counter


TOP = [
    ("1-11-21-30-39-48-56-57-67", 242),
    ("1-2-11-21-30-39-48-56-57", 29),
    ("3-9-12-19-22-29-30-31-40", 378),
    ("3-13-18-19-20-21-22-27-32", 200),
    ("1-2-3-11-20-29-38-47-56", 979),
    ("3-13-18-19-20-22-23-30-31", 695),
    ("1-2-11-21-30-39-48-57-66", 29),
    ("3-12-18-21-22-27-28-29-30", 714),
    ("3-9-11-12-18-21-28-29-30", 883),
    ("4-9-13-19-22-29-30-31-32", 1108),
]


def parse_hex_lines(g):
    hexs = []
    for line in g.strip().split("\n"):
        line = line.strip()
        if line.startswith("h "):
            hexs.append(line.split()[1:])
    return hexs


def adjacency(hexs):
    n = len(hexs)
    adj = [[] for _ in range(n)]
    sets = [set(h) for h in hexs]
    for i in range(n):
        for j in range(i + 1, n):
            if len(sets[i] & sets[j]) >= 2:
                adj[i].append(j)
                adj[j].append(i)
    return adj, sets


def boundary_atoms(hexs):
    c = Counter()
    for h in hexs:
        for a in h:
            c[a] += 1
    return {a for a, k in c.items() if k == 1}, c


def main():
    out = io.StringIO()
    conn = sqlite3.connect("experiments/final/final_h3_h9.db")
    conn.row_factory = sqlite3.Row

    for rank, (mol_name, idx) in enumerate(TOP, 1):
        row = conn.execute(
            "SELECT graph_content_gz, csp_solution_json, angle_deg "
            "FROM final_solutions WHERE graph_name=? AND sol_index=? AND config='C1'",
            (mol_name, idx),
        ).fetchone()
        if not row:
            print(f"#{rank} {mol_name} sol{idx}: NOT FOUND", file=out)
            continue
        g = gzip.decompress(row["graph_content_gz"]).decode()
        sol = json.loads(row["csp_solution_json"])
        hexs = parse_hex_lines(g)
        adj, sets = adjacency(hexs)
        n_hex = len(hexs)
        sizes_list = [int(sol.get(str(i), 6)) for i in range(n_hex)]
        n5 = sizes_list.count(5)
        n6 = sizes_list.count(6)
        n7 = sizes_list.count(7)

        a55 = a57 = a77 = a56 = a67 = a66 = 0
        for i in range(n_hex):
            for j in adj[i]:
                if j > i:
                    p = tuple(sorted([sizes_list[i], sizes_list[j]]))
                    if p == (5, 5):
                        a55 += 1
                    elif p == (5, 6):
                        a56 += 1
                    elif p == (5, 7):
                        a57 += 1
                    elif p == (6, 6):
                        a66 += 1
                    elif p == (6, 7):
                        a67 += 1
                    elif p == (7, 7):
                        a77 += 1

        bnd, atom_cnt = boundary_atoms(hexs)
        hex_on_bnd = [i for i, hs in enumerate(sets) if hs & bnd]
        pent_bnd = sum(1 for i in hex_on_bnd if sizes_list[i] == 5)
        hept_bnd = sum(1 for i in hex_on_bnd if sizes_list[i] == 7)
        K_signed = n5 - n7
        K_abs = n5 + n7
        degs = [len(adj[i]) for i in range(n_hex)]
        max_deg = max(degs)
        n_triple = sum(1 for v in atom_cnt.values() if v >= 3)

        # Plus gros cluster de defauts adjacents
        defects = {i for i, s in enumerate(sizes_list) if s != 6}
        visited = set()
        biggest = 0
        for s in defects:
            if s in visited:
                continue
            stack = [s]
            comp = 0
            while stack:
                v = stack.pop()
                if v in visited:
                    continue
                visited.add(v)
                comp += 1
                for u in adj[v]:
                    if u in defects and u not in visited:
                        stack.append(u)
            biggest = max(biggest, comp)

        print(f"#{rank}  {mol_name}  sol{idx}  angle={row['angle_deg']:.2f} deg", file=out)
        print(f"   n5={n5}  n6={n6}  n7={n7}    K_signed={K_signed:+d}*pi/3    defauts={K_abs}/{n_hex}", file=out)
        print(f"   adj  5-5={a55} 5-7={a57} 7-7={a77}  |  5-6={a56} 6-6={a66} 6-7={a67}", file=out)
        print(f"   bnd  pent={pent_bnd}/{n5}  hept={hept_bnd}/{n7}  (interieur p/h={n5-pent_bnd}/{n7-hept_bnd})", file=out)
        print(f"   max_cluster_defauts={biggest}  triple_jct={n_triple}  max_dual_deg={max_deg}", file=out)
        print(file=out)

    text = out.getvalue()
    with open("tmp/h9_top10_angles.txt", "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
