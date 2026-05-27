"""
Requetes d'analyse sur topology_metrics joint a solutions.

Chaque fonction retourne soit une liste de dicts (pour iteration / CSV),
soit un dict de stats. Pas d'effet de bord : aucune ecriture en DB.

Usage typique :
    import sqlite3
    from experiments.viewer.analysis.queries import (
        plan_solutions_with_metrics,
        top_aromatic_planar,
    )
    conn = sqlite3.connect("db_v2.db")
    for row in plan_solutions_with_metrics(conn, h="h6"):
        print(row)
"""

import sqlite3
from typing import Iterator, List, Optional


def plan_solutions_with_metrics(conn: sqlite3.Connection,
                                h: Optional[str] = None,
                                limit: Optional[int] = None
                                ) -> List[sqlite3.Row]:
    """Toutes les solutions avec verdict in ('plan','non_plan') jointes a
    leurs metriques topologiques.

    Colonnes retournees : h, config, mol, sol_idx, sizes, verdict,
      angle_deg, planar, n_kekule, n_radicals, clar_number,
      n_clar_covers, cbo_available, cbo_mean_hex, cbo_max_hex,
      cbo_mean_pent, cbo_mean_hept, n_hex, n_pent, n_hept.
    """
    conn.row_factory = sqlite3.Row
    sql = (
        "SELECT s.h, s.config, s.mol, s.sol_idx, s.sizes, s.verdict, "
        "       s.angle_deg, s.planar, "
        "       t.n_kekule, t.is_exact, t.n_radicals, "
        "       t.clar_number, t.n_clar_covers, "
        "       t.cbo_available, t.cbo_mean_hex, t.cbo_max_hex, "
        "       t.cbo_mean_pent, t.cbo_mean_hept, "
        "       t.n_hex, t.n_pent, t.n_hept "
        "FROM solutions s "
        "JOIN topology_metrics t USING (h, config, mol, sol_idx) "
        "WHERE s.verdict IN ('plan','non_plan')"
    )
    params = []
    if h is not None:
        sql += " AND s.h = ?"
        params.append(h)
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def summary_by_h(conn: sqlite3.Connection,
                 h: Optional[str] = None) -> List[sqlite3.Row]:
    """Stats agregees par h. Renvoie une ligne par h avec :
       n_evaluees, n_plans, n_non_plans, mean_clar, mean_radicals,
       mean_n_kekule, mean_cbo_hex (sur les non-radicalaires).

    Si h est fourni, ne retourne que les stats de ce h (et c'est
    fortement plus rapide car on evite le scan global de solutions).

    Note de perf : la requete part de topology_metrics (au plus quelques
    milliers de lignes par h) puis joint vers solutions via la PK.
    L'ordre opposé (s JOIN t) faisait scanner les 6M de solutions et
    rendait la requete intractable.
    """
    conn.row_factory = sqlite3.Row
    sql = """
    SELECT t.h,
           COUNT(*) as n_evaluees,
           SUM(CASE WHEN s.verdict='plan'     THEN 1 ELSE 0 END) as n_plans,
           SUM(CASE WHEN s.verdict='non_plan' THEN 1 ELSE 0 END) as n_non_plans,
           AVG(t.clar_number)              as mean_clar,
           AVG(CAST(t.n_radicals AS REAL)) as mean_radicals,
           AVG(CAST(t.n_kekule   AS REAL)) as mean_n_kekule,
           AVG(t.cbo_mean_hex)             as mean_cbo_hex
    FROM topology_metrics t
    JOIN solutions s ON s.h=t.h AND s.config=t.config
                     AND s.mol=t.mol AND s.sol_idx=t.sol_idx
    WHERE s.verdict IN ('plan','non_plan')
    """
    params = []
    if h is not None:
        sql += " AND t.h = ?"
        params.append(h)
    sql += " GROUP BY t.h ORDER BY t.h"
    return conn.execute(sql, params).fetchall()


def distribution_clar(conn: sqlite3.Connection,
                      h: Optional[str] = None) -> List[sqlite3.Row]:
    """Distribution du clar_number sur les solutions evaluees.
    Retourne [(clar_number, count), ...] tri par clar_number croissant."""
    conn.row_factory = sqlite3.Row
    sql = "SELECT clar_number, COUNT(*) as n FROM topology_metrics"
    params = []
    if h is not None:
        sql += " WHERE h = ?"
        params.append(h)
    sql += " GROUP BY clar_number ORDER BY clar_number"
    return conn.execute(sql, params).fetchall()


def distribution_radicals(conn: sqlite3.Connection,
                          h: Optional[str] = None) -> List[sqlite3.Row]:
    """Distribution de n_radicals sur les solutions evaluees.
    Retourne [(n_radicals, count), ...] tri par n_radicals croissant."""
    conn.row_factory = sqlite3.Row
    sql = "SELECT n_radicals, COUNT(*) as n FROM topology_metrics"
    params = []
    if h is not None:
        sql += " WHERE h = ?"
        params.append(h)
    sql += " GROUP BY n_radicals ORDER BY n_radicals"
    return conn.execute(sql, params).fetchall()


def top_aromatic_planar(conn: sqlite3.Connection,
                        h: Optional[str] = None,
                        k: int = 20,
                        max_angle: float = 5.0,
                        min_clar: int = 2) -> List[sqlite3.Row]:
    """Top-K structures planes ET aromatiques (clar_number >= min_clar,
    angle_deg <= max_angle), triees par clar_number desc puis angle asc.

    Pattern de JOIN : on part de topology_metrics (petite table) et on
    joint vers solutions par PK pour eviter un scan inutile des 6M sols.
    """
    conn.row_factory = sqlite3.Row
    sql = """
    SELECT t.h, t.config, t.mol, t.sol_idx, s.sizes, s.angle_deg,
           t.clar_number, t.n_clar_covers, t.cbo_mean_hex, t.n_radicals
    FROM topology_metrics t
    JOIN solutions s ON s.h=t.h AND s.config=t.config
                     AND s.mol=t.mol AND s.sol_idx=t.sol_idx
    WHERE t.clar_number >= ?
      AND s.verdict = 'plan'
      AND s.angle_deg <= ?
    """
    params = [min_clar, max_angle]
    if h is not None:
        sql += " AND t.h = ?"
        params.append(h)
    sql += " ORDER BY t.clar_number DESC, s.angle_deg ASC LIMIT ?"
    params.append(k)
    return conn.execute(sql, params).fetchall()


def top_radical_planar(conn: sqlite3.Connection,
                       h: Optional[str] = None,
                       k: int = 20,
                       max_angle: float = 5.0,
                       min_radicals: int = 2) -> List[sqlite3.Row]:
    """Top-K structures planes ET fortement radicalaires."""
    conn.row_factory = sqlite3.Row
    sql = """
    SELECT t.h, t.config, t.mol, t.sol_idx, s.sizes, s.angle_deg,
           t.n_radicals, t.clar_number, t.n_kekule
    FROM topology_metrics t
    JOIN solutions s ON s.h=t.h AND s.config=t.config
                     AND s.mol=t.mol AND s.sol_idx=t.sol_idx
    WHERE t.n_radicals >= ?
      AND s.verdict = 'plan'
      AND s.angle_deg <= ?
    """
    params = [min_radicals, max_angle]
    if h is not None:
        sql += " AND t.h = ?"
        params.append(h)
    sql += " ORDER BY t.n_radicals DESC, s.angle_deg ASC LIMIT ?"
    params.append(k)
    return conn.execute(sql, params).fetchall()


def correlation_angle_radicals(conn: sqlite3.Connection,
                               h: Optional[str] = None
                               ) -> Optional[float]:
    """Coefficient de correlation de Pearson entre angle_deg et n_radicals
    sur les solutions plan+non_plan. Pur Python pour eviter numpy.
    Retourne None si moins de 2 echantillons.
    """
    sql = """
    SELECT s.angle_deg, t.n_radicals
    FROM topology_metrics t
    JOIN solutions s ON s.h=t.h AND s.config=t.config
                     AND s.mol=t.mol AND s.sol_idx=t.sol_idx
    WHERE s.verdict IN ('plan','non_plan')
      AND s.angle_deg IS NOT NULL
    """
    params = []
    if h is not None:
        sql += " AND t.h = ?"
        params.append(h)
    rows = conn.execute(sql, params).fetchall()
    if len(rows) < 2:
        return None
    xs = [r[0] for r in rows]
    ys = [float(r[1]) for r in rows]
    return _pearson(xs, ys)


def _pearson(xs, ys):
    """Coefficient de correlation de Pearson, pur Python."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = (sxx * syy) ** 0.5
    if denom == 0:
        return None
    return sxy / denom
