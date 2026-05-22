"""
E02 : Topologie -> Aromaticite.
"""

from ..queries import mean_metric_by_5_7
from ..plots import heatmap_svg


INTRO = """
<b>But :</b> comprendre quelles compositions (n_pent, n_hept) developpent le plus
d'aromaticite (nombre de Clar eleve, RBO hex proche de 3).<br><br>

<b>Rappel :</b><br>
- <b>Clar number</b> = nb max de sextets aromatiques places sur les hexagones de la molecule.
Compris entre 0 (aucun rond) et le nb d'hex max (1 par hex possible).<br>
- <b>CBO hex moyen</b> = aromaticite locale moyenne des hexagones. Valeur ideale 3 (benzene pur).
NULL pour les molecules radicalaires (sans Kekule stricte).<br>
- <b>n_azulene_units</b> = paires 5+7 fusionnees par arete (motif azulene, polaire, aromatique).<br><br>

<b>Hypothese :</b> les compositions tres riches en hex avec quelques 5/7 bien places
maximiseront l'aromaticite. Les compositions pent-pent ou hept-hept devraient avoir
moins de Clar (et plus de radicaux).
"""


def run(conn, h=None):
    title = f"E02 — Topologie x Aromaticite{f' ({h})' if h else ''}"

    clar_per_cell = mean_metric_by_5_7(conn, "clar_number", h=h, verdict="plan")
    cbo_per_cell = mean_metric_by_5_7(conn, "cbo_mean_hex", h=h, verdict="plan")
    azu_per_cell = mean_metric_by_5_7(conn, "n_azulene_units", h=h, verdict="plan")

    hm_clar = heatmap_svg(
        clar_per_cell,
        x_label="n_pentagones", y_label="n_heptagones",
        title="Clar_number moyen (sur plans)",
        cmap="warm", value_format=".2f",
    )
    hm_cbo = heatmap_svg(
        cbo_per_cell,
        x_label="n_pentagones", y_label="n_heptagones",
        title="cbo_mean_hex moyen (sur plans)",
        cmap="warm", value_format=".2f",
    )
    hm_azu = heatmap_svg(
        azu_per_cell,
        x_label="n_pentagones", y_label="n_heptagones",
        title="n_azulene_units moyen (sur plans)",
        cmap="cool", value_format=".1f",
    )

    summary_parts = []
    if clar_per_cell:
        max_clar_cell = max(clar_per_cell.items(), key=lambda kv: kv[1])
        summary_parts.append(
            f"Cellule la plus aromatique (Clar moyen max) : <b>{max_clar_cell[0]}</b> "
            f"a {max_clar_cell[1]:.2f} sextets en moyenne."
        )
    if cbo_per_cell:
        max_cbo_cell = max(cbo_per_cell.items(), key=lambda kv: kv[1])
        summary_parts.append(
            f"Cellule au CBO hex max : <b>{max_cbo_cell[0]}</b> a "
            f"{max_cbo_cell[1]:.2f}/3 (3 = benzene).")
    if azu_per_cell:
        max_azu_cell = max(azu_per_cell.items(), key=lambda kv: kv[1])
        summary_parts.append(
            f"Cellule avec le plus d'unites azulene : <b>{max_azu_cell[0]}</b> "
            f"a {max_azu_cell[1]:.1f}.")

    return {
        "title": title,
        "intro": INTRO,
        "summary": "<br>".join(summary_parts),
        "plots": [
            {
                "title": "Clar_number moyen par composition",
                "description":
                    "Moyenne du nombre de Clar (max de sextets aromatiques places) "
                    "sur les solutions plan de chaque cellule.",
                "svg": hm_clar,
                "interpretation":
                    "<b>Rouge fonce</b> = cellules tres aromatiques (plusieurs sextets "
                    "en moyenne). <b>Jaune pale</b> = peu/pas de sextets. "
                    "Les cellules avec beaucoup d'hex (haut-gauche de la grille) sont "
                    "typiquement plus rouges.",
            },
            {
                "title": "CBO hex moyen par composition",
                "description":
                    "Moyenne du RBO moyen sur les hexagones (aromaticite locale Pauling). "
                    "Valeur 0 a 3 : plus c'est haut, plus les hex sont aromatiques.",
                "svg": hm_cbo,
                "interpretation":
                    "<b>Rouge fonce ~ 2.5-3.0</b> = hex tres aromatiques (comme benzene). "
                    "<b>Jaune pale</b> = hex peu aromatiques (souvent dans les molecules "
                    "radicalaires). NB : les molecules radicalaires sont exclues (CBO NULL).",
            },
            {
                "title": "n_azulene_units moyen par composition",
                "description":
                    "Combien d'unites azulene (paire 5+7 partageant une arete) la molecule "
                    "contient en moyenne. C'est un proxy de la polarite (cf litterature).",
                "svg": hm_azu,
                "interpretation":
                    "<b>Bleu fonce</b> = beaucoup d'unites azulene -> candidats pour la "
                    "polarite/transfert de charge. Naturellement les cellules avec autant "
                    "de 5 que de 7 (diagonale) en auront le plus.",
            },
        ],
        "tables": [],
    }
