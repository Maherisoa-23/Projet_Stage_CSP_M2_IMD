"""Optimisation DETERMINISTE par perturbation z structuree + xtb --opt.

EVOLUTION (mai 2026, 2e revision) :
    Le protocole originel "md + opt" (xtb --md 1 ps a 298 K -> derniere frame
    -> xtb --opt) etait recommande par les chimistes pour casser les minima
    plats parasites. Mais il introduit un non-determinisme severe : xTB MD
    seede ses vitesses initiales sur l'horloge systeme, donc 2 runs
    identiques produisent des trajectoires differentes. Sur des structures
    tres tendues (5/7 alternes dense), ca menait a des verdicts qui
    basculaient entre PLAN et NON PLAN selon le tirage de vitesses.

    Choix arrete avec l'utilisateur : la priorite est le DETERMINISME (meme
    input -> meme output, byte-pour-byte). On accepte une legere perte de
    "physicalite" (pas d'exploration thermique) en echange de cette
    reproductibilite. Les chimistes valident : ils ne veulent pas tomber
    dans des analyses statistiques (multi-runs).

PROTOCOLE ACTUEL :
    1. Appliquer une perturbation z STRUCTUREE et DETERMINISTE :
           z_i' = z_i + amplitude * sin(2 * pi * i / N + phase)
       Pas de RNG. Identique a chaque appel. Brise la symetrie z=0 (qui
       imposerait un gradient nul perpendiculaire au plan a xtb --opt et
       le pieger sur le minimum plat).
    2. xtb perturbed.xyz --opt LEVEL
    3. Test de planarite ACP sur xtbopt.xyz

OUTPUT FILES (noms conserves pour retro-compat avec aggregate_md.py et
le viewer) :
    md.inp              # bloc $md mais mentionne method=det-opt + params
    md_geom.xyz         # geometrie perturbee (= input de l'opt)
    md_traj.xyz         # 2 frames : perturbed + final (mimique trajectoire)
    md_final_opt.xyz    # geometrie finale optimisee = reponse

DETERMINISME GARANTI :
    Avec OMP_NUM_THREADS=1 + MKL_NUM_THREADS=1 (deterministic=True, defaut)
    et la perturbation structuree, le pipeline est byte-deterministe :
    md5(md_final_opt.xyz) reste constant pour le meme input.xyz.

SANITY CHECKS + AUTO-RETRY :
    Conserves de l'ancien protocole MD :
      - returncode xTB
      - xtbopt.xyz existe et n'est pas vide
      - pas d'atome ejecte (norme > ejection_threshold, defaut 30 A)
    Avec un protocole deterministe, retry n'apporte rien sauf en cas de
    crash transitoire OS (out of memory, etc.). max_retries=3 conserve
    par defense.

LIMITES CONNUES :
    Une perturbation deterministe unique peut ne pas atteindre tous les
    minima accessibles depuis la geometrie 2D plate. Pour les cas
    bistables (2 minima energetiquement proches, l'un plat l'autre courbe),
    la perturbation choisie determine reproductiblement lequel sera
    atteint -- le verdict est stable mais peut differer du resultat MD.

LEGACY :
    L'ancien protocole MD est conserve sous git history (avant cette
    revision). Si necessaire on peut reactiver via une fonction dediee
    md_then_optimize_legacy. Cette strategy est independante de
    optimizer.py (qui fait --opt simple avec perturbation aleatoire).
"""

import math
import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Tuple, Optional


# Parametres de la perturbation structuree DETERMINISTE.
# Volontairement petits : on veut juste casser la symetrie z=0 sans deplacer
# significativement la molecule. xtb --opt revient au vrai minimum si la
# molecule est plane, ou diverge vers le minimum courbe sinon.
DEFAULT_PERTURB_PARAMS = {
    "amplitude": 0.05,  # Amplitude max en z (Angstroms)
    "phase": 0.5,       # Phase initiale du sinus (radians)
}

# Conservé pour rétro-compat : l'API publique accepte encore un dict params.
# Si l'utilisateur passe les anciennes cles MD (temp, time, dump, ...), elles
# sont silencieusement ignorees ; seules `amplitude` et `phase` ont un effet.
DEFAULT_MD_PARAMS = {
    "temp": 298.15, "time": 1.0, "dump": 50.0, "step": 4.0,
    "velo": False, "nvt": True, "hmass": 4, "sccacc": 2.0,
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


def _count_frames(traj_path: Path, n_atoms: int) -> int:
    """Compte le nombre de frames dans une trajectoire xTB.

    Chaque frame fait n_atoms+2 lignes. Tolerant aux fichiers vides ou
    trop courts (retourne 0 dans ces cas).
    """
    frame_lines = n_atoms + 2
    if not traj_path.exists():
        return 0
    n_lines = 0
    with open(traj_path) as f:
        for _ in f:
            n_lines += 1
    return n_lines // frame_lines


def _has_aberrant_atom(xyz_path: Path, threshold: float = 30.0) -> bool:
    """Detecte si la geometrie contient un atome ejecte (coords aberrantes).

    Calcule le barycentre puis verifie qu'aucun atome n'est plus loin que
    `threshold` Angstroms. Threshold defaut 30 A : pour les molecules h6
    (~10-15 A de rayon), un atome a 30+ A est forcement detache.

    Cas typique : xTB MD sur structure tendue ejecte un H qui s'envole
    a 35+ A de la molecule. Le test ACP retourne alors un angle bizarre
    pour la geometrie restante.
    """
    if not xyz_path.exists():
        return False
    coords = []
    with open(xyz_path) as f:
        try:
            n = int(f.readline().strip())
        except ValueError:
            return False
        f.readline()  # comment
        for _ in range(n):
            line = f.readline()
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                coords.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except ValueError:
                continue
    if not coords:
        return False
    cx = sum(c[0] for c in coords) / len(coords)
    cy = sum(c[1] for c in coords) / len(coords)
    cz = sum(c[2] for c in coords) / len(coords)
    threshold2 = threshold * threshold
    for x, y, z in coords:
        d2 = (x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2
        if d2 > threshold2:
            return True
    return False


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


def _expected_frames(md_params: dict) -> int:
    """[Legacy MD] Calcule le nb de frames attendu dans xtb.trj.

    Conserve pour retro-compat de tests / scripts qui auraient importe ce
    helper. Plus utilise dans le pipeline det-opt actuel (pas de trajectoire).
    """
    try:
        time_ps = float(md_params.get("time", 1.0))
        dump_fs = float(md_params.get("dump", 50.0))
    except (TypeError, ValueError):
        return 21
    if dump_fs <= 0:
        return 0
    return int(time_ps * 1000.0 / dump_fs) + 1


def _apply_structured_z_perturbation(input_path: Path, output_path: Path,
                                      amplitude: float = 0.05,
                                      phase: float = 0.5,
                                      mode: str = "structured",
                                      seed: int = 42) -> None:
    """Perturbation z DETERMINISTE.

    mode="structured" (defaut) :
      Pattern :  z_i' = z_i + amplitude * sin(2 * pi * i / N + phase)
      - Aucun RNG, byte-deterministe via parametres (amp, phase) seuls
      - Adapte aux geometries reconstruites sans atomes superposes

    mode="random" :
      Pattern :  z_i' = z_i + random.Random(seed).uniform(-amplitude, amplitude)
      - random.Random(seed) = sequence deterministe et reproductible
      - Brise plus efficacement les configurations dégénérées (atomes
        superposés des reconstructions 3D problematiques)
      - Mode de fallback pour les sols ou structured echoue

    Dans les deux cas :
      - Meme input.xyz + meme params -> meme output.xyz, byte-pour-byte
      - L'ordre des atomes est canonicalise par la reconstruction (sorted)
    """
    with open(input_path) as f:
        lines = f.readlines()
    n = int(lines[0].strip())
    atoms = []
    for i in range(2, 2 + n):
        parts = lines[i].split()
        atoms.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))

    if mode == "random":
        import random as _random
        rng = _random.Random(seed)
        deltas = [rng.uniform(-amplitude, amplitude) for _ in range(n)]
        comment = f"perturbed (random seed={seed} amp={amplitude})"
    else:
        two_pi = 2.0 * math.pi
        deltas = [amplitude * math.sin(two_pi * i / n + phase) for i in range(n)]
        comment = f"perturbed (structured amp={amplitude} phase={phase})"

    with open(output_path, "w") as f:
        f.write(f"{n}\n")
        f.write(f"{comment}\n")
        for i, (elem, x, y, z) in enumerate(atoms):
            f.write(f"{elem:<2s}  {x:14.6f}  {y:14.6f}  {z + deltas[i]:14.6f}\n")


def _write_minimal_md_inp(path: Path, params: dict):
    """Ecrit un md.inp minimal documentant la methode det-opt utilisee.
    Garde la syntaxe $md/$end pour que aggregate_md.py::read_md_params parse
    sans crasher, mais inscrit method=det-opt + amplitude + phase au lieu
    des parametres MD historiques.
    """
    with open(path, "w") as f:
        f.write("$md\n")
        f.write("   method=det-opt\n")
        f.write(f"   amplitude={params['amplitude']}\n")
        f.write(f"   phase={params['phase']}\n")
        f.write("$end\n")


def _try_det_opt_attempt(input_path: Path, work_dir: Path, perturb_params: dict,
                          opt_level: str, timeout_opt: int, env: dict,
                          ejection_threshold: float):
    """Une tentative deterministe : perturbation z structuree + xtb --opt.

    Sanity checks :
      L1.a : returncode xTB
      L1.b : xtbopt.xyz existe et n'est pas vide
      L1.c : geometrie finale n'a pas d'atome ejecte (norme > seuil)
    """
    in_xyz = work_dir / "input.xyz"
    shutil.copy2(input_path, in_xyz)

    # Etape 1 : perturbation z deterministe (structured ou random)
    perturbed = work_dir / "perturbed.xyz"
    try:
        _apply_structured_z_perturbation(
            in_xyz, perturbed,
            amplitude=float(perturb_params.get("amplitude", 0.05)),
            phase=float(perturb_params.get("phase", 0.5)),
            mode=str(perturb_params.get("mode", "structured")),
            seed=int(perturb_params.get("seed", 42)),
        )
    except (ValueError, OSError) as e:
        return False, f"Perturbation echouee : {e}", None

    # Etape 2 : xtb --opt sur le perturbe
    try:
        result_opt = subprocess.run(
            ["xtb", "perturbed.xyz", "--opt", opt_level],
            capture_output=True, text=True, timeout=timeout_opt,
            cwd=str(work_dir), env=env,
            encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        return False, "xtb non trouve dans le PATH", None
    except subprocess.TimeoutExpired:
        return False, f"Timeout opt apres {timeout_opt}s", None

    # L1.a : returncode opt
    if result_opt.returncode != 0:
        err = (result_opt.stderr or result_opt.stdout or "").strip().split("\n")[-3:]
        msg = f"Opt returncode={result_opt.returncode} | " + " | ".join(l.strip() for l in err if l.strip())
        return False, msg, None

    final = work_dir / "xtbopt.xyz"
    # L1.b : sortie opt absente
    if not final.exists() or final.stat().st_size == 0:
        err = (result_opt.stderr or result_opt.stdout or "").strip().split("\n")[-3:]
        return False, "xtbopt.xyz non genere | " + " | ".join(l.strip() for l in err if l.strip()), None

    # L1.c : geometrie finale a un atome ejecte
    if _has_aberrant_atom(final, ejection_threshold):
        return False, f"Atome ejecte dans la geometrie finale (>{ejection_threshold} A)", None

    converged = "GEOMETRY OPTIMIZATION CONVERGED" in (result_opt.stdout or "")
    artefacts = {
        "perturbed": perturbed,
        "final": final,
        "converged": converged,
        "stdout": result_opt.stdout or "",
    }
    return True, "OK (converge)" if converged else "OK (non converge, max iterations)", artefacts


def md_then_optimize(input_xyz: str,
                     output_dir: str,
                     params: Optional[dict] = None,
                     opt_level: str = "tight",
                     timeout_md: int = 600,           # legacy, ignore (pas de MD)
                     timeout_opt: int = 300,
                     deterministic: bool = True,
                     max_retries: int = 3,
                     ejection_threshold: float = 30.0) -> Tuple[bool, Optional[Path], dict]:
    """Optimisation DETERMINISTE via perturbation z structuree + xtb --opt.

    NB : Le nom md_then_optimize est conserve pour retro-compat avec les
    callers existants (csp_solver/reconstruction/pipeline.py::_run_md,
    csp_solver/utils/validation/md.py, etc.). En interne, ce n'est PLUS
    une vraie MD : on fait une perturbation analytique z = sin(...) +
    xtb --opt, ce qui est byte-deterministe (meme input -> meme output).

    Voir docstring du module pour la motivation et la specification du
    protocole. Le parametre `timeout_md` est ignore (pas de phase MD).

    Args:
        input_xyz          : XYZ d'entree (geometrie initiale, typiquement plate).
        output_dir         : repertoire OU les artefacts finals sont copies. Cree si besoin.
        params             : dict avec cles 'amplitude' (defaut 0.05 A) et
                             'phase' (defaut 0.5 rad). Les anciennes cles MD
                             (temp, time, dump, ...) sont silencieusement ignorees.
        opt_level          : niveau de convergence xTB pour l'opt (--opt LEVEL).
        timeout_md         : IGNORE (compat retro). Voir timeout_opt.
        timeout_opt        : timeout en secondes pour xtb --opt.
        deterministic      : True (defaut) -> force OMP=1+MKL=1 pour byte-determinisme.
        max_retries        : nb max de tentatives. Avec un protocole deterministe
                             le retry n'apporte rien sauf en cas de crash transitoire
                             OS (out of memory, etc.). Defaut 3 par defense.
        ejection_threshold : distance max d'un atome au barycentre (A) avant que
                             la geometrie soit consideree corrompue. Defaut 30 A.

    Sanity checks (chaque tentative) :
      - returncode xTB
      - xtbopt.xyz existe et n'est pas vide
      - pas d'atome ejecte (norme > ejection_threshold)

    Returns:
        (success, final_xyz_path, info_dict)
    """
    input_path = Path(input_xyz).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    perturb_params = dict(DEFAULT_PERTURB_PARAMS)
    if params:
        if "amplitude" in params:
            perturb_params["amplitude"] = params["amplitude"]
        if "phase" in params:
            perturb_params["phase"] = params["phase"]
        if "mode" in params:
            perturb_params["mode"] = params["mode"]
        if "seed" in params:
            perturb_params["seed"] = params["seed"]

    info = {
        "method": "det-opt",
        "params": dict(perturb_params),
        "deterministic": deterministic,
        "converged": False,
        "trajectory_file": None,
        "final_opt_file": None,
        "message": "",
        "attempts": [],          # erreurs des tentatives ratees
        "n_attempts": 0,
        "n_frames": 2,           # toujours 2 (perturbed + final) pour compat data.json
        "expected_frames": 2,
        "ejection_threshold": ejection_threshold,
    }

    env = _build_xtb_env(deterministic)

    for attempt_id in range(1, max_retries + 1):
        info["n_attempts"] = attempt_id
        work_dir = Path(tempfile.mkdtemp(prefix=f"xtb_optdet_a{attempt_id}_"))
        try:
            ok, msg, artefacts = _try_det_opt_attempt(
                input_path, work_dir, perturb_params, opt_level,
                timeout_opt, env, ejection_threshold
            )
            if ok:
                # Copie des artefacts dans output_dir. Noms de fichiers conserves
                # de l'ancien protocole MD pour retro-compat aggregate_md.py / viewer :
                #   md.inp           -> minimal $md mentionnant method=det-opt + params
                #   md_geom.xyz      -> geometrie perturbee (= input de l'opt)
                #   md_traj.xyz      -> 2 frames : perturbed + final (mimique trajectoire)
                #   md_final_opt.xyz -> geometrie optimisee (= reponse)
                out_md_inp = output_dir / "md.inp"
                out_md_geom = output_dir / "md_geom.xyz"
                out_traj = output_dir / "md_traj.xyz"
                out_final = output_dir / "md_final_opt.xyz"

                _write_minimal_md_inp(out_md_inp, perturb_params)
                shutil.copy2(artefacts["perturbed"], out_md_geom)
                # md_traj = concatenation perturbed + final
                with open(artefacts["perturbed"]) as fp_a, open(artefacts["final"]) as fp_b:
                    perturbed_content = fp_a.read()
                    final_content = fp_b.read()
                with open(out_traj, "w") as f:
                    if not perturbed_content.endswith("\n"):
                        perturbed_content += "\n"
                    f.write(perturbed_content)
                    f.write(final_content)
                shutil.copy2(artefacts["final"], out_final)
                if artefacts.get("stdout"):
                    (output_dir / "xtb.log").write_text(
                        artefacts["stdout"], encoding="utf-8"
                    )

                info["converged"] = artefacts["converged"]
                info["trajectory_file"] = out_traj.name
                info["final_opt_file"] = out_final.name
                if attempt_id > 1:
                    info["message"] = f"{msg} (apres {attempt_id} tentatives, {len(info['attempts'])} echecs)"
                else:
                    info["message"] = msg
                return True, out_final, info

            # Echec : on log et on retente (sauf si dernier essai)
            info["attempts"].append(f"tentative {attempt_id}/{max_retries}: {msg}")
        finally:
            shutil.rmtree(str(work_dir), ignore_errors=True)

    # Toutes les tentatives ont echoue
    info["message"] = (
        f"Echec apres {max_retries} tentatives. "
        f"Derniere erreur : {info['attempts'][-1] if info['attempts'] else '?'}"
    )
    return False, None, info
