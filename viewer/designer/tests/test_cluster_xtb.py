"""Test minimal : aller-retour xtb sur cluster.

Verifie la chaine complete :
  1. Genere un benzene simple en local.
  2. Upload via scp vers un workdir temporaire sur le cluster.
  3. Lance xtb --opt a distance (conda env nonbenz).
  4. Rapatrie xtbopt.xyz en local.
  5. Cleanup du workdir distant.
  6. Affiche temps total + energie finale.

Si cela marche, l'option B (cluster pour le designer) est techniquement
validee : on a SSH sans password + xtb a distance + transfert de fichiers
bidirectionnel.

Usage:
    python tmp/test_cluster_xtb.py
"""

import subprocess
import sys
import time
from pathlib import Path


CLUSTER_HOST = "192.168.200.49"

# Commande shell qui charge conda + active nonbenz avant d'executer ce qui suit.
# Reproduit exactement ce qu'on a teste manuellement aux etapes precedentes.
_CONDA_INIT = (
    'eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" '
    '&& conda activate nonbenz'
)


# Benzene C6H6 (geometrie planaire de reference, longueurs CC=1.396, CH=1.088)
_BENZENE_XYZ = """12
benzene C6H6 (test cluster xtb)
C    1.39600   0.00000   0.00000
C    0.69800   1.20893   0.00000
C   -0.69800   1.20893   0.00000
C   -1.39600   0.00000   0.00000
C   -0.69800  -1.20893   0.00000
C    0.69800  -1.20893   0.00000
H    2.48400   0.00000   0.00000
H    1.24200   2.15117   0.00000
H   -1.24200   2.15117   0.00000
H   -2.48400   0.00000   0.00000
H   -1.24200  -2.15117   0.00000
H    1.24200  -2.15117   0.00000
"""


def _run(cmd, **kwargs):
    """subprocess.run avec capture, ecrit le retour code et le stderr en cas d'echec."""
    print(f"  > {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"    ECHEC (rc={result.returncode})")
        if result.stderr.strip():
            print(f"    stderr: {result.stderr.strip()[:500]}")
        if result.stdout.strip():
            print(f"    stdout: {result.stdout.strip()[:500]}")
    return result


def main():
    t0 = time.time()
    workdir_remote = f"~/_designer_cluster_test_{int(t0)}"
    local_dir = Path(__file__).resolve().parent
    local_input = local_dir / "benzene_input.xyz"
    local_output = local_dir / "benzene_opt.xyz"

    print("=== Etape 1/5 : Generation du benzene local ===")
    local_input.write_text(_BENZENE_XYZ, encoding="ascii")
    print(f"  Ecrit : {local_input}")

    print(f"\n=== Etape 2/5 : Creation du workdir distant {workdir_remote} ===")
    r = _run(["ssh", CLUSTER_HOST, f"mkdir -p {workdir_remote} && echo OK"])
    if r.returncode != 0 or "OK" not in r.stdout:
        print("ECHEC : impossible de creer le workdir distant.")
        return 1

    print(f"\n=== Etape 3/5 : Upload du benzene via scp ===")
    r = _run(["scp", str(local_input), f"{CLUSTER_HOST}:{workdir_remote}/input.xyz"])
    if r.returncode != 0:
        print("ECHEC : scp upload a echoue.")
        return 1

    print(f"\n=== Etape 4/5 : xtb --opt sur le cluster ===")
    remote_cmd = (
        f"{_CONDA_INIT} && cd {workdir_remote} && "
        f"xtb input.xyz --opt tight --silent 2>&1 | tail -20"
    )
    t_xtb_start = time.time()
    r = _run(["ssh", CLUSTER_HOST, remote_cmd])
    t_xtb = time.time() - t_xtb_start
    print(f"  Temps xtb distant : {t_xtb:.1f} s")
    if r.returncode != 0:
        print("ECHEC : xtb a echoue sur le cluster.")
        return 1
    for line in r.stdout.splitlines()[-10:]:
        print(f"    | {line}")

    print(f"\n=== Etape 5/5 : Rapatriement de xtbopt.xyz ===")
    r = _run(["scp", f"{CLUSTER_HOST}:{workdir_remote}/xtbopt.xyz", str(local_output)])
    if r.returncode != 0:
        print("ECHEC : impossible de rapatrier xtbopt.xyz.")
        return 1
    if not local_output.is_file():
        print(f"ECHEC : le fichier {local_output} n'existe pas apres scp.")
        return 1

    _run(["ssh", CLUSTER_HOST, f"rm -rf {workdir_remote}"])

    lines = local_output.read_text(encoding="utf-8").splitlines()
    energy_line = lines[1] if len(lines) > 1 else "<vide>"
    n_atoms = int(lines[0]) if lines and lines[0].strip().isdigit() else "?"

    total = time.time() - t0
    print()
    print("=" * 60)
    print("SUCCES : aller-retour cluster valide.")
    print(f"  Fichier local optimise : {local_output}")
    print(f"  Nombre d'atomes : {n_atoms}")
    print(f"  Ligne d'energie : {energy_line.strip()}")
    print(f"  Temps total : {total:.1f} s (dont xtb = {t_xtb:.1f} s)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
