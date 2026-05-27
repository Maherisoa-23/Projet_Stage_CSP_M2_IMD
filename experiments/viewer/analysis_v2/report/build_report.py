"""
Genere le rapport HTML statique a partir des resultats des experiences.

Chaque experience expose un `run(conn, h)` qui retourne un dict
{title, summary, plots, tables}.

Le rapport :
  - une page d'accueil avec resume + nav
  - une section par experience (ancres)
  - tout en un seul HTML autonome (svg inline)

Usage :
    python -m experiments.viewer.analysis_v2.report.build_report \\
        --db db_v2.db --h h6 --output rapport_h6.html

    # Sans --h : rapport sur TOUS les h confondus
    python -m experiments.viewer.analysis_v2.report.build_report \\
        --db db_v2.db --output rapport_all.html
"""

import argparse
import datetime as _dt
import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[5]))
    __package__ = "experiments.viewer.analysis_v2.report"

from ..experiments import (  # noqa: E402
    e01_topology_planarity,
    e02_topology_aromaticity,
    e03_boundary_stability,
    e04_geometry_electronic,
    e05_radical_localization,
    e06_top_candidates,
    e07_scaling,
)


EXPERIMENTS = [
    ("e01", e01_topology_planarity),
    ("e02", e02_topology_aromaticity),
    ("e03", e03_boundary_stability),
    ("e04", e04_geometry_electronic),
    ("e05", e05_radical_localization),
    ("e06", e06_top_candidates),
    ("e07", e07_scaling),
]


def _table_html(t: dict) -> str:
    head = "".join(f"<th>{h}</th>" for h in t["headers"])
    body = []
    for row in t["rows"]:
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    return (
        f'<div class="table-wrap"><h3>{t["title"]}</h3>'
        f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    )


def _plot_html(p: dict) -> str:
    """Format etendu : un plot peut avoir description (avant) et
    interpretation (apres) en plus du title et svg."""
    desc = p.get("description", "")
    interp = p.get("interpretation", "")
    desc_html = f'<div class="plot-desc">{desc}</div>' if desc else ""
    interp_html = f'<div class="plot-interp">{interp}</div>' if interp else ""
    return (
        f'<div class="plot">'
        f'<h3>{p["title"]}</h3>'
        f'{desc_html}'
        f'{p["svg"]}'
        f'{interp_html}'
        f'</div>'
    )


def _experiment_html(eid: str, result: dict) -> str:
    intro = result.get("intro", "")
    intro_html = f'<div class="intro">{intro}</div>' if intro else ""
    plots_html = "".join(_plot_html(p) for p in result.get("plots", []))
    tables_html = "".join(_table_html(t) for t in result.get("tables", []))
    summary = result.get("summary", "")
    summary_html = f'<div class="summary">{summary}</div>' if summary else ""
    return (
        f'<section id="{eid}">'
        f'<h2>{result["title"]}</h2>'
        f'{intro_html}'
        f'{summary_html}'
        f'{plots_html}'
        f'{tables_html}'
        f'</section>'
    )


def build_report(db_path: Path, h: str = None, output: Path = None) -> Path:
    conn = sqlite3.connect(str(db_path))

    if output is None:
        suffix = f"_{h}" if h else "_all"
        output = Path(f"rapport{suffix}.html")

    print(f"[report] DB = {db_path}, filtre h = {h or '(tous)'}")
    print(f"[report] Output = {output}")

    sections = []
    nav_items = []
    for eid, mod in EXPERIMENTS:
        print(f"[report] running {eid} ...")
        try:
            result = mod.run(conn, h=h)
        except Exception as e:
            import traceback
            print(f"  ECHEC {eid}: {e}")
            traceback.print_exc(limit=3)
            result = {
                "title": f"{eid} - ECHEC",
                "summary": f"Erreur : {e.__class__.__name__}: {e}",
                "plots": [], "tables": [],
            }
        sections.append(_experiment_html(eid, result))
        nav_items.append(f'<a href="#{eid}">{eid}</a>')

    n_desc = conn.execute("SELECT COUNT(*) FROM solution_descriptors" +
                          (" WHERE h=?" if h else ""),
                          ([h] if h else [])).fetchone()[0]
    conn.close()

    timestamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    h_str = h or "h6 + h7 + h8 + h9"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Analyse topologie x planeite x electronique - {h_str}</title>
<style>
body {{ font-family: Inter, system-ui, sans-serif; margin: 0; padding: 0;
       background: #f3f4f6; color: #111827; }}
header {{ background: #1e3a8a; color: #fff; padding: 1.5rem 2rem; }}
header h1 {{ margin: 0; font-size: 1.3rem; }}
header .meta {{ font-size: 0.85rem; opacity: 0.85; margin-top: 0.4rem; }}
nav {{ background: #fff; padding: 0.6rem 2rem; border-bottom: 1px solid #e5e7eb;
       position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 4px rgba(0,0,0,.04);
       display: flex; gap: 1rem; flex-wrap: wrap; }}
nav a {{ color: #2563eb; text-decoration: none; font-weight: 500; font-size: 0.9rem; }}
nav a:hover {{ text-decoration: underline; }}
section {{ background: #fff; margin: 1.2rem 2rem; padding: 1.5rem;
           border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }}
section h2 {{ color: #1e40af; margin-top: 0; font-size: 1.15rem;
              border-bottom: 2px solid #e5e7eb; padding-bottom: 0.4rem; }}
section h3 {{ color: #374151; font-size: 1rem; margin: 1rem 0 0.4rem; }}
.summary {{ background: #eff6ff; border-left: 3px solid #2563eb;
            padding: 0.6rem 0.9rem; border-radius: 4px; font-size: 0.92rem;
            margin: 0.6rem 0; }}
.intro {{ background: #fef9c3; border-left: 3px solid #ca8a04;
          padding: 0.8rem 1rem; border-radius: 4px; font-size: 0.92rem;
          margin: 0.6rem 0 1.2rem; line-height: 1.55; }}
.intro b {{ color: #713f12; }}
.plot {{ margin: 1.5rem 0; overflow-x: auto; padding: 0.6rem;
         background: #fafafa; border-radius: 6px; }}
.plot svg {{ max-width: 100%; height: auto; display: block; margin: 0.6rem auto; }}
.plot-desc {{ font-size: 0.88rem; color: #4b5563; font-style: italic;
              margin: 0.3rem 0 0.6rem; padding: 0 0.4rem; line-height: 1.4; }}
.plot-interp {{ background: #f0fdf4; border-left: 3px solid #16a34a;
                padding: 0.5rem 0.8rem; border-radius: 4px;
                font-size: 0.88rem; margin: 0.6rem 0 0; color: #14532d;
                line-height: 1.5; }}
.plot-interp::before {{ content: "Comment lire : "; font-weight: 700;
                        color: #15803d; }}
.table-wrap {{ margin: 1rem 0; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th, td {{ padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid #e5e7eb; }}
th {{ background: #f9fafb; font-weight: 600; color: #374151; }}
tr:hover td {{ background: #f9fafb; }}
.footer {{ text-align: center; color: #6b7280; padding: 1rem; font-size: 0.85rem; }}
</style>
</head>
<body>
<header>
  <h1>Analyse topologie x planeite x electronique</h1>
  <div class="meta">
    Donnees : <b>{n_desc}</b> solutions caracterisees -
    filtre h : <b>{h_str}</b> -
    genere le <b>{timestamp}</b>
  </div>
</header>
<nav>
  {' '.join(nav_items)}
</nav>
{"".join(sections)}
<div class="footer">analysis_v2 - rapport autonome</div>
</body>
</html>
"""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"[report] OK : {output}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--h", default=None,
                        help="filtre par h (h6/h7/h8/h9). Default = tous")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    build_report(
        db_path=Path(args.db),
        h=args.h,
        output=Path(args.output) if args.output else None,
    )


if __name__ == "__main__":
    main()
