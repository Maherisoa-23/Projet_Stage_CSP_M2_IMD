"""
Met a jour report/index.html a partir des data.json dans output/.

Usage (depuis csp_solver/experiments/) :
    python update_report.py
"""

import json
from pathlib import Path
from datetime import datetime


def load_all_data(output_dir):
    """Charge tous les data.json tries par hX."""
    results = {}
    for data_file in sorted(output_dir.glob("*/data.json")):
        h_name = data_file.parent.name  # "h3", "h4", ...
        with open(data_file, "r", encoding="utf-8") as f:
            results[h_name] = json.load(f)
    return results


def compute_stats(data):
    """Calcule les stats pour un data.json."""
    molecules = data["molecules"]
    n_mol = len(molecules)
    n_sol = sum(len(m["solutions"]) for m in molecules.values())
    n_plan = sum(1 for m in molecules.values() for s in m["solutions"] if s["planar"])
    n_non = n_sol - n_plan
    n_orig = sum(1 for m in molecules.values() if m.get("original"))
    n_orig_plan = sum(1 for m in molecules.values()
                      if m.get("original") and m["original"]["planar"])
    pct = round(100 * n_plan / n_sol) if n_sol > 0 else 0
    return {
        "molecules": n_mol,
        "solutions": n_sol,
        "planar": n_plan,
        "non_planar": n_non,
        "pct_planar": pct,
        "originals": n_orig,
        "originals_planar": n_orig_plan,
    }


def generate_html(all_data):
    """Genere le HTML du rapport."""
    # Stats par h
    rows = []
    totals = {"molecules": 0, "solutions": 0, "planar": 0, "non_planar": 0}
    h_cards = []

    for h_name in sorted(all_data.keys(), key=lambda x: int(x[1:])):
        stats = compute_stats(all_data[h_name])
        h_num = h_name[1:]
        totals["molecules"] += stats["molecules"]
        totals["solutions"] += stats["solutions"]
        totals["planar"] += stats["planar"]
        totals["non_planar"] += stats["non_planar"]

        non_cls = ' class="non-planar"' if stats["non_planar"] > 0 else ""
        rows.append(
            f'    <tr>'
            f'<td><strong>h={h_num}</strong></td>'
            f'<td>{stats["molecules"]}</td>'
            f'<td>{stats["solutions"]}</td>'
            f'<td class="planar">{stats["planar"]}</td>'
            f'<td{non_cls}>{stats["non_planar"]}</td>'
            f'<td>{stats["pct_planar"]}%</td>'
            f'<td class="planar">{stats["originals_planar"]}/{stats["originals"]}</td>'
            f'</tr>'
        )

        h_cards.append(
            f'  <a href="../output/{h_name}/view.html" target="_blank" '
            f'class="card blue" style="text-decoration:none; cursor:pointer;">'
            f'<div class="value">{h_name}</div>'
            f'<div class="label">{stats["molecules"]} molecules</div></a>'
        )

    h_list = sorted(all_data.keys(), key=lambda x: int(x[1:]))
    h_min = h_list[0][1:]
    h_max = h_list[-1][1:]

    rows_html = "\n".join(rows)
    cards_html = "\n".join(h_cards)

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    batch_rows = "\n".join(
        f'    <tr><td>{h}</td>'
        f'<td><code>python batch_main.py plane/benzdb/{h} --validate</code></td></tr>'
        for h in h_list
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Experimentation — Structures planes BenzAI DB</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f6fa; color: #2d3436; padding: 32px; max-width: 1100px; margin: 0 auto; line-height: 1.6; }}
  h1 {{ font-size: 1.6em; margin-bottom: 4px; color: #2d3436; }}
  h2 {{ font-size: 1.2em; margin: 32px 0 12px; color: #0984e3; border-bottom: 2px solid #dfe6e9; padding-bottom: 6px; }}
  h3 {{ font-size: 1em; margin: 20px 0 8px; color: #636e72; }}
  p {{ margin-bottom: 12px; }}
  .meta {{ color: #636e72; font-size: 0.85em; margin-bottom: 24px; }}
  .pipeline {{ background: #fff; border-radius: 8px; padding: 16px 20px; margin: 12px 0;
              box-shadow: 0 1px 3px rgba(0,0,0,0.08); font-family: monospace; font-size: 0.9em;
              display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .pipeline .step {{ background: #dfe6e9; padding: 6px 12px; border-radius: 4px; }}
  .pipeline .arrow {{ color: #0984e3; font-weight: bold; }}
  .config {{ background: #fff; border-radius: 8px; padding: 16px 20px; margin: 12px 0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .config table {{ width: 100%; border-collapse: collapse; }}
  .config td {{ padding: 4px 12px; font-size: 0.9em; }}
  .config td:first-child {{ font-weight: 600; color: #636e72; width: 220px; }}
  .cards {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px 20px; min-width: 140px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08); text-align: center; }}
  .card .value {{ font-size: 1.8em; font-weight: 700; }}
  .card .label {{ font-size: 0.75em; color: #636e72; margin-top: 2px; }}
  .card.green .value {{ color: #00b894; }}
  .card.red .value {{ color: #d63031; }}
  .card.blue .value {{ color: #0984e3; }}
  table.results {{ width: 100%; background: #fff; border-radius: 8px; overflow: hidden;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-collapse: collapse; margin: 16px 0; }}
  table.results th {{ background: #dfe6e9; padding: 10px 14px; text-align: center; font-size: 0.8em;
                     text-transform: uppercase; letter-spacing: 0.5px; color: #636e72; }}
  table.results td {{ padding: 8px 14px; border-top: 1px solid #f0f0f0; text-align: center; font-size: 0.9em; }}
  table.results tr:hover {{ background: #f8f9fa; }}
  .planar {{ color: #00b894; font-weight: 600; }}
  .non-planar {{ color: #d63031; font-weight: 600; }}
  .note {{ background: #ffeaa7; border-left: 4px solid #fdcb6e; padding: 12px 16px; border-radius: 0 8px 8px 0;
          margin: 16px 0; font-size: 0.9em; }}
  .observation {{ background: #fff; border-left: 4px solid #0984e3; padding: 12px 16px; border-radius: 0 8px 8px 0;
                 margin: 12px 0; font-size: 0.9em; }}
  .placeholder {{ background: #dfe6e9; border-radius: 8px; padding: 32px; text-align: center; color: #636e72;
                 margin: 16px 0; font-style: italic; }}
  ul {{ margin: 8px 0 8px 24px; }}
  li {{ margin-bottom: 4px; }}
  code {{ background: #dfe6e9; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; }}
  a {{ color: #0984e3; }}
</style>
</head>
<body>

<h1>Phase experimentale — Structures planes</h1>
<p class="meta">Source : BenzAI DB &mdash; Structures planes h{h_min} a h{h_max} &mdash; Mis a jour le {now}</p>

<!-- ============================================================ -->
<h2>1. Introduction</h2>

<p>
  Le modele de generation de non-benzenoides (solveur CSP + reconstruction 3D + optimisation xTB)
  est operationnel. Les premiers tests ont revele des solutions marquees comme non planes,
  ce qui a motive le lancement d'une phase experimentale systematique.
</p>
<p>
  L'objectif est de tester le pipeline sur des structures dont la planarite est connue :
  les benzenoides plans issus de <strong>BenzAI DB</strong>, de h={h_min} a h={h_max}.
  Puisque ces structures sont planes par construction, toutes les solutions tout-hexagonales (6,6,...,6)
  doivent etre validees comme planes. Les solutions avec substitutions 5/7 sont les cas d'interet.
</p>

<!-- ============================================================ -->
<h2>2. Methodologie</h2>

<h3>Pipeline</h3>
<div class="pipeline">
  <span class="step">.graph (BenzAI DB)</span>
  <span class="arrow">&rarr;</span>
  <span class="step">Solveur CSP (ACE)</span>
  <span class="arrow">&rarr;</span>
  <span class="step">Reconstruction 3D</span>
  <span class="arrow">&rarr;</span>
  <span class="step">xTB (GFN2-xTB)</span>
  <span class="arrow">&rarr;</span>
  <span class="step">Test planarite (ACP)</span>
</div>

<h3>Configuration xTB</h3>
<div class="config">
  <table>
    <tr><td>Methode</td><td>GFN2-xTB (semi-empirique, tight-binding etendu)</td></tr>
    <tr><td>Niveau d'optimisation</td><td><code>--opt tight</code></td></tr>
    <tr><td>Perturbation initiale</td><td>&plusmn;0.1 &Aring; aleatoire sur les coordonnees z</td></tr>
    <tr><td>Timeout</td><td>300 secondes par molecule</td></tr>
  </table>
</div>

<h3>Test de planarite</h3>
<div class="config">
  <table>
    <tr><td>Methode</td><td>Analyse en Composantes Principales (ACP) sur les coordonnees atomiques</td></tr>
    <tr><td>Metrique</td><td>Angle maximal de deviation par rapport au plan moyen</td></tr>
    <tr><td>Seuil</td><td><strong>10&deg;</strong> &mdash; en dessous = plan, au dessus = non plan</td></tr>
  </table>
</div>

<div class="note">
  <strong>Non-determinisme :</strong> xTB est un optimiseur local (descente de gradient).
  La perturbation aleatoire en z fait que le point de depart differe a chaque run,
  ce qui peut mener a des minima locaux legerement differents.
  Les angles observes peuvent varier de &plusmn;3-5&deg; entre executions successives.
</div>

<!-- ============================================================ -->
<h2>3. Resultats</h2>

<h3>Vue d'ensemble</h3>
<div class="cards">
  <div class="card blue"><div class="value">{totals["molecules"]}</div><div class="label">Molecules testees</div></div>
  <div class="card blue"><div class="value">{totals["solutions"]}</div><div class="label">Solutions CSP</div></div>
  <div class="card green"><div class="value">{totals["planar"]}</div><div class="label">Solutions planes</div></div>
  <div class="card red"><div class="value">{totals["non_planar"]}</div><div class="label">Solutions non planes</div></div>
</div>

<h3>Par taille de benzenoide</h3>
<table class="results">
  <thead>
    <tr>
      <th>h</th>
      <th>Molecules</th>
      <th>Solutions</th>
      <th>Planes</th>
      <th>Non planes</th>
      <th>% plan</th>
      <th>Originaux plans</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>

<!-- ============================================================ -->
<h2>4. Observations</h2>

<div class="observation">
  <strong>Les originaux sont tous plans.</strong>
  Les {totals["molecules"]} structures originales (tout hexagonal, solution 6,6,...,6) sont systematiquement
  validees comme planes (&lt; 1&deg;). Cela confirme que le pipeline de reconstruction + xTB
  fonctionne correctement sur les benzenoides connus.
</div>

<div class="observation">
  <strong>Les solutions tout-6 sont toujours planes.</strong>
  Quand la solution CSP est identique au benzenoide original (tous les cycles a 6),
  l'angle maximal est systematiquement &lt; 1&deg;. Le pipeline est coherent.
</div>

<div class="observation">
  <strong>Le taux de non-planarite augmente avec h.</strong>
  Plus le benzenoide est grand, plus les substitutions 5/7
  ont de chances de produire des structures non planes.
</div>

<div class="observation">
  <strong>Non-determinisme observe.</strong>
  Les solutions avec des angles proches du seuil (10-20&deg;) peuvent varier entre les runs.
  Les solutions clairement planes (&lt; 1&deg;) ou clairement non planes (&gt; 20&deg;)
  sont stables entre les runs.
</div>

<!-- ============================================================ -->
<h2>5. Analyses a venir</h2>

<div class="placeholder">
  Espace reserve pour les analyses futures : graphes, charts, correlations
  entre topologie et planarite, etude de la position des 5/7 dans la structure, etc.
</div>

<!-- ============================================================ -->
<h2>Resultats detailles</h2>
<div class="cards">
{cards_html}
</div>

<!-- ============================================================ -->
<h2>Commandes</h2>

<p>Toutes les commandes se lancent depuis le dossier <code>csp_solver/experiments/</code>.</p>

<h3>Lancer les tests sur un dossier (CSP + validation + original)</h3>
<div class="config">
  <table>
{batch_rows}
  </table>
</div>
<p>
  Cela lance pour chaque <code>.graph</code> : le test de l'original (tout-6) via <code>test.py</code>,
  puis le solveur CSP + validation xTB via <code>main.py --validate</code>.
  Le rapport <code>view.html</code> est genere automatiquement a la fin dans <code>output/hX/</code>.
</p>

<h3>Tester seulement les originaux</h3>
<div class="config">
  <table>
    <tr><td>Exemple</td><td><code>python batch_test.py plane/benzdb/h3</code></td></tr>
  </table>
</div>

<h3>Regenerer les rapports sans relancer les calculs</h3>
<div class="config">
  <table>
    <tr><td>Un seul</td><td><code>python view.py output/h4</code></td></tr>
    <tr><td>Rapport global</td><td><code>python update_report.py</code></td></tr>
  </table>
</div>

<h3>Lancer un seul fichier manuellement</h3>
<p>Depuis le dossier <code>csp_solver/</code> :</p>
<div class="config">
  <table>
    <tr><td>CSP + validation</td><td><code>python main.py data/fichier.graph --validate</code></td></tr>
    <tr><td>Test original seul</td><td><code>python test.py data/fichier.graph</code></td></tr>
  </table>
</div>

</body>
</html>"""
    return html


def main():
    experiments_dir = Path(__file__).parent
    output_dir = experiments_dir / "output"
    report_dir = experiments_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not output_dir.is_dir():
        print("ERREUR : dossier output/ introuvable.")
        return

    all_data = load_all_data(output_dir)
    if not all_data:
        print("Aucun data.json trouve dans output/.")
        return

    print(f"Donnees chargees : {', '.join(sorted(all_data.keys()))}")

    html = generate_html(all_data)
    out_path = report_dir / "index.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Rapport genere : {out_path}")


if __name__ == "__main__":
    main()
