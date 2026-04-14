#!/usr/bin/env python3
"""Generateur principal de structures non-benzenoides

Deux commandes :
  python main.py generate              # Genere les 1228 structures CML
  python main.py optimize              # Optimise MMFF94 + test planarite + rapport
  python main.py optimize -t 0.3       # Seuil de planarite plus strict
  python main.py optimize -s 1000      # Plus d'etapes d'optimisation
"""

from pathlib import Path
from utils.symmetry import generate_canonical_sequences
from generators.builder import StructureBuilder
from config import NEIGHBOR_CONSTRAINTS


def cmd_generate(output_dir: Path):
    """Genere toutes les structures CML (sans optimisation)."""
    import shutil

    # Nettoyer les anciens fichiers pour repartir proprement
    for size in [5, 6, 7]:
        cycle_dir = output_dir / f"cycle{size}"
        if cycle_dir.exists():
            shutil.rmtree(cycle_dir)

    builder = StructureBuilder()
    total = 0

    for size in [5, 6, 7]:
        constraints = NEIGHBOR_CONSTRAINTS[size]
        configs = generate_canonical_sequences(
            size,
            constraints['n_positions'],
            constraints['max'],
            constraints['min']
        )

        print(f"Cycle {size}: {len(configs)} configurations canoniques")

        for central_size, seq in configs:
            result = builder.build(central_size, seq, output_dir)
            if result:
                total += 1

        n_cml = len(list((output_dir / f'cycle{size}').glob('*.cml')))
        print(f"  Generes: {n_cml} fichiers")

    print(f"\nTotal : {total} structures creees dans {output_dir}/")


def cmd_optimize(output_dir: Path, threshold: float, steps: int):
    """Optimise les CML existants avec MMFF94, teste la planarite, genere le rapport."""
    from core.optimizer import optimize_cml, read_optimized_coords, read_coords_from_cml
    from utils.planarity import compute_planarity, is_planar
    from utils.report import generate_report
    import shutil
    import sys
    import xml.etree.ElementTree as ET

    # Verifier que obabel est disponible
    if not shutil.which("obabel"):
        print("ERREUR : obabel non trouve dans le PATH.")
        print("Installez Open Babel : conda install -c conda-forge openbabel")
        print("  ou : https://openbabel.org/wiki/Category:Installation")
        sys.exit(1)

    # Collecter tous les CML generes (exclure les *_opt.cml existants)
    cml_files = []
    for size in [5, 6, 7]:
        cycle_dir = output_dir / f"cycle{size}"
        if cycle_dir.exists():
            for f in sorted(cycle_dir.glob("*.cml")):
                if not f.stem.endswith("_opt"):
                    cml_files.append((size, f))

    if not cml_files:
        print("Aucun fichier CML trouve. Lancez d'abord : python main.py generate")
        sys.exit(1)

    print(f"Optimisation MMFF94 de {len(cml_files)} structures (seuil planarite: {threshold} A)")
    print()

    all_results = []

    for i, (central_size, cml_path) in enumerate(cml_files, 1):
        seq_str = cml_path.stem
        opt_path = cml_path.parent / f"{seq_str}_opt.cml"

        result = {
            'sequence': seq_str,
            'central_size': central_size,
            'n_carbons': 0,
            'cml_file': str(cml_path),
            'optimized': False,
            'planar': False,
            'max_deviation': 0.0,
            'rmsd_plane': 0.0,
            'height': 0.0,
            'opt_message': '',
        }

        # Lire nC depuis le titre du CML
        tree = ET.parse(str(cml_path))
        title = tree.getroot().get('title', '')
        for part in title.split():
            if part.startswith('n_C='):
                result['n_carbons'] = int(part.split('=')[1])

        # Optimisation MMFF94 (CML -> XYZ tmp -> obabel minimize -> XYZ opt)
        success, msg = optimize_cml(
            str(cml_path), str(opt_path),
            forcefield="mmff94", steps=steps
        )
        result['opt_message'] = msg

        if not success:
            print(f"  [{i}/{len(cml_files)}] {seq_str} — ECHEC : {msg}")
            all_results.append(result)
            continue

        result['optimized'] = True

        # Test de planarite sur les coordonnees XYZ optimisees
        coords_opt = read_optimized_coords(str(opt_path))
        if len(coords_opt) >= 3:
            metrics = compute_planarity(coords_opt)
            result['max_deviation'] = metrics['max_deviation']
            result['rmsd_plane'] = metrics['rmsd_plane']
            result['height'] = metrics['height']
            result['planar'] = is_planar(metrics, threshold)

        status = "PLANE" if result['planar'] else f"NON PLANE (dev={result['max_deviation']:.3f} A)"
        print(f"  [{i}/{len(cml_files)}] {seq_str} — {status}")

        all_results.append(result)

    # --- Rapport ---
    report_path = output_dir / "rapport_planarite.txt"
    generate_report(all_results, str(report_path))

    n_planar = sum(1 for r in all_results if r.get('planar'))
    n_non_planar = sum(1 for r in all_results
                       if not r.get('planar') and r.get('optimized'))
    n_failed = sum(1 for r in all_results if not r.get('optimized'))

    print()
    print(f"Resultats : {len(all_results)} structures")
    print(f"  Planes     : {n_planar}")
    print(f"  Non planes : {n_non_planar}")
    print(f"  Echecs     : {n_failed}")
    print(f"\nRapport : {report_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generateur de structures non-benzenoides polycycliques"
    )
    sub = parser.add_subparsers(dest="command", help="Commande a executer")

    # --- generate ---
    gen = sub.add_parser("generate", help="Generer toutes les structures CML")
    gen.add_argument("-o", "--output", default="output",
                     help="Dossier de sortie (defaut: output)")

    # --- optimize ---
    opt = sub.add_parser("optimize",
                         help="Optimiser MMFF94 + test planarite + rapport")
    opt.add_argument("-o", "--output", default="output",
                     help="Dossier contenant les CML (defaut: output)")
    opt.add_argument("-t", "--threshold", type=float, default=0.5,
                     help="Seuil planarite max_deviation en A (defaut: 0.5)")
    opt.add_argument("-s", "--steps", type=int, default=500,
                     help="Nombre d'etapes MMFF94 (defaut: 500)")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(Path(args.output))
    elif args.command == "optimize":
        cmd_optimize(Path(args.output), args.threshold, args.steps)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
