"""Generation du rapport de pipeline : structures planes vs non planes"""

from pathlib import Path
from typing import List, Dict
from datetime import datetime


def generate_report(results: List[Dict], output_path: str):
    """
    Genere un rapport texte listant les structures planes et non planes.

    Chaque element de `results` est un dict avec les cles :
      - sequence     : str  (ex. "5_0_5_0_0_0_0")
      - central_size : int
      - n_carbons    : int
      - cml_file     : str  (chemin du fichier CML)
      - optimized    : bool (True si MMFF94 a reussi)
      - planar       : bool (True si passe le test de planarite)
      - max_deviation: float (deviation max au plan moyen, en Angstroms)
      - rmsd_plane   : float (RMSD au plan moyen, en Angstroms)
      - height       : float (epaisseur totale, en Angstroms)
      - opt_message  : str  (message de l'optimiseur)
    """
    planar = [r for r in results if r.get('planar', False)]
    non_planar = [r for r in results if not r.get('planar', False) and r.get('optimized', False)]
    opt_failed = [r for r in results if not r.get('optimized', False)]

    # Trier les non-planes par deviation decroissante
    non_planar.sort(key=lambda r: r.get('max_deviation', 0), reverse=True)

    lines = []
    lines.append("=" * 80)
    lines.append("  RAPPORT DE GENERATION — Structures non-benzenoides polycycliques")
    lines.append(f"  Date : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 80)
    lines.append("")

    # --- Resume ---
    lines.append(f"Total structures generees : {len(results)}")
    lines.append(f"  Planes (acceptees)      : {len(planar)}")
    lines.append(f"  Non planes (rejetees)   : {len(non_planar)}")
    lines.append(f"  Optimisation echouee    : {len(opt_failed)}")
    lines.append("")

    # --- Par cycle central ---
    for size in [5, 6, 7]:
        subset = [r for r in results if r['central_size'] == size]
        p = sum(1 for r in subset if r.get('planar', False))
        np_ = sum(1 for r in subset if not r.get('planar', False) and r.get('optimized', False))
        fail = sum(1 for r in subset if not r.get('optimized', False))
        lines.append(f"  Cycle {size} : {len(subset)} total | "
                     f"{p} planes | {np_} non planes | {fail} echecs")
    lines.append("")

    # --- Structures planes ---
    lines.append("-" * 80)
    lines.append("  STRUCTURES PLANES (acceptees)")
    lines.append("-" * 80)
    if planar:
        lines.append(f"{'Sequence':<30} {'Cycle':>5} {'nC':>4} "
                     f"{'MaxDev(A)':>10} {'RMSD(A)':>9} {'Hauteur(A)':>11}")
        lines.append("-" * 80)
        for r in sorted(planar, key=lambda x: (x['central_size'], x['sequence'])):
            lines.append(
                f"{r['sequence']:<30} {r['central_size']:>5} {r['n_carbons']:>4} "
                f"{r.get('max_deviation', 0):>10.4f} "
                f"{r.get('rmsd_plane', 0):>9.4f} "
                f"{r.get('height', 0):>11.4f}"
            )
    else:
        lines.append("  (aucune)")
    lines.append("")

    # --- Structures non planes ---
    lines.append("-" * 80)
    lines.append("  STRUCTURES NON PLANES (rejetees) — triees par deviation decroissante")
    lines.append("-" * 80)
    if non_planar:
        lines.append(f"{'Sequence':<30} {'Cycle':>5} {'nC':>4} "
                     f"{'MaxDev(A)':>10} {'RMSD(A)':>9} {'Hauteur(A)':>11}")
        lines.append("-" * 80)
        for r in non_planar:
            lines.append(
                f"{r['sequence']:<30} {r['central_size']:>5} {r['n_carbons']:>4} "
                f"{r.get('max_deviation', 0):>10.4f} "
                f"{r.get('rmsd_plane', 0):>9.4f} "
                f"{r.get('height', 0):>11.4f}"
            )
    else:
        lines.append("  (aucune)")
    lines.append("")

    # --- Echecs d'optimisation ---
    if opt_failed:
        lines.append("-" * 80)
        lines.append("  ECHECS D'OPTIMISATION (obabel)")
        lines.append("-" * 80)
        for r in opt_failed:
            lines.append(f"  {r['sequence']:<30} cycle={r['central_size']}  "
                         f"— {r.get('opt_message', '?')}")
        lines.append("")

    lines.append("=" * 80)
    lines.append("  Fin du rapport")
    lines.append("=" * 80)

    report_text = "\n".join(lines)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_text)

    return report_text
