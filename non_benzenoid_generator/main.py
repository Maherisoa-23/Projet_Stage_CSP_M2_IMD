#!/usr/bin/env python3
"""Generateur principal de structures non-benzenoides

Deux commandes :
  python main.py generate              # Genere 1228 structures CML + XYZ
  python main.py optimize              # Optimise xTB + test planarite + rapport
  python main.py optimize -t 15        # Seuil de planarite en degres
  python main.py optimize --level tight # Niveau de convergence xTB
"""

from pathlib import Path
from utils.symmetry import generate_canonical_sequences
from generators.builder import StructureBuilder
from config import NEIGHBOR_CONSTRAINTS


def cmd_generate(output_dir: Path):
    """Genere toutes les structures CML + XYZ (sans optimisation)."""
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

        n_files = len(list((output_dir / f'cycle{size}').glob('*.cml')))
        print(f"  Generes: {n_files} CML + {n_files} XYZ")

    print(f"\nTotal : {total} structures creees dans {output_dir}/")


def cmd_optimize(output_dir: Path, threshold: float, opt_level: str):
    """Optimise les XYZ avec xTB, teste la planarite, genere le rapport."""
    from core.optimizer import read_optimized_coords, verify_distances
    from core.optimizer_md import md_then_optimize
    from utils.planarity import compute_planarity, is_planar
    from utils.report import generate_report
    import shutil
    import sys
    import xml.etree.ElementTree as ET

    # Verifier que xtb est disponible
    if not shutil.which("xtb"):
        print("ERREUR : xtb non trouve dans le PATH.")
        print("Installez xTB :")
        print("  Windows : https://github.com/grimme-lab/xtb/releases")
        print("  Conda   : conda install -c conda-forge xtb")
        sys.exit(1)

    # Collecter tous les XYZ generes (exclure les *_opt.xyz)
    xyz_files = []
    for size in [5, 6, 7]:
        cycle_dir = output_dir / f"cycle{size}"
        if cycle_dir.exists():
            for f in sorted(cycle_dir.glob("*.xyz")):
                if not f.stem.endswith("_opt"):
                    xyz_files.append((size, f))

    if not xyz_files:
        print("Aucun fichier XYZ trouve. Lancez d'abord : python main.py generate")
        sys.exit(1)

    print(f"Validation MD (xtb --md 1ps a 298K + --opt {opt_level}) de {len(xyz_files)} structures")
    print(f"Seuil planarite : {threshold} deg")
    print()

    all_results = []

    for i, (central_size, xyz_path) in enumerate(xyz_files, 1):
        seq_str = xyz_path.stem
        opt_path = xyz_path.parent / f"{seq_str}_opt.xyz"

        result = {
            'sequence': seq_str,
            'central_size': central_size,
            'n_carbons': 0,
            'cml_file': str(xyz_path.with_suffix('.cml')),
            'optimized': False,
            'planar': False,
            'max_deviation': 0.0,
            'max_angle_deg': 0.0,
            'rmsd_plane': 0.0,
            'height': 0.0,
            'opt_message': '',
        }

        # Lire nC depuis le titre du CML correspondant
        cml_path = xyz_path.with_suffix('.cml')
        if cml_path.exists():
            tree = ET.parse(str(cml_path))
            title = tree.getroot().get('title', '')
            for part in title.split():
                if part.startswith('n_C='):
                    result['n_carbons'] = int(part.split('=')[1])

        # Validation MD : xtb --md 1ps a 298K -> derniere frame -> --opt tight.
        # Le protocole casse les minima plats parasites avant l'opt finale,
        # contrairement a optimize_xtb (--opt direct + perturbation z) qui
        # peut rester piege sur une geometrie 2D plate par construction.
        # Les artefacts MD (md.inp, md_traj.xyz, md_geom.xyz, md_final_opt.xyz)
        # sont sauves dans <seq>_md/ a cote du source ; on copie ensuite
        # md_final_opt.xyz vers opt_path pour que la suite du pipeline
        # (test ACP, rapport) reste inchangee.
        md_output_dir = xyz_path.parent / f"{seq_str}_md"
        success, final_xyz, info = md_then_optimize(
            str(xyz_path), str(md_output_dir),
            opt_level=opt_level, deterministic=True
        )
        if success and final_xyz:
            shutil.copy2(str(final_xyz), str(opt_path))
        msg = info.get("message") or ("OK" if success else "MD echec")
        result['opt_message'] = msg

        if not success:
            print(f"  [{i}/{len(xyz_files)}] {seq_str} — ECHEC MD/opt : {msg}")
            all_results.append(result)
            continue

        result['optimized'] = True

        # Verification des distances (C-C ~1.42, C-H ~1.08)
        dist_ok, dist_msg = verify_distances(str(opt_path))
        if not dist_ok:
            result['opt_message'] += f" | DISTANCES: {dist_msg}"

        # Test de planarite sur les coordonnees optimisees
        coords_opt = read_optimized_coords(str(opt_path))
        if len(coords_opt) >= 3:
            metrics = compute_planarity(coords_opt)
            result['max_deviation'] = metrics['max_deviation']
            result['max_angle_deg'] = metrics['max_angle_deg']
            result['rmsd_plane'] = metrics['rmsd_plane']
            result['height'] = metrics['height']
            result['planar'] = is_planar(metrics, threshold)

        status = "PLANE" if result['planar'] else f"NON PLANE ({result['max_angle_deg']:.1f} deg)"
        print(f"  [{i}/{len(xyz_files)}] {seq_str} — {status}")

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
    gen = sub.add_parser("generate", help="Generer toutes les structures CML + XYZ")
    gen.add_argument("-o", "--output", default="output",
                     help="Dossier de sortie (defaut: output)")

    # --- optimize ---
    opt = sub.add_parser("optimize",
                         help="Optimiser xTB + test planarite + rapport")
    opt.add_argument("-o", "--output", default="output",
                     help="Dossier contenant les XYZ (defaut: output)")
    opt.add_argument("-t", "--threshold", type=float, default=10.0,
                     help="Seuil planarite en degres (defaut: 10.0)")
    opt.add_argument("--level", default="tight",
                     choices=["crude", "sloppy", "loose", "lax",
                              "normal", "tight", "vtight", "extreme"],
                     help="Niveau de convergence xTB (defaut: tight)")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(Path(args.output))
    elif args.command == "optimize":
        cmd_optimize(Path(args.output), args.threshold, args.level)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
