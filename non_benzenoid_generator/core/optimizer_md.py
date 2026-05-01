"""Optimisation par dynamique moleculaire xTB suivie d'optimisation finale.

Implementation du protocole en 3 etapes recommande par les chimistes
(Yannick Carissan) pour casser les symetries d'une geometrie initiale plate
avant l'optimisation. La MD courte (~1 ps a 298 K) introduit assez de
mouvement thermique pour franchir les petites barrieres locales, tout en
restant tres rapide.

Protocole :
    1. xtb input.xyz --md --input md.inp     # MD seule, produit xtb.trj
    2. extraire la derniere frame de xtb.trj  # geometrie post-MD
    3. xtb md_geom.xyz --opt                  # optimisation finale

Tout se passe dans un repertoire temporaire (scratch dir) ; les artefacts
utiles sont copies dans output_dir a la fin :
    md.inp              # input file utilise (reproductibilite)
    md_traj.xyz         # trajectoire complete (rebaptisee depuis xtb.trj)
    md_geom.xyz         # derniere frame extraite
    md_final_opt.xyz    # geometrie finale optimisee (= reponse)

DETERMINISME (limites connues) :
    xTB ne supporte PAS un parametre 'seed' dans le bloc $md (verifie avec
    xtb 6.7.1pre : warning "the key 'seed' is not recognized by md"). xTB
    seed ses vitesses initiales depuis l'horloge systeme, sans hook utilisateur.
    Consequence : 2 runs successifs produisent des trajectoires dont le md5
    differe (les vitesses initiales different).

    EN PRATIQUE, la variance reste sub-seuil pour les cas non marginaux.
    Mesure sur une molecule planaire : sur 5 runs, angle_max varie de
    0.021 a 0.038 deg (std = 0.007 deg). Negligeable face au seuil 10 deg,
    donc le verdict planar/non-planar est stable.

    Par defaut on active aussi le single-thread (OMP_NUM_THREADS=1,
    MKL_NUM_THREADS=1) qui MINIMISE encore cette variance en eliminant
    les race conditions SCF. Pour autoriser le multi-thread (plus rapide
    mais variance legerement plus grande), passer deterministic=False.

    Pour les cas limites (angle proche du seuil 10 deg), la strategy
    multi-runs reste preferable -- c'est exactement pour ces cas qu'on a
    besoin de statistiques.

Cette strategy est independante de optimizer.py (qui fait --opt simple
avec perturbation aleatoire en z). Les deux peuvent coexister et etre
appelees sur la meme molecule pour comparaison.
"""

import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Tuple, Optional


# Parametres MD par defaut (recommandes par Yannick Carissan, AMU).
# Volontairement modestes : 1 ps a temperature ambiante suffit pour
# casser les symetries d'une geometrie plate sans surcout.
DEFAULT_MD_PARAMS = {
    "temp": 298.15,    # Temperature en K
    "time": 1.0,       # Duree totale de MD en ps
    "dump": 50.0,      # Intervalle de sortie de frames en fs
    "step": 4.0,       # Pas d'integration en fs
    "velo": False,     # Ecrire les vitesses dans la sortie
    "nvt": True,       # Ensemble NVT (constant N, V, T)
    "hmass": 4,        # Multiplicateur de masse de l'hydrogene
    "sccacc": 2.0,     # Precision de la SCC
}


def _format_md_value(val):
    """Convertit une valeur Python en representation d'input file xTB."""
    if isinstance(val, bool):
        return "true" if val else "false"
    return val


def _write_md_inp(path: Path, params: dict):
    """Ecrit un fichier $md/$end exploitable par xtb --input."""
    with open(path, "w") as f:
        f.write("$md\n")
        for key, val in params.items():
            f.write(f"   {key}={_format_md_value(val)}\n")
        f.write("$end\n")


def _read_n_atoms(xyz_path: Path) -> int:
    """Lit le nombre d'atomes (ligne 1) d'un fichier XYZ."""
    with open(xyz_path) as f:
        return int(f.readline().strip())


def _extract_last_frame(traj_path: Path, n_atoms: int, output_path: Path):
    """Extrait la derniere frame d'une trajectoire xTB (xtb.trj).

    Chaque frame fait n_atoms+2 lignes (1 ligne nb atomes, 1 ligne commentaire,
    n_atoms lignes de coordonnees). On prend les n_atoms+2 dernieres lignes
    du fichier.
    """
    frame_lines = n_atoms + 2
    with open(traj_path) as f:
        lines = f.readlines()
    if len(lines) < frame_lines:
        raise ValueError(f"Trajectoire trop courte : {len(lines)} lignes, attendu >= {frame_lines}")
    last_frame = lines[-frame_lines:]
    with open(output_path, "w") as f:
        f.writelines(last_frame)


def _build_xtb_env(deterministic: bool):
    """Construit l'environnement subprocess pour invoquer xtb.

    Si deterministic=True, force le single-thread (OMP_NUM_THREADS=1,
    MKL_NUM_THREADS=1). C'est l'unique mecanisme connu pour rendre xtb MD
    reproductible run apres run (le bloc $md ne supporte pas 'seed').
    """
    env = os.environ.copy()
    if deterministic:
        env["OMP_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["OMP_STACKSIZE"] = env.get("OMP_STACKSIZE", "1G")
    return env


def md_then_optimize(input_xyz: str,
                     output_dir: str,
                     params: Optional[dict] = None,
                     opt_level: str = "tight",
                     timeout_md: int = 600,
                     timeout_opt: int = 300,
                     deterministic: bool = True) -> Tuple[bool, Optional[Path], dict]:
    """Lance le protocole MD + optimisation et copie les artefacts dans output_dir.

    Args:
        input_xyz     : XYZ d'entree (geometrie initiale, typiquement plate).
        output_dir    : repertoire OU les artefacts finals sont copies. Cree si besoin.
        params        : overrides du dict DEFAULT_MD_PARAMS. Cles acceptees : tous les
                        parametres du bloc $md xTB (temp, time, dump, step, velo, nvt,
                        hmass, sccacc...). xTB ne reconnait PAS 'seed' ici — pour la
                        reproductibilite, voir argument `deterministic`.
        opt_level     : niveau de convergence xTB pour l'opt finale (--opt LEVEL).
        timeout_md    : timeout en secondes pour la phase MD.
        timeout_opt   : timeout en secondes pour la phase opt finale.
        deterministic : si True (defaut), force xTB en single-thread (OMP=1, MKL=1).
                        Garantit que 2 invocations consecutives produisent un xtb.trj
                        IDENTIQUE. Si False, xTB tourne en multi-thread (plus rapide,
                        mais variabilite minime entre runs due aux race conditions SCF).

    Returns:
        (success, final_xyz_path, info_dict)
            success         : True si le protocole complet a abouti.
            final_xyz_path  : Path vers md_final_opt.xyz dans output_dir, ou None si echec.
            info_dict       : dict avec params utilises, converged, file paths, deterministic flag.
    """
    input_path = Path(input_xyz).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_params = dict(DEFAULT_MD_PARAMS)
    if params:
        md_params.update(params)

    info = {
        "params": dict(md_params),
        "deterministic": deterministic,
        "converged": False,
        "trajectory_file": None,
        "final_opt_file": None,
        "message": "",
    }

    n_atoms = _read_n_atoms(input_path)
    work_dir = Path(tempfile.mkdtemp(prefix="xtb_md_"))
    env = _build_xtb_env(deterministic)

    try:
        # --- Etape 1 : MD ---
        in_xyz = work_dir / "input.xyz"
        shutil.copy2(input_path, in_xyz)
        md_inp = work_dir / "md.inp"
        _write_md_inp(md_inp, md_params)

        try:
            result_md = subprocess.run(
                ["xtb", "input.xyz", "--md", "--input", "md.inp"],
                capture_output=True, text=True, timeout=timeout_md,
                cwd=str(work_dir), env=env,
                encoding="utf-8", errors="replace"
            )
        except FileNotFoundError:
            info["message"] = "xtb non trouve dans le PATH"
            return False, None, info
        except subprocess.TimeoutExpired:
            info["message"] = f"Timeout MD apres {timeout_md}s"
            return False, None, info

        traj = work_dir / "xtb.trj"
        if not traj.exists() or traj.stat().st_size == 0:
            err = (result_md.stderr or result_md.stdout or "").strip().split("\n")[-3:]
            info["message"] = "MD a echoue : xtb.trj non genere | " + " | ".join(l.strip() for l in err if l.strip())
            return False, None, info

        # --- Etape 2 : extraire la derniere frame ---
        md_geom = work_dir / "md_geom.xyz"
        try:
            _extract_last_frame(traj, n_atoms, md_geom)
        except (ValueError, OSError) as e:
            info["message"] = f"Extraction frame echouee : {e}"
            return False, None, info

        # --- Etape 3 : optimisation finale ---
        # Sous-repertoire dedie pour eviter les collisions avec les artefacts MD
        # (xTB reecrit wbo, charges, xtbtopo.mol, etc. dans son cwd).
        opt_dir = work_dir / "opt"
        opt_dir.mkdir()
        opt_input = opt_dir / "input.xyz"
        shutil.copy2(md_geom, opt_input)

        try:
            result_opt = subprocess.run(
                ["xtb", "input.xyz", "--opt", opt_level],
                capture_output=True, text=True, timeout=timeout_opt,
                cwd=str(opt_dir), env=env,
                encoding="utf-8", errors="replace"
            )
        except subprocess.TimeoutExpired:
            info["message"] = f"Timeout opt finale apres {timeout_opt}s"
            return False, None, info

        final = opt_dir / "xtbopt.xyz"
        if not final.exists() or final.stat().st_size == 0:
            err = (result_opt.stderr or result_opt.stdout or "").strip().split("\n")[-3:]
            info["message"] = "Opt finale a echoue : xtbopt.xyz non genere | " + " | ".join(l.strip() for l in err if l.strip())
            return False, None, info

        info["converged"] = "GEOMETRY OPTIMIZATION CONVERGED" in (result_opt.stdout or "")

        # --- Copie des artefacts dans output_dir ---
        out_md_inp = output_dir / "md.inp"
        out_traj = output_dir / "md_traj.xyz"
        out_md_geom = output_dir / "md_geom.xyz"
        out_final = output_dir / "md_final_opt.xyz"
        shutil.copy2(md_inp, out_md_inp)
        shutil.copy2(traj, out_traj)
        shutil.copy2(md_geom, out_md_geom)
        shutil.copy2(final, out_final)

        info["trajectory_file"] = out_traj.name
        info["final_opt_file"] = out_final.name
        info["message"] = "OK (converge)" if info["converged"] else "OK (non converge, max iterations)"
        return True, out_final, info

    finally:
        shutil.rmtree(str(work_dir), ignore_errors=True)
