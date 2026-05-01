"""
Agregateur de la strategy "md" : scanne un dossier de config et ajoute le
bloc 'md_validation' a chaque solution dans data.json.

Comportement ADDITIF : si data.json existe deja (cas typique : multi-runs a
deja ete lance avant sur la meme config), on charge le fichier existant et
on ajoute/met-a-jour le bloc 'md_validation' de chaque solution sans
toucher au reste (notamment au bloc 'runs' produit par aggregate_runs.py).
Cela permet d'avoir les 2 methodes coexistant pour la meme molecule.

Si data.json n'existe pas, on cree une structure minimale.

Structure attendue (post-strategy md) :
    <config_dir>/
      data.json                          (optionnel, cree/mis-a-jour)
      {mol_name}/
        {mol_name}_original.xyz
        {mol_name}_original_opt.xyz       (planarite de l'original, single-run)
        solutions/
          sol_<idx>_<sizes>/
            source.xyz
            md_validation/
              md.inp
              md_traj.xyz
              md_geom.xyz
              md_final_opt.xyz            <-- structure finale (planarite testee ici)

Usage :
    python aggregate_md.py <dossier_config>
"""

import sys
import json
import importlib.util
from pathlib import Path
from datetime import datetime

# --- Import du module planarity ---
_gen_root = Path(__file__).parent.parent.parent / "non_benzenoid_generator"
_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_gen_root / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar

THRESHOLD_DEG = 10.0


# =====================================================================
#  Lecture XYZ et test de planarite
# =====================================================================

def read_xyz_coords(xyz_path):
    coords = []
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 3:
        return coords
    n = int(lines[0].strip())
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return coords


def read_xyz_comment(xyz_path):
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    return lines[1].strip() if len(lines) >= 2 else ""


def parse_solution_comment(comment):
    if ":" in comment:
        return comment.split(":", 1)[1].strip()
    return comment


def test_planarity(xyz_path, threshold=THRESHOLD_DEG):
    coords = read_xyz_coords(str(xyz_path))
    if len(coords) < 3:
        return None
    metrics = compute_planarity(coords)
    return {
        "planar": is_planar(metrics, threshold),
        "angle_deg": round(metrics["max_angle_deg"], 2),
        "rmsd": round(metrics["rmsd_plane"], 4),
        "height": round(metrics["height"], 4),
    }


# =====================================================================
#  Lecture des params MD utilises (depuis md.inp)
# =====================================================================

def read_md_params(md_inp_path):
    """Parse un fichier md.inp xTB ($md / $end) et retourne un dict."""
    params = {}
    if not md_inp_path.exists():
        return params
    in_block = False
    with open(md_inp_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("$md"):
                in_block = True
                continue
            if line.startswith("$end"):
                in_block = False
                continue
            if not in_block or not line or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Conversion best-effort
            if val.lower() in ("true", "false"):
                val = (val.lower() == "true")
            else:
                try:
                    val = int(val)
                except ValueError:
                    try:
                        val = float(val)
                    except ValueError:
                        pass  # garder str
            params[key] = val
    return params


# =====================================================================
#  Aggregation principale
# =====================================================================

def aggregate_solution_md(sol_dir):
    """Pour un dossier sol_X_sizes/, retourne (sizes_str, md_validation_dict).
    Retourne (None, None) si md_validation/md_final_opt.xyz n'existe pas.
    """
    md_dir = sol_dir / "md_validation"
    final_xyz = md_dir / "md_final_opt.xyz"
    if not final_xyz.exists():
        return None, None

    # sizes : depuis le commentaire de source.xyz
    sizes = ""
    source = sol_dir / "source.xyz"
    if source.exists():
        sizes = parse_solution_comment(read_xyz_comment(str(source)))

    # Test planarite sur la structure finale
    plan = test_planarity(final_xyz)
    if plan is None:
        return None, None

    # Params MD (lecture du md.inp si present)
    md_inp = md_dir / "md.inp"
    params = read_md_params(md_inp)

    # Chemins relatifs au dossier mol/solutions/<sol_X>
    block = {
        "method": "md",
        "params": params,
        **plan,                                          # planar, angle_deg, rmsd, height
        "trajectory_file": "md_validation/md_traj.xyz",
        "final_opt_file": "md_validation/md_final_opt.xyz",
    }
    return sizes, block


def aggregate_config(config_dir):
    """Met a jour data.json en ajoutant les blocs md_validation aux solutions.

    Si data.json n'existe pas, cree une structure minimale {molecules:{}}.
    Si une solution n'a pas de md_validation/, on la laisse intacte.
    """
    config_dir = Path(config_dir)
    data_path = config_dir / "data.json"

    # Charger l'existant ou creer une coquille minimale
    if data_path.exists():
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {
            "source": config_dir.parent.name,
            "config": config_dir.name,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "threshold_deg": THRESHOLD_DEG,
            "molecules": {},
        }

    n_added = 0
    n_skipped = 0
    n_dropped_stale = 0    # entrees du data.json dont le sol_dir n'existe plus
    on_disk_mols = set()   # molecules effectivement presentes sur disque

    # Scanner les molecules du dossier de config
    for mol_dir in sorted(config_dir.iterdir()):
        if not mol_dir.is_dir():
            continue
        mol_name = mol_dir.name
        on_disk_mols.add(mol_name)
        sol_root = mol_dir / "solutions"
        if not sol_root.is_dir():
            continue

        # S'assurer que la molecule existe dans data.json
        mol_data = data["molecules"].setdefault(mol_name, {
            "name": mol_name,
            "original": None,
            "solutions": [],
        })

        # === Reconciliation : determiner les sizes presents sur disque ===
        # Une solution sur disque est un sous-dossier sol_<idx>_<sizes>/ avec
        # un source.xyz dont le commentaire donne le 'sizes'. Si source.xyz
        # est absent, on retombe sur le nom du dossier.
        on_disk_sizes = set()
        sol_dirs_by_sizes = {}
        for sol_dir in sorted(sol_root.iterdir()):
            if not sol_dir.is_dir():
                continue
            src = sol_dir / "source.xyz"
            if src.exists():
                sz = parse_solution_comment(read_xyz_comment(str(src)))
            else:
                sz = sol_dir.name
            if sz:
                on_disk_sizes.add(sz)
                sol_dirs_by_sizes[sz] = sol_dir

        # === Drop des entrees obsoletes ===
        # Une entree de data.json est consideree obsolete si son 'sizes' n'a
        # plus de sol_dir correspondant. Cas typique : un ancien run incluait
        # la solution tout-hexagones, le solveur ne la genere plus avec le
        # nouveau defaut (--count-hexagon absent), le sol_dir est absent, on
        # retire l'entree de data.json.
        before = len(mol_data.get("solutions", []))
        kept = []
        for s in mol_data.get("solutions", []):
            key = s.get("sizes") or s.get("file", "")
            if key in on_disk_sizes:
                kept.append(s)
            else:
                n_dropped_stale += 1
        mol_data["solutions"] = kept
        if before != len(kept):
            print(f"  [{mol_name}] {before - len(kept)} solution(s) obsolete(s) retiree(s)")

        # Index des solutions existantes par sizes (pour fusion additive)
        sol_index = {}
        for s in mol_data.get("solutions", []):
            key = s.get("sizes") or s.get("file", "")
            sol_index[key] = s

        # === Ajout/maj des blocs md_validation pour les solutions presentes ===
        for sizes, sol_dir in sol_dirs_by_sizes.items():
            mb_sizes, md_block = aggregate_solution_md(sol_dir)
            if md_block is None:
                continue
            # mb_sizes peut differer si source.xyz absent ; on garde celui calcule plus haut
            existing = sol_index.get(sizes)
            if existing is not None:
                # ADDITIF : ajouter md_validation, ne PAS toucher aux autres champs
                existing["md_validation"] = md_block
                n_added += 1
            else:
                # Solution non vue auparavant : creer une entree minimale.
                # 'planar', 'angle_deg', 'file' sont fixes par compatibilite ascendante
                # (le viewer single-run les lit).
                new_sol = {
                    "planar": md_block["planar"],
                    "angle_deg": md_block["angle_deg"],
                    "rmsd": md_block["rmsd"],
                    "height": md_block["height"],
                    "sizes": sizes,
                    "file": f"{sol_dir.name}/md_validation/md_final_opt.xyz",
                    "md_validation": md_block,
                }
                mol_data.setdefault("solutions", []).append(new_sol)
                sol_index[sizes] = new_sol
                n_added += 1

    # === Drop des molecules entieres qui n'existent plus sur disque ===
    # Cas extreme : un dossier mol_X/ a ete supprime entre 2 runs. On retire
    # son entree de data.json pour eviter d'afficher des fantomes.
    stale_mols = [m for m in list(data["molecules"].keys()) if m not in on_disk_mols]
    for m in stale_mols:
        del data["molecules"][m]
    if stale_mols:
        print(f"  {len(stale_mols)} molecule(s) obsolete(s) retiree(s) : {', '.join(stale_mols)}")

    # Mise a jour timestamp
    data["generated"] = datetime.now().isoformat(timespec="seconds")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  data.json -> {data_path}")
    print(f"  {n_added} bloc(s) md_validation ajoute(s)/mis-a-jour")
    if n_dropped_stale:
        print(f"  {n_dropped_stale} solution(s) obsolete(s) totale(s) retiree(s) du data.json")
    if n_skipped:
        print(f"  {n_skipped} solution(s) sautee(s) (pas de md_validation/)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python aggregate_md.py <dossier_config>")
        sys.exit(1)
    config_dir = Path(sys.argv[1])
    if not config_dir.is_dir():
        print(f"ERREUR : {config_dir} n'est pas un dossier.")
        sys.exit(1)
    print(f"Aggregation MD : {config_dir}")
    aggregate_config(config_dir)
    print("Termine.")


if __name__ == "__main__":
    main()
