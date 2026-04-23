"""
Lance batch_main.py --validate pour toutes les combinaisons de contraintes.

Usage (depuis csp_solver/experiments/) :
    python batch_all.py <dossier> [--n-runs N]

Exemple:
    python batch_all.py plane/benzdb/h3
    python batch_all.py plane/benzdb/h3 --n-runs 10
"""

import sys
import json
import subprocess
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path

CSP_FLAGS = ["--no-freeze", "--no-table", "--adj-57"]


def all_combinations():
    """Genere toutes les combinaisons possibles (2^3 = 8)."""
    combos = [()]  # default (aucun flag)
    for r in range(1, len(CSP_FLAGS) + 1):
        combos.extend(combinations(CSP_FLAGS, r))
    return combos


def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_all.py <dossier> [--n-runs N]")
        sys.exit(1)

    dossier = sys.argv[1]
    passthrough = sys.argv[2:]  # propage --n-runs et autres options
    batch_main = Path(__file__).parent / "batch_main.py"
    combos = all_combinations()

    print(f"=== Batch ALL : {len(combos)} configurations sur {dossier} ===")
    if passthrough:
        print(f"Options propagees : {passthrough}")
    print()

    t0 = time.time()
    for i, flags in enumerate(combos, 1):
        name = " ".join(flags) if flags else "(default)"
        print(f"===== [{i}/{len(combos)}] {name} =====\n")
        cmd = [sys.executable, str(batch_main), dossier, "--validate"] + list(flags) + passthrough
        subprocess.run(cmd)
        print()
    elapsed = time.time() - t0

    # Collecte des stats depuis les data.json produits
    h_name = Path(dossier).name
    h_dir = Path(__file__).parent / "output" / h_name
    n_instances = 0
    n_solutions = 0
    for data_file in sorted(h_dir.glob("*/data.json")):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            mols = data.get("molecules", {})
            n_instances += len(mols)
            n_solutions += sum(len(m.get("solutions", [])) for m in mols.values())
        except (OSError, json.JSONDecodeError):
            pass

    h, rem = divmod(int(elapsed), 3600)
    m, s = divmod(rem, 60)
    duration = f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"

    # Ecrire batch_meta.json au niveau hX
    # Consomme par l'affichage pour montrer un bandeau "dernier run batch_all"
    meta = {
        "type": "batch_all",
        "source": dossier,
        "h": h_name,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "n_configs": len(combos),
        "n_instances": n_instances,
        "n_solutions": n_solutions,
        "duration_sec": round(elapsed, 1),
        "duration_str": duration,
        "options": passthrough,
    }
    h_dir.mkdir(parents=True, exist_ok=True)
    meta_path = h_dir / "batch_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"=== Termine : {len(combos)} configurations traitees ===")
    print(f"Duree totale      : {duration} ({elapsed:.1f}s)")
    print(f"Instances totales : {n_instances}  (molecules x configs)")
    print(f"Solutions totales : {n_solutions}")
    print(f"Meta sauvegarde   : {meta_path}")


if __name__ == "__main__":
    main()
