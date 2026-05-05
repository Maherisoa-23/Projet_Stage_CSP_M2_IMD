"""
Lance main.py sur tous les .graph d'un dossier.

Usage:
    python batch_main.py <dossier> [options main.py...]

Exemple:
    python batch_main.py plane/benzdb/h4 --validate
    python batch_main.py plane/benzdb/h4 --validate --no-freeze
    python batch_main.py plane/benzdb/h4 --validate --no-freeze --adj-57
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

# Force le single-thread pour toutes les libs scientifiques (xTB, BLAS, MKL...).
# Indispensable en cluster ou chaque coeur execute un job xTB independant.
# setdefault : si l'utilisateur a deja fixe une valeur, on la respecte.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
# Hash seed fige pour les sub-process : garantit l'ordre d'iteration sur les
# set/dict entre processus (defense en profondeur ; le fix principal est
# l'ajout de sorted() dans reconstruction/assembler.py).
os.environ.setdefault("PYTHONHASHSEED", "0")

# Flags CSP qui definissent une configuration (ordre alphabetique)
CSP_FLAGS = sorted(["--no-freeze", "--no-table", "--adj-57"])


def config_name(extra_args):
    """Derive le nom de config a partir des flags CSP presents."""
    flags = [f.lstrip("-") for f in CSP_FLAGS if f in extra_args]
    return "_".join(flags) if flags else "default"


def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_main.py <dossier> [options main.py...]")
        sys.exit(1)

    dossier = Path(sys.argv[1])
    extra_args = sys.argv[2:]
    main_py = Path(__file__).parent.parent / "main.py"
    test_py = Path(__file__).parent.parent / "test.py"
    # Dossier de sortie : configurable via la variable d'environnement
    # OUTPUT_ROOT (utile en cluster pour pointer vers un scratch local).
    # Defaut : csp_solver/experiments/output/ (comportement historique).
    output_base = Path(os.environ.get("OUTPUT_ROOT",
                                      str(Path(__file__).parent / "output")))
    view_py = Path(__file__).parent / "view.py"
    aggregate_runs_py = Path(__file__).parent / "aggregate_runs.py"
    aggregate_md_py = Path(__file__).parent / "aggregate_md.py"
    do_validate = "--validate" in extra_args

    # Detecter n_runs
    n_runs = 1
    if "--n-runs" in extra_args:
        idx = extra_args.index("--n-runs")
        try:
            n_runs = max(1, int(extra_args[idx + 1]))
        except (ValueError, IndexError):
            n_runs = 1

    # Detecter la strategy de validation. Defaut "md" depuis mai 2026 :
    # le protocole xtb --md + opt remplace les multi-runs comme defaut, plus
    # fiable physiquement et plus rapide (1 run au lieu de N=10). Pour
    # revenir a l'historique : --method multi-runs.
    method = "md"
    if "--method" in extra_args:
        idx = extra_args.index("--method")
        if idx + 1 < len(extra_args):
            method = extra_args[idx + 1]

    if not dossier.is_dir():
        print(f"ERREUR : {dossier} n'est pas un dossier.")
        sys.exit(1)

    graphs = sorted(dossier.glob("*.graph"))
    if not graphs:
        print(f"Aucun fichier .graph dans {dossier}")
        sys.exit(1)

    cfg = config_name(extra_args)
    h_dir = output_base / dossier.name
    config_dir = h_dir / cfg

    print(f"=== Batch main.py sur {dossier} ({len(graphs)} fichiers) ===")
    print(f"Config: {cfg}")
    print(f"n_runs: {n_runs}")
    print(f"Options: {extra_args if extra_args else '(aucune)'}")
    print()

    for i, graph_file in enumerate(graphs, 1):
        print(f"--- [{i}/{len(graphs)}] {graph_file.name} ---")
        mol_dir = config_dir / graph_file.stem

        # Nettoyer les anciens resultats de cette config
        if mol_dir.exists():
            shutil.rmtree(mol_dir)

        # Test de l'original (tout-6) si --validate
        if do_validate:
            mol_dir.mkdir(parents=True, exist_ok=True)
            cmd_test = [sys.executable, str(test_py), str(graph_file),
                        "--output-dir", str(mol_dir)]
            subprocess.run(cmd_test)

        # Resolution CSP + validation des solutions
        sol_dir = mol_dir / "solutions"
        sol_dir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(main_py), str(graph_file),
               "--output-dir", str(sol_dir)] + extra_args
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  ECHEC (code {result.returncode})")
        print()

    print(f"=== Termine : {len(graphs)} fichiers traites ===")

    # Generer les rapports si --validate
    if do_validate:
        print(f"\n=== Generation du rapport ({cfg}, methode={method}, n_runs={n_runs}) ===")
        # 1. data.json pour cette config -- dispatch selon la strategy.
        #    Chaque agregateur est ADDITIF : il met a jour son propre bloc
        #    (runs ou md_validation) sans toucher a l'autre. Si les 2 methodes
        #    ont ete lancees sequentiellement sur la meme config, les 2 blocs
        #    coexistent dans data.json.
        if method == "md":
            subprocess.run([sys.executable, str(aggregate_md_py), str(config_dir)])
        elif n_runs > 1:
            subprocess.run([sys.executable, str(aggregate_runs_py), str(config_dir)])
        else:
            subprocess.run([sys.executable, str(view_py), str(config_dir)])
        # 2. view.html agrege au niveau hX (independant de la strategy --
        #    le viewer detecte les blocs presents dans chaque data.json)
        subprocess.run([sys.executable, str(view_py), str(h_dir), "--aggregate"])


if __name__ == "__main__":
    main()
