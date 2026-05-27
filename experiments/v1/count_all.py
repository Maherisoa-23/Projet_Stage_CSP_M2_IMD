"""
Compte le nombre total de solutions CSP pour un dossier de .graph, sur les
8 combinaisons de flags CSP (--no-freeze, --no-table, --adj-57). Aucun xTB,
aucune reconstruction 3D : on s'arrete des qu'ACE a enumere les solutions.

Usage (depuis csp_solver/experiments/) :
    python count_all.py <dossier>

Exemple :
    python count_all.py plane/benzdb/h6
"""

import re
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

CSP_FLAGS = ["--no-freeze", "--no-table", "--adj-57"]
RE_NB_SOL = re.compile(r"Nombre de solutions\s*:\s*(\d+)")


def all_combinations():
    """Genere les 2^3 = 8 combinaisons de flags CSP."""
    combos = [()]
    for r in range(1, len(CSP_FLAGS) + 1):
        combos.extend(combinations(CSP_FLAGS, r))
    return combos


def config_name(flags):
    """Nom de config a partir des flags presents (cf. batch_main.py)."""
    if not flags:
        return "default"
    return "_".join(f.lstrip("-") for f in sorted(flags))


def count_one(main_py, graph_file, flags):
    """Lance main.py --count --all sur un .graph et retourne le nb de
    solutions (0 si parsing impossible, None en cas d'echec/timeout).

    --all est OBLIGATOIRE : sans lui, main.py force enumerate_all=False
    (cf. main.py L26) et ACE ne renvoie que la premiere solution trouvee,
    donc on aurait toujours 1 solution par instance."""
    cmd = [sys.executable, str(main_py), str(graph_file), "--count", "--all"] + list(flags)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    m = RE_NB_SOL.search(result.stdout)
    if not m:
        return 0  # ACE a peut-etre dit "Aucune solution trouvee"
    return int(m.group(1))


def main():
    if len(sys.argv) < 2:
        print("Usage: python count_all.py <dossier>")
        sys.exit(1)

    dossier = Path(sys.argv[1])
    if not dossier.is_dir():
        print(f"ERREUR : {dossier} n'est pas un dossier.")
        sys.exit(1)

    graphs = sorted(dossier.glob("*.graph"))
    if not graphs:
        print(f"Aucun fichier .graph dans {dossier}")
        sys.exit(1)

    main_py = Path(__file__).parent.parent / "main.py"
    combos = all_combinations()

    print(f"=== Count ALL : {len(combos)} configs x {len(graphs)} molecules sur {dossier} ===")
    print()

    t0 = time.time()
    # per_config[cfg_name] = liste de (mol_name, nb_sol_or_None)
    per_config = {}
    grand_total = 0
    n_failed = 0

    for i, flags in enumerate(combos, 1):
        cfg = config_name(flags)
        flags_str = " ".join(flags) if flags else "(default)"
        print(f"--- [{i}/{len(combos)}] {cfg}  flags: {flags_str} ---")
        sub_total = 0
        rows = []
        for j, graph_file in enumerate(graphs, 1):
            n = count_one(main_py, graph_file, flags)
            if n is None:
                rows.append((graph_file.stem, None))
                n_failed += 1
                print(f"  [{j:>3}/{len(graphs)}] {graph_file.name:<24} ECHEC")
            else:
                rows.append((graph_file.stem, n))
                sub_total += n
                print(f"  [{j:>3}/{len(graphs)}] {graph_file.name:<24} {n} sol.")
        per_config[cfg] = (rows, sub_total)
        grand_total += sub_total
        print(f"  -> sous-total {cfg}: {sub_total} solutions")
        print()

    elapsed = time.time() - t0
    h, rem = divmod(int(elapsed), 3600)
    m, s = divmod(rem, 60)
    duration = f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"

    print("=" * 60)
    print(f"=== Resume {dossier.name} ===")
    print("=" * 60)
    print(f"{'Configuration':<36} {'Solutions':>12}")
    print("-" * 50)
    for cfg in sorted(per_config.keys()):
        _, total = per_config[cfg]
        print(f"{cfg:<36} {total:>12}")
    print("-" * 50)
    n_instances = len(combos) * len(graphs)
    print(f"{'TOTAL':<36} {grand_total:>12}")
    print()
    print(f"Configurations testees : {len(combos)}")
    print(f"Molecules par config   : {len(graphs)}")
    print(f"Instances totales      : {n_instances}  (molecules x configs)")
    print(f"Solutions totales      : {grand_total}")
    if n_failed:
        print(f"Echecs                  : {n_failed}")
    print(f"Duree totale           : {duration} ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
