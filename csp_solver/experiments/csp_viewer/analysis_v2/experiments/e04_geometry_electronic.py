"""
E04 : Geometrie 3D -> Electronique.
"""

from ..queries import pearson
from ..plots import scatter_svg


INTRO = """
<b>But :</b> verifier si la <b>courbure 3D</b> de la molecule (mesuree apres
optimisation xTB) influe sur son electronique (aromaticite, radicaux).<br><br>

<b>Concepts :</b><br>
- <b>curvature_discrete_mean</b> = angle moyen entre les normales de cycles voisins.
0deg = plat parfait. ~30deg = courbure marquee (forme bol/selle).<br>
- <b>buckling_height</b> = deviation max d'un atome au plan moyen (en Angstrom).
0 A = plat ; > 0.5 A = clairement courbe.<br>
- <b>Clar_number, cbo_mean_hex, n_radicals</b> = indicateurs electroniques.<br><br>

<b>Hypothese (litterature, fullerenes) :</b> plus une molecule est courbee, moins
l'aromaticite est forte (les orbitales p ne se recouvrent plus aussi bien).
On s'attend a une correlation <b>negative</b> entre courbure et Clar/CBO.<br>
Pour les radicaux : pas d'hypothese claire dans la litterature, c'est exploratoire.
"""


def run(conn, h=None):
    title = f"E04 — Geometrie 3D x Electronique{f' ({h})' if h else ''}"

    rho_curv_clar = pearson(conn, "curvature_discrete_mean", "clar_number",
                              h=h, verdict="plan")
    rho_buck_cbo = pearson(conn, "buckling_height", "cbo_mean_hex",
                            h=h, verdict="plan")
    rho_curv_radicals = pearson(conn, "curvature_discrete_mean", "n_radicals",
                                  h=h, verdict=None)

    def _interp(rho):
        if rho is None:
            return "n/a"
        if abs(rho) < 0.1: return "FAIBLE (pas de lien)"
        return "NEGATIVE (courbure ↓ -> aromaticite ↑)" if rho < 0 else "POSITIVE"

    summary = []
    if rho_curv_clar is not None:
        summary.append(
            f"Pearson <b>curvature x Clar</b> (sur plans) : <b>{rho_curv_clar:+.3f}</b> "
            f"({_interp(rho_curv_clar)})")
    if rho_buck_cbo is not None:
        summary.append(
            f"Pearson <b>buckling x CBO hex</b> (sur plans) : <b>{rho_buck_cbo:+.3f}</b> "
            f"({_interp(rho_buck_cbo)})")
    if rho_curv_radicals is not None:
        summary.append(
            f"Pearson <b>curvature x n_radicals</b> (toutes sols) : "
            f"<b>{rho_curv_radicals:+.3f}</b> ({_interp(rho_curv_radicals)})")

    sql = """
    SELECT d.curvature_discrete_mean, d.cbo_mean_hex, s.verdict
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE d.curvature_discrete_mean IS NOT NULL
      AND d.cbo_mean_hex IS NOT NULL
      AND s.verdict IN ('plan','non_plan')
    """
    params = []
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " LIMIT 5000"
    points = []
    for r in conn.execute(sql, params):
        color = "plan" if r[2] == "plan" else "non_plan"
        points.append((r[0], r[1], color))

    scatter = scatter_svg(
        points,
        x_label="curvature_discrete_mean (deg)",
        y_label="cbo_mean_hex",
        title="Courbure x CBO hex (vert=plan, rouge=non_plan)",
        point_size=1.8, opacity=0.35,
    )

    return {
        "title": title,
        "intro": INTRO,
        "summary": "<br>".join(summary),
        "plots": [
            {
                "title": "Courbure 3D vs aromaticite (CBO hex)",
                "description":
                    "Chaque point = une solution. X = courbure 3D moyenne (deg), "
                    "Y = CBO hex moyen. Verts = plan, rouges = non_plan. "
                    "Limite a 5000 points pour la lisibilite.",
                "svg": scatter,
                "interpretation":
                    "Si les points <b>descendent vers la droite</b> (forme \\), "
                    "ca confirme la litterature : courbure ↑ -> aromaticite ↓. "
                    "Une separation visible verts/rouges = la courbure marque "
                    "aussi la planeite (attendu). Un nuage diffus = pas de lien clair.",
            },
        ],
        "tables": [],
    }
