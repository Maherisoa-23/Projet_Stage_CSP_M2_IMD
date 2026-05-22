"""
E01 : Topologie -> Planeite.
"""

from ..queries import heatmap_n_by_5_7, percent_plan_by_5_7
from ..plots import heatmap_svg


INTRO = """
<b>But :</b> savoir si la <b>composition en cycles (nombre de pentagones, nombre d'heptagones)</b>
predit la planeite de la molecule apres optimisation xTB.<br><br>

<b>Hypotheses chimiques :</b>
Les pentagones induisent une courbure positive (forme "bol"), les heptagones une courbure
negative (forme "selle"). Quand on en combine, la courbure peut se compenser et donner du
plan. On cherche les cellules ou la combinaison "marche".<br><br>

<b>Comment ca a ete calcule :</b>
Pour chaque cellule de la grille (n_pent, n_hept), on prend toutes les solutions
correspondantes, on calcule la fraction de celles dont le verdict MD est 'plan'.
On exige >= 5 sols pour qu'une cellule soit reportee.
"""


def run(conn, h=None):
    n_per_cell = heatmap_n_by_5_7(conn, h=h)
    pct_per_cell = percent_plan_by_5_7(conn, h=h, min_count=5)

    title = f"E01 — Topologie x Planeite{f' ({h})' if h else ''}"

    heatmap_pct = heatmap_svg(
        pct_per_cell,
        x_label="n_pentagones",
        y_label="n_heptagones",
        title="% solutions plan par (n_pent, n_hept)",
        vmin=0, vmax=100,
        cmap="diverge",
        value_format=".0f",
    )
    import math
    n_log = {k: math.log10(v) if v > 0 else 0 for k, v in n_per_cell.items()}
    heatmap_count = heatmap_svg(
        n_log,
        x_label="n_pentagones",
        y_label="n_heptagones",
        title="log10(nb solutions) par cellule (taille de l'echantillon)",
        cmap="cool",
        value_format=".1f",
    )

    sorted_cells = sorted(n_per_cell.items(), key=lambda kv: -kv[1])
    top_cells = sorted_cells[:8]
    rows = []
    for (p, hept), n in top_cells:
        pct = pct_per_cell.get((p, hept))
        pct_str = f"{pct:.1f}%" if pct is not None else "n/a"
        rows.append([str(p), str(hept), str(n), pct_str])

    stable_cells = [(k, v) for k, v in pct_per_cell.items()
                     if v >= 90 and n_per_cell.get(k, 0) >= 20]
    unstable_cells = [(k, v) for k, v in pct_per_cell.items()
                       if v <= 30 and n_per_cell.get(k, 0) >= 20]
    summary = (
        f"<b>{len(pct_per_cell)}</b> cellules (n_pent, n_hept) avec >=5 sols. "
        f"<b>{len(stable_cells)}</b> cellules a >=90% plan (sur >=20 sols), "
        f"<b>{len(unstable_cells)}</b> cellules a <=30% plan."
    )

    return {
        "title": title,
        "intro": INTRO,
        "summary": summary,
        "plots": [
            {
                "title": "% solutions plan par (n_pent, n_hept)",
                "description":
                    "Chaque case = une composition (n_pent x_axis, n_hept y_axis). "
                    "La couleur indique le pourcentage de molecules planes apres MD.",
                "svg": heatmap_pct,
                "interpretation":
                    "<b>Rouge fonce</b> = ~100% plan (composition tres stable). "
                    "<b>Bleu fonce</b> = ~0% plan (composition tordue par construction). "
                    "<b>Blanc</b> ~50% plan (cas intermediaire). "
                    "Les cellules vides = pas assez de donnees (n < 5).",
            },
            {
                "title": "log10(taille de l'echantillon) par cellule",
                "description":
                    "Pour interpreter le heatmap precedent il faut savoir COMBIEN de "
                    "solutions chaque cellule contient. Ce 2e heatmap montre cela en "
                    "echelle log : valeur 2 = 100 sols, 3 = 1000 sols, etc.",
                "svg": heatmap_count,
                "interpretation":
                    "Les cellules avec une couleur plus foncee (bleu fonce) sont les "
                    "compositions LES PLUS FREQUENTES dans nos donnees. "
                    "Une cellule avec %plan extreme mais peu de donnees doit etre "
                    "regardee avec prudence (non significatif statistiquement).",
            },
        ],
        "tables": [
            {
                "title": "Top 8 cellules par nombre de solutions (compositions dominantes)",
                "headers": ["n_pent", "n_hept", "n_sols", "% plan"],
                "rows": rows,
            }
        ],
    }
