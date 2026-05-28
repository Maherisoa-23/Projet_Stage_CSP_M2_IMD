"""
E07 : Scaling h6 -> h9.
"""

from ..plots import bar_chart_svg


INTRO = """
<b>But :</b> comparer les <b>quatre tailles</b> (h6, h7, h8, h9) sur tous les
indicateurs pour voir comment ils evoluent avec la complexite croissante.<br><br>

<b>Questions chimiques sous-jacentes :</b><br>
- Le <b>% de structures planes</b> baisse-t-il avec la taille ? (plus grand = plus
de contraintes geometriques)<br>
- Le <b>Clar moyen</b> augmente-t-il ? (plus d'hex disponibles pour des sextets)<br>
- Le <b>n_radicals moyen</b> augmente-t-il ou diminue-t-il ?<br>
- Le <b>buckling moyen</b> (deviation 3D) augmente-t-il ? (les grosses molecules
plient plus)<br><br>

<b>Note :</b> cette section utilise <b>l'ensemble des donnees</b>, peu importe le
filtre h du rapport (pour permettre la comparaison cross-h).
"""


def run(conn, h=None):
    title = "E07 — Scaling h6 -> h9"

    sql = """
    SELECT d.h,
        COUNT(*) as n_total,
        SUM(CASE WHEN s.verdict='plan' THEN 1 ELSE 0 END) as n_plan,
        AVG(d.clar_number) as mean_clar,
        AVG(CAST(d.n_radicals AS REAL)) as mean_rad,
        AVG(d.cbo_mean_hex) as mean_cbo,
        AVG(d.buckling_height) as mean_buckling,
        AVG(d.curvature_discrete_mean) as mean_curv,
        AVG(d.n_azulene_units) as mean_azu,
        AVG(d.irregularity_param) as mean_irreg
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict IN ('plan','non_plan')
    GROUP BY d.h
    ORDER BY d.h
    """
    rows = conn.execute(sql).fetchall()

    pct_plan = [(r[0], 100.0 * r[2] / r[1] if r[1] else 0) for r in rows]
    mean_clar = [(r[0], r[3] or 0) for r in rows]
    mean_rad = [(r[0], r[4] or 0) for r in rows]
    mean_buck = [(r[0], r[6] or 0) for r in rows]
    mean_azu = [(r[0], r[8] or 0) for r in rows]

    headers = ["h", "n_evaluees", "% plan", "mean_clar", "mean_rad",
                "mean_cbo_hex", "mean_buckling", "mean_curvature",
                "mean_azulene", "mean_irreg"]
    tbl_rows = []
    for r in rows:
        tbl_rows.append([
            r[0], str(r[1]),
            f"{100.0*r[2]/r[1]:.1f}%" if r[1] else "",
            f"{r[3]:.2f}" if r[3] is not None else "",
            f"{r[4]:.2f}" if r[4] is not None else "",
            f"{r[5]:.2f}" if r[5] is not None else "",
            f"{r[6]:.3f}" if r[6] is not None else "",
            f"{r[7]:.2f}" if r[7] is not None else "",
            f"{r[8]:.2f}" if r[8] is not None else "",
            f"{r[9]:.3f}" if r[9] is not None else "",
        ])

    summary = (
        f"Caracteristiques moyennes sur les <b>{sum(r[1] for r in rows)} solutions</b> "
        f"plan+non_plan, reparties sur h6 a h9."
    )

    return {
        "title": title,
        "intro": INTRO,
        "summary": summary,
        "plots": [
            {
                "title": "% solutions plan par h",
                "description": "Fraction de solutions verdict='plan' a chaque taille.",
                "svg": bar_chart_svg(pct_plan, y_label="% plan", color="plan"),
                "interpretation":
                    "Si la courbe descend de h6 a h9, la complexite croissante reduit "
                    "la planeite (attendu intuitivement). Si stable ou croissante, "
                    "les structures plus grandes sont aussi planes (intuition contraire).",
            },
            {
                "title": "Clar moyen par h",
                "description":
                    "Nombre moyen de sextets aromatiques places. Compte 0 quand pas d'hex.",
                "svg": bar_chart_svg(mean_clar, y_label="Clar", color="primary"),
                "interpretation":
                    "Doit monter avec h (plus d'hex disponibles). La pente indique a "
                    "quel point l'aromaticite s'echelonne avec la taille.",
            },
            {
                "title": "n_radicals moyen par h",
                "description":
                    "Nombre moyen de radicaux par solution.",
                "svg": bar_chart_svg(mean_rad, y_label="rad", color="radical"),
                "interpretation":
                    "Si monte : plus de radicaux dans les grosses molecules (effet "
                    "de structure). Si stable : la radicalite est gouvernee par la "
                    "parite des 5/7 pas par la taille.",
            },
            {
                "title": "Buckling moyen par h (A)",
                "description":
                    "Deviation 3D maximum moyenne au plan moyen. 0 = parfaitement plat.",
                "svg": bar_chart_svg(mean_buck, y_label="A", color="warm_high"),
                "interpretation":
                    "Si monte : les grosses molecules sont plus tordues meme apres "
                    "filtrage MD. C'est l'effet de la taille sur la conformation.",
            },
            {
                "title": "n_azulene_units moyen par h",
                "description":
                    "Nombre moyen d'unites azulene (paires 5+7 fusionnees par arete).",
                "svg": bar_chart_svg(mean_azu, y_label="azu", color="cool_high"),
                "interpretation":
                    "Doit monter avec h (plus de combinaisons possibles). Indique a "
                    "quel point on est dans le regime non-benzenoide vrai.",
            },
        ],
        "tables": [
            {"title": "Recap detaille par h",
             "headers": headers, "rows": tbl_rows},
        ],
    }
