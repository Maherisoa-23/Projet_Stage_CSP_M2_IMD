"""
Requetes SQL reutilisables sur solution_descriptors x solutions.

Toutes les fonctions :
  - prennent (conn: sqlite3.Connection, h: Optional[str], ...)
  - retournent des List[sqlite3.Row] ou des dicts agrege
  - PARTENT DE solution_descriptors d'abord, puis JOIN vers solutions
    (eviter le scan inutile des 6M sols). Pattern eprouve dans analysis/.
"""

import sqlite3
from typing import List, Optional, Dict, Tuple


def n_rows(conn: sqlite3.Connection, h: Optional[str] = None) -> int:
    """Nb de lignes dans solution_descriptors (filtre h optionnel)."""
    sql = "SELECT COUNT(*) FROM solution_descriptors"
    params = []
    if h is not None:
        sql += " WHERE h = ?"
        params.append(h)
    return conn.execute(sql, params).fetchone()[0]


def fetch_all_with_verdict(conn: sqlite3.Connection,
                            h: Optional[str] = None,
                            limit: Optional[int] = None) -> List[sqlite3.Row]:
    """Solutions descriptees jointes au verdict + angle_deg de solutions."""
    conn.row_factory = sqlite3.Row
    sql = """
    SELECT d.*, s.verdict, s.angle_deg
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    """
    params = []
    if h is not None:
        sql += " WHERE d.h = ?"
        params.append(h)
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def heatmap_n_by_5_7(conn: sqlite3.Connection,
                      h: Optional[str] = None,
                      verdict_filter: Optional[str] = None) -> Dict[Tuple[int, int], int]:
    """Heatmap : nombre de solutions par couple (n_pent, n_hept).

    Si verdict_filter, applique un filtre sur s.verdict (ex: 'plan').
    """
    if verdict_filter is None:
        sql = "SELECT n_pent, n_hept, COUNT(*) FROM solution_descriptors"
        if h:
            sql += " WHERE h = ?"
        sql += " GROUP BY n_pent, n_hept"
        params = [h] if h else []
    else:
        sql = """
        SELECT d.n_pent, d.n_hept, COUNT(*)
        FROM solution_descriptors d
        JOIN solutions s ON s.h=d.h AND s.config=d.config
                         AND s.mol=d.mol AND s.sol_idx=d.sol_idx
        WHERE s.verdict = ?
        """
        params = [verdict_filter]
        if h:
            sql += " AND d.h = ?"
            params.append(h)
        sql += " GROUP BY d.n_pent, d.n_hept"
    return {(r[0], r[1]): r[2] for r in conn.execute(sql, params)}


def percent_plan_by_5_7(conn: sqlite3.Connection,
                         h: Optional[str] = None,
                         min_count: int = 5) -> Dict[Tuple[int, int], float]:
    """Pour chaque couple (n_pent, n_hept), % de solutions verdict='plan'.

    `min_count` filtre les cellules avec trop peu d'echantillons (sinon
    on a des ratios sur 1 ou 2 sols qui sont non-significatifs).

    Retourne dict (n_pent, n_hept) -> pct (0-100, NaN si exclu).
    """
    sql = """
    SELECT d.n_pent, d.n_hept,
           SUM(CASE WHEN s.verdict='plan' THEN 1 ELSE 0 END) as n_plan,
           COUNT(*) as n_total
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict IN ('plan', 'non_plan')
    """
    params = []
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " GROUP BY d.n_pent, d.n_hept"
    out = {}
    for r in conn.execute(sql, params):
        if r[3] >= min_count:
            out[(r[0], r[1])] = 100.0 * r[2] / r[3]
    return out


def mean_metric_by_5_7(conn: sqlite3.Connection,
                       metric: str,
                       h: Optional[str] = None,
                       min_count: int = 5,
                       verdict: str = "plan") -> Dict[Tuple[int, int], float]:
    """Moyenne d'une metrique par cellule (n_pent, n_hept). Filtre verdict."""
    # Whitelist des metriques autorisees (anti injection SQL)
    allowed = {
        "clar_number", "n_radicals", "n_kekule",
        "cbo_mean_hex", "cbo_max_hex",
        "cbo_mean_pent", "cbo_mean_hept",
        "buckling_height", "curvature_discrete_mean",
        "curvature_discrete_max", "irregularity_param",
        "n_azulene_units", "n_stone_wales",
        "aromatic_planarity_score", "radical_planarity_score",
    }
    if metric not in allowed:
        raise ValueError(f"metric '{metric}' non autorisee")

    sql = f"""
    SELECT d.n_pent, d.n_hept, AVG(d.{metric}) as m, COUNT(*) as n
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE s.verdict = ? AND d.{metric} IS NOT NULL
    """
    params = [verdict]
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    sql += " GROUP BY d.n_pent, d.n_hept"
    out = {}
    for r in conn.execute(sql, params):
        if r[3] >= min_count and r[2] is not None:
            out[(r[0], r[1])] = r[2]
    return out


def distribution(conn: sqlite3.Connection,
                  column: str,
                  h: Optional[str] = None,
                  verdict: Optional[str] = None,
                  bins: Optional[int] = None) -> List[Tuple[float, int]]:
    """Distribution d'une colonne. Si bins, retourne histogramme; sinon
    groupement par valeur exacte."""
    allowed = {"clar_number", "n_radicals", "n_pent", "n_hex", "n_hept",
               "n_azulene_units", "n_stone_wales", "buckling_height",
               "curvature_discrete_max", "irregularity_param"}
    if column not in allowed:
        raise ValueError(f"column '{column}' non autorisee")

    if verdict is None:
        sql = f"SELECT {column} FROM solution_descriptors WHERE {column} IS NOT NULL"
        params = []
        if h:
            sql += " AND h = ?"
            params.append(h)
    else:
        sql = f"""
        SELECT d.{column}
        FROM solution_descriptors d
        JOIN solutions s ON s.h=d.h AND s.config=d.config
                         AND s.mol=d.mol AND s.sol_idx=d.sol_idx
        WHERE d.{column} IS NOT NULL AND s.verdict = ?
        """
        params = [verdict]
        if h:
            sql += " AND d.h = ?"
            params.append(h)
    values = [r[0] for r in conn.execute(sql, params)]
    if not values:
        return []
    if bins is None:
        # Discret : group_by exact
        counts = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return sorted(counts.items())
    # Continue : histogramme
    vmin, vmax = min(values), max(values)
    if vmin == vmax:
        return [(vmin, len(values))]
    bw = (vmax - vmin) / bins
    h_counts = [0] * bins
    for v in values:
        idx = min(int((v - vmin) / bw), bins - 1)
        h_counts[idx] += 1
    return [(vmin + bw * (i + 0.5), c) for i, c in enumerate(h_counts)]


def pearson(conn: sqlite3.Connection,
             col_x: str, col_y: str,
             h: Optional[str] = None,
             verdict: Optional[str] = None) -> Optional[float]:
    """Coefficient de Pearson entre 2 colonnes (filtre h + verdict optionnel)."""
    allowed = {"clar_number", "n_radicals", "n_kekule",
               "cbo_mean_hex", "buckling_height",
               "curvature_discrete_mean", "curvature_discrete_max",
               "irregularity_param", "n_azulene_units",
               "n_pent", "n_hex", "n_hept", "angle_deg",
               "max_angle_deg", "aromatic_planarity_score",
               "radical_planarity_score"}
    if col_x not in allowed or col_y not in allowed:
        raise ValueError(f"cols non autorisees : {col_x}, {col_y}")

    # On cherche d'abord dans solution_descriptors, fallback solutions
    table_x = "d" if col_x != "angle_deg" else "s"
    table_y = "d" if col_y != "angle_deg" else "s"
    sql = f"""
    SELECT {table_x}.{col_x}, {table_y}.{col_y}
    FROM solution_descriptors d
    JOIN solutions s ON s.h=d.h AND s.config=d.config
                     AND s.mol=d.mol AND s.sol_idx=d.sol_idx
    WHERE {table_x}.{col_x} IS NOT NULL AND {table_y}.{col_y} IS NOT NULL
    """
    params = []
    if verdict:
        sql += " AND s.verdict = ?"
        params.append(verdict)
    if h:
        sql += " AND d.h = ?"
        params.append(h)
    rows = conn.execute(sql, params).fetchall()
    if len(rows) < 2:
        return None
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = (sxx * syy) ** 0.5
    if denom == 0:
        return None
    return sxy / denom
