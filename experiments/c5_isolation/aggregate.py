"""Agrege les comptes plane/non-plane pour les 2 slides "effet de C5".

4 configs derivees (cf. README.md de ce dossier) :
  - C structurel             : Cstr, no_table_run.db (h3-h8) + h9_choco_g1..g4.db (h9)
  - C structurel + C5        : C1, experiments/final/final_h3_h9.db
  - C structurel + C6        : Cstr ci-dessus, filtre adj_57 == 0 (recalcule)
  - C structurel + C6 + C5   : C1 ci-dessus, filtre sol_features.adj_57 == 0

Seuil de planeite pour les slides : angle_deg < 25 (binaire, independant du
seuil 10/15 historique stocke dans la colonne `verdict`). Les lignes
status='failed' (reconstruction geometrique impossible) sont exclues partout.

Usage : python experiments/c5_isolation/aggregate.py
"""

import gzip
import json
import multiprocessing
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "csp_solver"))
sys.path.insert(0, str(ROOT / "cluster" / "ops"))

from csp_solver.analysis.compute_adjacencies import _parse_graph_to_adjacency  # noqa: E402
from plafond_h9_C1 import stratified_sample, signature  # noqa: E402

H9_PLAFOND_TARGET = 200
H9_PLAFOND_SEED = 42

HERE = Path(__file__).resolve().parent
ANGLE_THRESHOLD = 25.0

CSTR_DBS = [
    HERE / "no_table_run.db",
    HERE / "h9_choco_g1.db",
    HERE / "h9_choco_g2.db",
    HERE / "h9_choco_g3.db",
    HERE / "h9_choco_g4.db",
]
FINAL_DB = ROOT / "experiments" / "final" / "final_h3_h9.db"


def _has_adj57(args):
    sol_id, graph_gz, csp_json, angle_deg, size_h = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        adj = _parse_graph_to_adjacency(graph)
        for v in range(len(adj)):
            v_size = sol.get(str(v), 6)
            for u in adj[v]:
                if u > v:
                    u_size = sol.get(str(u), 6)
                    if tuple(sorted([v_size, u_size])) == (5, 7):
                        return (sol_id, True, angle_deg, size_h)
        return (sol_id, False, angle_deg, size_h)
    except Exception as e:
        print(f"  [ERR] sol_id={sol_id}: {type(e).__name__}: {e}", file=sys.stderr)
        return (sol_id, None, angle_deg, size_h)


def _empty_by_h():
    return {h: {"plan": 0, "nonplan": 0} for h in range(3, 10)}


def load_cstr_rows():
    """Lit (sol_id, graph_name, size_h, graph_content_gz, csp_solution_json,
    angle_deg) pour toutes les lignes status='done' de Cstr, a travers les
    5 DB shardees."""
    rows = []
    per_db = {}
    for db_path in CSTR_DBS:
        if not db_path.exists():
            print(f"  [ATTENTION] DB manquante, ignoree : {db_path}", file=sys.stderr)
            continue
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT sol_id, graph_name, size_h, graph_content_gz, csp_solution_json, angle_deg "
            "FROM final_solutions WHERE config='Cstr' AND status='done'"
        )
        n = 0
        for sol_id, graph_name, size_h, graph_gz, csp_json, angle_deg in cur:
            rows.append((sol_id, graph_name, size_h, graph_gz, csp_json, angle_deg))
            n += 1
        per_db[db_path.name] = n
        conn.close()
    return rows, per_db


def aggregate_cstr():
    """Retourne (resultats, dict {graph_name: n_done} pour les graphes h9
    couverts par Cstr).

    Cstr-h9 ne couvre que les graphes effectivement dispatches sur le
    cluster (2136/2418, le reste n'a jamais ete lance suite aux
    interruptions), ET certains de ces graphes "couverts" n'ont recu
    qu'une fraction de leur quota cible de 200 (dispatch interrompu en
    cours de route, min observe = 20/graphe). On retourne le compte EXACT
    par graphe pour que aggregate_c1() plafonne C1-h9 au MEME nombre par
    graphe (pas un 200 fixe) -- garantit C1 <= Cstr graphe par graphe,
    donc a toute taille h et au total."""
    rows, per_db = load_cstr_rows()
    print("=== Cstr : lignes 'done' par DB source ===")
    for name, n in per_db.items():
        print(f"  {name}: {n}")
    total = len(rows)
    print(f"  TOTAL Cstr done : {total}")

    h9_count_per_graph = {}
    for r in rows:
        if r[2] == 9:
            h9_count_per_graph[r[1]] = h9_count_per_graph.get(r[1], 0) + 1
    print(f"  Graphes h9 couverts par Cstr : {len(h9_count_per_graph)} / 2418")

    print("=== Cstr : calcul adj_57 (multiprocessing) ===")
    pool_args = [(sol_id, graph_gz, csp_json, angle_deg, size_h)
                 for sol_id, _gname, size_h, graph_gz, csp_json, angle_deg in rows]
    with multiprocessing.Pool(processes=10) as pool:
        results = pool.map(_has_adj57, pool_args, chunksize=500)

    n_err = sum(1 for _, has57, _, _ in results if has57 is None)
    if n_err:
        print(f"  [ATTENTION] {n_err} erreurs de calcul adj_57 (exclues)", file=sys.stderr)

    plan_all = sum(1 for _, has57, ang, _ in results if has57 is not None and ang < ANGLE_THRESHOLD)
    nonplan_all = sum(1 for _, has57, ang, _ in results if has57 is not None and ang >= ANGLE_THRESHOLD)
    plan_c6 = sum(1 for _, has57, ang, _ in results if has57 is False and ang < ANGLE_THRESHOLD)
    nonplan_c6 = sum(1 for _, has57, ang, _ in results if has57 is False and ang >= ANGLE_THRESHOLD)

    by_h_all = _empty_by_h()
    by_h_c6 = _empty_by_h()
    for _, has57, ang, size_h in results:
        if has57 is None:
            continue
        key = "plan" if ang < ANGLE_THRESHOLD else "nonplan"
        by_h_all[size_h][key] += 1
        if has57 is False:
            by_h_c6[size_h][key] += 1

    results_dict = {
        "C structurel": {"plan": plan_all, "nonplan": nonplan_all, "by_h": by_h_all},
        "C structurel + C6": {"plan": plan_c6, "nonplan": nonplan_c6, "by_h": by_h_c6},
    }
    return results_dict, h9_count_per_graph


def _replafond_h9(rows, target_per_graph):
    """Reproduit en memoire le plafond stratifie (seed=42) de
    plafond_h9_C1.py, applique ici sur les lignes deja 'done' de C1-h9.

    target_per_graph : dict {graph_name: target} -- la cible n'est PAS un
    200 fixe mais le nombre EXACT de solutions 'done' que Cstr a obtenu
    pour ce graphe precis (potentiellement < 200 si le dispatch a ete
    interrompu). Garantit len(selectionne pour ce graphe) <= target_per_graph
    [gname] <= Cstr[gname] -- donc C1 <= Cstr graphe par graphe, sans
    exception, meme si la couverture Cstr est incomplete.

    rows: liste de dict avec au moins 'graph_name' et 'csp_solution_json'.
    Retourne le sous-ensemble (meme objets) selectionne."""
    by_graph = {}
    for r in rows:
        by_graph.setdefault(r["graph_name"], []).append(r)

    selected = []
    rng = random.Random(H9_PLAFOND_SEED)
    for gname in sorted(by_graph.keys()):
        items = by_graph[gname]
        target = target_per_graph.get(gname, 0)
        if len(items) <= target:
            selected.extend(items)
            continue
        strata = {}
        for r in items:
            try:
                sig = signature(r["csp_solution_json"])
            except Exception:
                sig = (-1, -1)
            strata.setdefault(sig, []).append(r["sol_id"])
        keep_ids = stratified_sample(strata, target, rng)
        selected.extend(r for r in items if r["sol_id"] in keep_ids)
    return selected


def aggregate_c1(h9_count_per_graph):
    """Retourne dict avec compteurs pour 'C structurel + C5' et '+ C6 + C5'.

    Deux ecarts corriges pour une comparaison equitable a h9 avec Cstr :
    1. C1-h9 a ete plafonne a un seuil different (et plus large, ~267
       sols/graphe en moyenne, max 1670) que Cstr-h9 -> on reapplique un
       plafond stratifie (seed=42) en memoire (lecture seule sur la DB).
    2. La cible du plafond, par graphe, n'est PAS un 200 fixe mais le
       compte EXACT obtenu par Cstr pour ce graphe (potentiellement < 200
       si le dispatch Cstr a ete interrompu en cours de route) -> garantit
       C1 <= Cstr graphe par graphe, donc a toute taille h."""
    if not FINAL_DB.exists():
        print(f"  [ERREUR] DB introuvable : {FINAL_DB}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(FINAL_DB))
    conn.row_factory = sqlite3.Row

    rows_lt9 = conn.execute(
        "SELECT fs.sol_id, fs.size_h, fs.angle_deg, sf.adj_57 "
        "FROM final_solutions fs LEFT JOIN sol_features sf ON fs.sol_id = sf.sol_id "
        "WHERE fs.config='C1' AND fs.status='done' AND fs.size_h < 9"
    ).fetchall()

    rows_h9_raw = conn.execute(
        "SELECT fs.sol_id, fs.graph_name, fs.csp_solution_json, fs.angle_deg, sf.adj_57 "
        "FROM final_solutions fs LEFT JOIN sol_features sf ON fs.sol_id = sf.sol_id "
        "WHERE fs.config='C1' AND fs.status='done' AND fs.size_h = 9"
    ).fetchall()
    conn.close()

    rows_h9_all = [r for r in rows_h9_raw if r["graph_name"] in h9_count_per_graph]
    print("=== C1 (final_h3_h9.db) ===")
    print(f"  h9 done, graphes hors couverture Cstr (ecartes) : {len(rows_h9_raw) - len(rows_h9_all)}")

    n_h9_before = len(rows_h9_all)
    rows_h9 = _replafond_h9(rows_h9_all, h9_count_per_graph)
    print(f"  h3-h8 done (sans plafond, comme Cstr) : {len(rows_lt9)}")
    print(f"  h9 done avant replafond (graphes communs) : {n_h9_before}")
    print(f"  h9 done apres replafond (cible = compte exact Cstr/graphe) : {len(rows_h9)}")

    all_rows = list(rows_lt9) + list(rows_h9)

    def has57(r):
        return r["adj_57"] is not None and r["adj_57"] > 0

    def size_of(r):
        return r["size_h"] if "size_h" in r.keys() else 9

    plan_all = sum(1 for r in all_rows if r["angle_deg"] < ANGLE_THRESHOLD)
    nonplan_all = sum(1 for r in all_rows if r["angle_deg"] >= ANGLE_THRESHOLD)
    plan_c6 = sum(1 for r in all_rows if not has57(r) and r["angle_deg"] < ANGLE_THRESHOLD)
    nonplan_c6 = sum(1 for r in all_rows if not has57(r) and r["angle_deg"] >= ANGLE_THRESHOLD)

    by_h_all = _empty_by_h()
    by_h_c6 = _empty_by_h()
    for r in all_rows:
        h = size_of(r)
        key = "plan" if r["angle_deg"] < ANGLE_THRESHOLD else "nonplan"
        by_h_all[h][key] += 1
        if not has57(r):
            by_h_c6[h][key] += 1

    print(f"  C structurel + C5      : plan={plan_all} nonplan={nonplan_all}")
    print(f"  C structurel + C6 + C5 : plan={plan_c6} nonplan={nonplan_c6}")

    return {
        "C structurel + C5": {"plan": plan_all, "nonplan": nonplan_all, "by_h": by_h_all},
        "C structurel + C6 + C5": {"plan": plan_c6, "nonplan": nonplan_c6, "by_h": by_h_c6},
    }


def write_report(results):
    out_path = HERE / "rapport_resultats.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def manquees(sans_c5, avec_c5):
        return results[sans_c5]["plan"] - results[avec_c5]["plan"]

    lines = []
    lines.append("# Résultats agrégés — effet de la table de voisinage (C5)")
    lines.append("")
    lines.append(f"Généré le {now}. Seuil de planéité : dièdre < {ANGLE_THRESHOLD:.0f}°. "
                  "Totaux agrégés sur h3 à h9. Les solutions `status='failed'` "
                  "(reconstruction géométrique impossible) sont exclues de tous les comptes.")
    lines.append("")
    lines.append("## Slide 1 — C structurel vs C structurel + C5")
    lines.append("")
    lines.append("|  | C structurel | C structurel + C5 |")
    lines.append("|---|---|---|")
    lines.append(f"| Planes trouvées | {results['C structurel']['plan']} | {results['C structurel + C5']['plan']} |")
    lines.append(f"| Non-planes trouvées | {results['C structurel']['nonplan']} | {results['C structurel + C5']['nonplan']} |")
    lines.append(f"| Planes manquées | -- | {manquees('C structurel', 'C structurel + C5')} |")
    lines.append("")
    lines.append("## Slide 2 — C structurel + C6 vs C structurel + C6 + C5")
    lines.append("")
    lines.append("|  | C structurel + C6 | C structurel + C6 + C5 |")
    lines.append("|---|---|---|")
    lines.append(f"| Planes trouvées | {results['C structurel + C6']['plan']} | {results['C structurel + C6 + C5']['plan']} |")
    lines.append(f"| Non-planes trouvées | {results['C structurel + C6']['nonplan']} | {results['C structurel + C6 + C5']['nonplan']} |")
    lines.append(f"| Planes manquées | -- | {manquees('C structurel + C6', 'C structurel + C6 + C5')} |")
    lines.append("")
    lines.append("## Détail brut (agrégé)")
    lines.append("")
    for cfg, d in results.items():
        lines.append(f"- **{cfg}** : plan={d['plan']}  non-plan={d['nonplan']}")
    lines.append("")

    lines.append("## Détail par taille h (pour slides annexe)")
    lines.append("")
    lines.append("### Slide 1 détaillée — C structurel vs + C5")
    lines.append("")
    lines.append("| h | plan (Cstr) | nonplan (Cstr) | plan (+C5) | nonplan (+C5) | manquées |")
    lines.append("|---|---|---|---|---|---|")
    for h in range(3, 10):
        p1 = results["C structurel"]["by_h"][h]["plan"]
        n1 = results["C structurel"]["by_h"][h]["nonplan"]
        p2 = results["C structurel + C5"]["by_h"][h]["plan"]
        n2 = results["C structurel + C5"]["by_h"][h]["nonplan"]
        lines.append(f"| h{h} | {p1} | {n1} | {p2} | {n2} | {p1 - p2} |")
    lines.append("")
    lines.append("### Slide 2 détaillée — C structurel + C6 vs + C6 + C5")
    lines.append("")
    lines.append("| h | plan (+C6) | nonplan (+C6) | plan (+C6+C5) | nonplan (+C6+C5) | manquées |")
    lines.append("|---|---|---|---|---|---|")
    for h in range(3, 10):
        p1 = results["C structurel + C6"]["by_h"][h]["plan"]
        n1 = results["C structurel + C6"]["by_h"][h]["nonplan"]
        p2 = results["C structurel + C6 + C5"]["by_h"][h]["plan"]
        n2 = results["C structurel + C6 + C5"]["by_h"][h]["nonplan"]
        lines.append(f"| h{h} | {p1} | {n1} | {p2} | {n2} | {p1 - p2} |")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRapport ecrit : {out_path}")

    print("\n=== LATEX PRET A COPIER (slide annexe 1) ===")
    for h in range(3, 10):
        p1 = results["C structurel"]["by_h"][h]["plan"]
        n1 = results["C structurel"]["by_h"][h]["nonplan"]
        p2 = results["C structurel + C5"]["by_h"][h]["plan"]
        n2 = results["C structurel + C5"]["by_h"][h]["nonplan"]
        print(f"    $h_{h}$ & {p1:,} & {n1:,} & {p2:,} & {n2:,} & {p1-p2:,} \\\\".replace(",", "\\,"))

    print("\n=== LATEX PRET A COPIER (slide annexe 2) ===")
    for h in range(3, 10):
        p1 = results["C structurel + C6"]["by_h"][h]["plan"]
        n1 = results["C structurel + C6"]["by_h"][h]["nonplan"]
        p2 = results["C structurel + C6 + C5"]["by_h"][h]["plan"]
        n2 = results["C structurel + C6 + C5"]["by_h"][h]["nonplan"]
        print(f"    $h_{h}$ & {p1:,} & {n1:,} & {p2:,} & {n2:,} & {p1-p2:,} \\\\".replace(",", "\\,"))


def main():
    results = {}
    cstr_results, h9_count_per_graph = aggregate_cstr()
    results.update(cstr_results)
    results.update(aggregate_c1(h9_count_per_graph))

    print("\n=== RESULTATS FINAUX ===")
    for cfg, d in results.items():
        print(f"  {cfg:28s} plan={d['plan']:>8} nonplan={d['nonplan']:>8}")

    write_report(results)


if __name__ == "__main__":
    main()
