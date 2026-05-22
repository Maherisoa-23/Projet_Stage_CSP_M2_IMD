"""
E03 : Bordure -> Stabilite.
"""

from ..queries import pearson
from ..plots import bar_chart_svg


INTRO = """
<b>But :</b> savoir si la <b>forme de la bordure</b> de la molecule (les atomes
exterieurs) predit la planeite.<br><br>

<b>Concepts (issu de la these Varet, section 2.2) :</b><br>
- <b>Parametre d'irregularite</b> (Bouwman 2019) = quantite chimique mesurant la
"compacite" de la bordure. Calcule a partir des "groupes" de carbones consecutifs au
bord. Valeur entre 0 et 1 : 0 = bordure tres reguliere/compacte (beaucoup de symetries),
1 = bordure tres irreguliere.<br>
- <b>n_pent_at_boundary</b> = nombre de pentagones touchant le bord. Plus il y a de
pent en bord, plus on s'attend a une courbure positive (bowl).<br><br>

<b>Hypothese :</b> les bordures regulieres (irregularite proche de 0) devraient
correspondre a des structures plus planes. Les bordures avec beaucoup de
pent/hept en saillie devraient tordre la molecule.
"""


def _pct_plan_by_bucket(conn, column, h, buckets):
    out = []
    for lo, hi, label in buckets:
        sql = f"""
        SELECT
            SUM(CASE WHEN s.verdict='plan' THEN 1 ELSE 0 END) as n_plan,
            COUNT(*) as n_total
        FROM solution_descriptors d
        JOIN solutions s ON s.h=d.h AND s.config=d.config
                         AND s.mol=d.mol AND s.sol_idx=d.sol_idx
        WHERE s.verdict IN ('plan','non_plan')
          AND d.{column} IS NOT NULL
          AND d.{column} >= ? AND d.{column} < ?
        """
        params = [lo, hi]
        if h:
            sql += " AND d.h = ?"
            params.append(h)
        row = conn.execute(sql, params).fetchone()
        n_plan, n_total = row[0] or 0, row[1] or 0
        pct = 100 * n_plan / n_total if n_total > 0 else None
        out.append((label, pct, n_total))
    return out


def run(conn, h=None):
    title = f"E03 — Bordure x Stabilite{f' ({h})' if h else ''}"

    rho_irreg_angle = pearson(conn, "irregularity_param", "angle_deg",
                               h=h, verdict=None)

    irreg_buckets = [
        (0.0, 0.2, "0-0.2"),
        (0.2, 0.4, "0.2-0.4"),
        (0.4, 0.6, "0.4-0.6"),
        (0.6, 0.8, "0.6-0.8"),
        (0.8, 1.01, "0.8-1.0"),
    ]
    irreg_pct = _pct_plan_by_bucket(conn, "irregularity_param", h, irreg_buckets)
    irreg_bars = [(lbl, pct if pct is not None else 0) for lbl, pct, _n in irreg_pct]

    sql = """
    SELECT d.n_pent_at_boundary,
           SUM(CASE WHEN s.verdict='plan' THEN 1 ELSE 0 END) as n_plan,
           COUNT(*) as n_total
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict IN ('plan','non_plan')
    """
    params = []
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " GROUP BY d.n_pent_at_boundary ORDER BY d.n_pent_at_boundary"
    pent_b_pct = []
    for r in conn.execute(sql, params):
        if r[2] >= 5:
            pent_b_pct.append((str(r[0]), 100.0 * r[1] / r[2]))

    sql_hept = sql.replace("n_pent_at_boundary", "n_hept_at_boundary")
    hept_b_pct = []
    for r in conn.execute(sql_hept, params):
        if r[2] >= 5:
            hept_b_pct.append((str(r[0]), 100.0 * r[1] / r[2]))

    summary = []
    if rho_irreg_angle is not None:
        sign = "POSITIVE" if rho_irreg_angle > 0.1 else (
            "NEGATIVE" if rho_irreg_angle < -0.1 else "QUASI-NULLE"
        )
        summary.append(
            f"Correlation <b>irregularite x angle_deg</b> (sur plan+non_plan) : "
            f"<b>{rho_irreg_angle:+.3f}</b> ({sign}).")
        if rho_irreg_angle > 0.1:
            summary.append(
                "&rarr; plus la bordure est irreguliere, plus la molecule est tordue.")
        elif rho_irreg_angle < -0.1:
            summary.append(
                "&rarr; les bordures irregulieres semblent <b>plus planes</b>.")
        else:
            summary.append("&rarr; pas de lien clair.")

    rows_pct = []
    for lbl, pct, n in irreg_pct:
        pct_str = f"{pct:.1f}%" if pct is not None else "n/a"
        rows_pct.append([lbl, str(n), pct_str])

    return {
        "title": title,
        "intro": INTRO,
        "summary": "<br>".join(summary),
        "plots": [
            {
                "title": "% plan par bucket d'irregularite",
                "description":
                    "On classe les solutions en 5 buckets selon leur "
                    "irregularity_param, puis on affiche la fraction de chaque "
                    "bucket qui est verdict='plan'.",
                "svg": bar_chart_svg(irreg_bars, y_label="% plan", color="plan"),
                "interpretation":
                    "Une barre haute = la majorite des sols dans ce bucket sont plans. "
                    "Si la tendance est decroissante (vers la droite), les bordures "
                    "irregulieres sont moins planes. Si plate, l'irregularite n'a pas "
                    "d'effet observable.",
            },
            {
                "title": "% plan par nombre de pent au bord",
                "description":
                    "Combien de % de solutions sont planes selon le nombre de "
                    "pentagones qui touchent la bordure de la molecule.",
                "svg": bar_chart_svg(pent_b_pct, y_label="% plan", color="primary"),
                "interpretation":
                    "Les pentagones induisent une courbure positive (forme bol). "
                    "Si la barre baisse a mesure que n_pent_at_boundary monte, "
                    "ca confirme l'effet \"bowl\" des pent en bord.",
            },
            {
                "title": "% plan par nombre de hept au bord",
                "description":
                    "Idem mais avec les heptagones (courbure negative attendue).",
                "svg": bar_chart_svg(hept_b_pct, y_label="% plan", color="warm_high"),
                "interpretation":
                    "Les heptagones induisent une courbure negative (forme selle). "
                    "Si la barre baisse aussi, ca confirme l'effet \"saddle\" des "
                    "hept en bord.",
            },
        ],
        "tables": [
            {
                "title": "Repartition % plan par bucket d'irregularite",
                "headers": ["irregularite", "n_sols", "% plan"],
                "rows": rows_pct,
            }
        ],
    }
