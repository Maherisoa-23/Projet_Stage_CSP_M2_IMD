"""
E05 : Localisation des radicaux.
"""

from ..plots import bar_chart_svg


INTRO = """
<b>But :</b> savoir <b>ou</b> tombent les electrons radicalaires des molecules
non-Kekuleennes (n_radicals > 0). Question chimique posee par Liu & Feng (2020) :
les radicaux sont-ils preferentiellement sur les pent, sur les hept, sur les hex,
sur la bordure ?<br><br>

<b>Concepts :</b><br>
- <b>radical_on_pent_freq</b> = sur les configurations radicalaires enumerees,
fraction des radicaux tombant sur un atome de pentagone. Idem hex/hept/bordure.<br>
- Pour les molecules NON-radicalaires (n_radicals = 0), ces champs sont NULL.
On filtre donc uniquement les radicalaires.<br><br>

<b>Hypothese :</b> les radicaux devraient preferentiellement tomber sur les sites
de "stress topologique" : pentagones (electron en trop) ou bord. Les heptagones
electronquerement peuvent aussi en attirer ("recovery of aromaticity" : creer un
radical libere un tropylium aromatique a 6 electrons sur le 7-ring).<br><br>

<b>Note :</b> un atome peut appartenir a plusieurs cycles, donc pent+hex+hept
peut depasser 1 (chaque rad est compte dans tous ses cycles).
"""


def run(conn, h=None):
    title = f"E05 — Localisation des radicaux{f' ({h})' if h else ''}"

    sql = """
    SELECT
        AVG(radical_on_pent_freq),
        AVG(radical_on_hex_freq),
        AVG(radical_on_hept_freq),
        AVG(radical_at_boundary_freq),
        COUNT(*) as n
    FROM solution_descriptors
    WHERE n_radicals > 0
      AND radical_on_pent_freq IS NOT NULL
    """
    params = []
    if h:
        sql += " AND h = ?"
        params.append(h)
    row = conn.execute(sql, params).fetchone()
    pent_freq = row[0] or 0
    hex_freq = row[1] or 0
    hept_freq = row[2] or 0
    boundary_freq = row[3] or 0
    n_sols = row[4] or 0

    summary = (
        f"Statistiques sur <b>{n_sols} solutions radicalaires</b>. "
        f"Frequence radicaux par site : "
        f"pent <b>{pent_freq:.3f}</b>, "
        f"hex <b>{hex_freq:.3f}</b>, "
        f"hept <b>{hept_freq:.3f}</b>, "
        f"bordure <b>{boundary_freq:.3f}</b>."
    )

    bars_size = [
        ("pent", pent_freq),
        ("hex", hex_freq),
        ("hept", hept_freq),
    ]
    bars_b = [
        ("bord", boundary_freq),
        ("interieur", 1.0 - boundary_freq),
    ]

    sql2 = "SELECT n_radicals, COUNT(*) FROM solution_descriptors"
    p2 = []
    if h:
        sql2 += " WHERE h = ?"
        p2.append(h)
    sql2 += " GROUP BY n_radicals ORDER BY n_radicals"
    dist_rad = [(str(r[0]), r[1]) for r in conn.execute(sql2, p2)]

    return {
        "title": title,
        "intro": INTRO,
        "summary": summary,
        "plots": [
            {
                "title": "Frequence radicaux par type de cycle hote",
                "description":
                    "Moyenne de la frequence d'apparition d'un radical dans un cycle "
                    "de chaque taille (pentagone, hexagone, heptagone). Calcule sur les "
                    "solutions radicalaires uniquement.",
                "svg": bar_chart_svg(bars_size, y_label="frequence", color="radical"),
                "interpretation":
                    "La barre la plus haute = cycles qui \"attirent\" preferentiellement "
                    "les radicaux. Si <b>pent > hept >> hex</b>, ca confirme l'hypothese "
                    "que les radicaux se localisent sur les sites de stress topologique. "
                    "Si <b>hept eleve</b>, c'est l'effet \"tropylium aromatique\" "
                    "(recovery of aromaticity).",
            },
            {
                "title": "Repartition bord vs interieur",
                "description":
                    "Fraction des radicaux qui tombent sur les atomes de bordure vs "
                    "les atomes interieurs.",
                "svg": bar_chart_svg(bars_b, y_label="frequence", color="muted"),
                "interpretation":
                    "Si \"bord\" >> \"interieur\", les radicaux sont preferentiellement "
                    "exposes (reactivite chimique forte). C'est le cas attendu pour les "
                    "PAH avec radicaux stables.",
            },
            {
                "title": "Distribution n_radicals (TOUTES solutions)",
                "description":
                    "Combien de solutions ont 0 radical, 1 radical, 2 radicaux, etc. "
                    "Pas filtree par verdict.",
                "svg": bar_chart_svg(dist_rad, y_label="nb solutions", color="primary"),
                "interpretation":
                    "Le pic est typiquement a 0 (la plupart sont Kekule strictes) ou 1 "
                    "(parite forcee par les 5/7). Une queue a 2-3 = molecules a forte "
                    "instabilite (candidats interessants pour magnetisme moleculaire).",
            },
        ],
        "tables": [],
    }
