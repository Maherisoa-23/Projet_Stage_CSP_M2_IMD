"""
E06 : Top candidates par famille.
"""


INTRO = """
<b>But :</b> sortir les <b>structures concretes les plus interessantes</b>
a montrer aux chimistes. 3 categories :<br><br>

<b>Plans + aromatiques (Top 20)</b> : structures planes (angle MD <= 5deg) avec
au moins 2 sextets de Clar. Triees par Clar decroissant. <i>Candidates pour
materiaux stables / optoelectroniques / transport de charge.</i><br><br>

<b>Plans + radicalaires (Top 20)</b> : structures planes avec au moins 1 radical.
Triees par n_radicals decroissant. <i>Candidates pour magnetisme moleculaire /
spintronique (cf. Liu &amp; Feng 2020).</i><br><br>

<b>Plans + courbees mais aromatiques (Top 20)</b> : structures qui passent le verdict
plan MD (angle <= 10deg) mais ont une courbure 3D residuelle (buckling > 0.3 A),
avec quand meme Clar >= 2. <i>Candidates rares : forme bowl/saddle ET aromaticite
preservee.</i><br><br>

Chaque ligne identifie une solution unique par (h, config, mol, sol_idx). Tu peux
ouvrir n'importe laquelle dans le viewer 3D pour la regarder en detail.
"""


def _top_aromatic_planar(conn, h=None, k=20):
    sql = """
    SELECT d.h, d.config, d.mol, d.sol_idx, s.sizes, s.angle_deg,
           d.clar_number, d.n_clar_covers, d.cbo_mean_hex,
           d.n_radicals, d.n_pent, d.n_hex, d.n_hept
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict='plan' AND d.clar_number >= 2
      AND s.angle_deg <= 5.0
    """
    params = []
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " ORDER BY d.clar_number DESC, s.angle_deg ASC LIMIT ?"
    params.append(k)
    return conn.execute(sql, params).fetchall()


def _top_radical_planar(conn, h=None, k=20):
    sql = """
    SELECT d.h, d.config, d.mol, d.sol_idx, s.sizes, s.angle_deg,
           d.n_radicals, d.clar_number, d.n_kekule,
           d.n_pent, d.n_hex, d.n_hept
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict='plan' AND d.n_radicals >= 1
      AND s.angle_deg <= 5.0
    """
    params = []
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " ORDER BY d.n_radicals DESC, s.angle_deg ASC LIMIT ?"
    params.append(k)
    return conn.execute(sql, params).fetchall()


def _top_curved_aromatic(conn, h=None, k=20):
    sql = """
    SELECT d.h, d.config, d.mol, d.sol_idx, s.sizes,
           d.buckling_height, d.curvature_discrete_max, d.clar_number,
           d.n_pent, d.n_hex, d.n_hept, s.angle_deg
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict='plan' AND d.clar_number >= 2
      AND d.buckling_height > 0.3
    """
    params = []
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " ORDER BY d.buckling_height DESC LIMIT ?"
    params.append(k)
    return conn.execute(sql, params).fetchall()


def run(conn, h=None):
    title = f"E06 — Top candidates{f' ({h})' if h else ''}"

    rows1 = _top_aromatic_planar(conn, h=h)
    rows2 = _top_radical_planar(conn, h=h)
    rows3 = _top_curved_aromatic(conn, h=h)

    def _fmt(r, fmts):
        out = []
        for i, fm in enumerate(fmts):
            v = r[i]
            if fm == "f":
                out.append(f"{v:.3f}" if v is not None else "")
            else:
                out.append(str(v) if v is not None else "")
        return out

    t1 = {
        "title": "Top 20 plans + aromatiques (candidates stables / optoelectroniques)",
        "headers": ["h", "config", "mol", "sol", "sizes", "angle°",
                    "Clar", "n_covers", "CBO_hex", "rad", "pent", "hex", "hept"],
        "rows": [_fmt(r, ["s","s","s","s","s","f","s","s","f","s","s","s","s"]) for r in rows1],
    }
    t2 = {
        "title": "Top 20 plans + radicalaires (candidates magnetisme moleculaire)",
        "headers": ["h", "config", "mol", "sol", "sizes", "angle°",
                    "rad", "Clar", "n_kekule", "pent", "hex", "hept"],
        "rows": [_fmt(r, ["s","s","s","s","s","f","s","s","s","s","s","s"]) for r in rows2],
    }
    t3 = {
        "title": "Top 20 plans + courbes mais aromatiques (candidates bowl/saddle aromatiques)",
        "headers": ["h", "config", "mol", "sol", "sizes",
                    "buckling A", "curv_max°", "Clar",
                    "pent", "hex", "hept", "angle°"],
        "rows": [_fmt(r, ["s","s","s","s","s","f","f","s","s","s","s","f"]) for r in rows3],
    }

    summary = (
        f"<b>{len(rows1)}</b> candidates plans+aromatiques | "
        f"<b>{len(rows2)}</b> plans+radicalaires | "
        f"<b>{len(rows3)}</b> plans+courbes-aromatiques."
    )

    return {
        "title": title,
        "intro": INTRO,
        "summary": summary,
        "plots": [],
        "tables": [t1, t2, t3],
    }
