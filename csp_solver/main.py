"""
Point d'entree du solveur CSP pour les non-benzenoides.

Usage:
    python main.py <fichier.graph> [--all] [--count] [--validate]
                                   [--count-hexagon]

Options:
    --all            : enumerer toutes les solutions (defaut)
    --count          : afficher seulement le nombre de solutions
    --validate       : valider les solutions avec xTB + test planarite
    --count-hexagon  : inclure la solution tout-hexagones (le benzenoide
                       d'origine) dans la liste. Defaut : exclue, puisque
                       l'objectif est d'enumerer les substitutions
                       non-benzenoides. Le benzenoide d'origine reste
                       teste separement par test.py.
"""

import sys
import os
from pathlib import Path

# Sauvegarder nos arguments AVANT d'importer pycsp3,
# car pycsp3 intercepte sys.argv a l'import.
_own_argv = sys.argv[:]
filepath = _own_argv[1] if len(_own_argv) >= 2 else None
count_only = "--count" in _own_argv
do_validate = "--validate" in _own_argv
no_freeze = "--no-freeze" in _own_argv
adj_57 = "--adj-57" in _own_argv
no_table = "--no-table" in _own_argv
# Table de voisinage alternative (cf. csp_solver/utils/table.py::load_table
# et viewer/designer/tables_mgmt.py pour le CRUD cote designer). None =
# table par defaut du projet (data/table_voisinage.json).
table_path = None
if "--table-path" in _own_argv:
    idx = _own_argv.index("--table-path")
    if idx + 1 < len(_own_argv):
        table_path = _own_argv[idx + 1]
# Par defaut, le solveur exclut la solution tout-hexagones (le benzenoide
# d'origine). Le flag --count-hexagon la reintroduit dans la liste.
count_hexagon = "--count-hexagon" in _own_argv
enumerate_all = "--all" in _own_argv or not count_only
output_dir = None
if "--output-dir" in _own_argv:
    idx = _own_argv.index("--output-dir")
    if idx + 1 < len(_own_argv):
        output_dir = _own_argv[idx + 1]
n_runs = 1
if "--n-runs" in _own_argv:
    idx = _own_argv.index("--n-runs")
    if idx + 1 < len(_own_argv):
        try:
            n_runs = max(1, int(_own_argv[idx + 1]))
        except ValueError:
            n_runs = 1
# Strategy de validation. Defaut "md" depuis mai 2026 (protocole xtb --md
# + opt, recommande par les chimistes -- casse les minima plats parasites).
# Pour revenir a l'ancien comportement multi-runs : --method multi-runs.
# Voir utils.validation.list_strategies() pour les valeurs acceptees.
method = "md"
if "--method" in _own_argv:
    idx = _own_argv.index("--method")
    if idx + 1 < len(_own_argv):
        method = _own_argv[idx + 1]
# MD : par defaut deterministe (single-thread). Flag pour autoriser le multi-thread
# (plus rapide mais runs non-reproductibles -- xTB n'a pas de seed pour MD).
md_deterministic = "--md-no-deterministic" not in _own_argv

# Cache xTB (cf. csp_solver/xtb/cache.py) : optionnel, evite de relancer xTB
# pour une solution deja calculee (meme source.xyz + memes parametres).
# Utilise par le designer web (viewer/designer/runner.py) qui connait
# toujours son db_path ; absent en CLI pur (pas de dependance sqlite forcee).
cache_db_path = None
if "--cache-db" in _own_argv:
    idx = _own_argv.index("--cache-db")
    if idx + 1 < len(_own_argv):
        cache_db_path = _own_argv[idx + 1]

# --- Contraintes additionnelles (issues d'experiments_v2/v3) ---
# Toutes optionnelles : None = desactivees.
def _parse_int_arg(flag_name):
    """Renvoie int(value) du flag, ou None s'il n'est pas present."""
    if flag_name not in _own_argv:
        return None
    idx = _own_argv.index(flag_name)
    if idx + 1 >= len(_own_argv):
        return None
    try:
        return int(_own_argv[idx + 1])
    except ValueError:
        return None

K_sym = _parse_int_arg("--sym")   # |n_pent - n_hept| <= K_sym
K_pb  = _parse_int_arg("--pb")    # nb_pent_au_bord <= K_pb
K_hb  = _parse_int_arg("--hb")    # nb_hept_au_bord <= K_hb
K_tot = _parse_int_arg("--tot")   # nb_pent + nb_hept <= K_tot
tau_gb = _parse_int_arg("--tau-gb")        # Gauss-Bonnet local (v3)
radius_gb = _parse_int_arg("--radius-gb") or 2  # rayon BFS Gauss-Bonnet

# Ctopo : contrainte blacklist rayon-2 + pre-check n_peri (juin 2026)
ctopo_filter = "--ctopo" in _own_argv
ctopo_min_n_peri = _parse_int_arg("--ctopo-min-n-peri") or 4

# Solveur CSP : 'choco' (defaut) ou 'ace' (LEGACY, conserve pour
# reproductibilite du run final cluster). La migration vers Choco a ete
# decidee suite au bench complet (cf. doc/choco_vs_ace.md) : Choco gagne
# en moyenne sur ce corpus, et la difference marginale de propagation
# de LexIncreasing est corrigee par un post-filtre dedup_by_orbit cote
# Python.
solver_name = "choco"
if "--solver" in _own_argv:
    idx = _own_argv.index("--solver")
    if idx + 1 < len(_own_argv):
        solver_name = _own_argv[idx + 1].lower()
        if solver_name not in ("choco", "ace"):
            print(f"ERREUR : --solver doit etre 'choco' ou 'ace', recu '{solver_name}'",
                  file=sys.stderr)
            sys.exit(1)

# --- Preset (catalogue presets.py) ---
# Si --preset NAME est passe, il SURCHARGE les flags individuels (sauf
# ceux qui sont deja explicites en CLI).
preset_name = None
if "--preset" in _own_argv:
    idx = _own_argv.index("--preset")
    if idx + 1 < len(_own_argv):
        preset_name = _own_argv[idx + 1]
if preset_name:
    from csp_solver.presets import get_preset
    try:
        _preset = get_preset(preset_name)
    except KeyError as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)
    # Les flags du preset sont appliques SAUF si le user les a deja
    # explicites en ligne de commande (=> les CLI gagnent).
    if K_sym is None and "K_sym" in _preset:
        K_sym = _preset["K_sym"]
    if K_pb  is None and "K_pb"  in _preset:
        K_pb  = _preset["K_pb"]
    if K_hb  is None and "K_hb"  in _preset:
        K_hb  = _preset["K_hb"]
    if K_tot is None and "K_tot" in _preset:
        K_tot = _preset["K_tot"]
    if tau_gb is None and "tau_gb" in _preset:
        tau_gb = _preset["tau_gb"]
    if "radius_gb" in _preset:
        radius_gb = _preset["radius_gb"]
    if not adj_57 and _preset.get("adj_57"):
        adj_57 = True

# Nettoyer sys.argv pour que pycsp3 ne les intercepte pas
sys.argv = [_own_argv[0]]

# Ajouter le dossier csp_solver/ au path (pour 'from utils.X import Y')
# ET son parent (pour 'from csp_solver.X import Y' utilise dans les
# sous-modules reconstruction/, utils/validate.py, etc.)
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from utils.parser import parse
from utils.preprocessing import preprocess
from utils.model import build_and_solve, format_solution


def main():
    if filepath is None:
        print("Usage: python main.py <fichier.graph> [options]")
        print("  --all         : enumerer toutes les solutions (defaut)")
        print("  --count       : afficher seulement le nombre de solutions")
        print("  --validate    : valider les solutions avec xTB + test planarite")
        print("  --no-freeze   : desactiver la contrainte des hexagones geles (b(v)>=2)")
        print("  --no-table    : desactiver la contrainte de table de voisinage (C3)")
        print("  --adj-57      : activer la contrainte d'adjacence 5-7 (C5)")
        print("  --sym K       : limite |n_pent - n_hept| <= K (C-SYM, v2)")
        print("  --pb K        : limite nb pent en bord <= K (C-PB, v2)")
        print("  --hb K        : limite nb hept en bord <= K (C-HB, v2)")
        print("  --tot K       : limite nb pent + nb hept <= K (C-TOT, v2)")
        print("  --n-runs N    : nombre d'optimisations xTB par solution (defaut 1)")
        print("  --method M    : strategy de validation (defaut 'multi-runs')")
        print("                  voir utils/validation/ pour les strategies disponibles")
        print("  --md-no-deterministic : autoriser xTB MD multi-thread (plus rapide,")
        print("                          mais runs non-reproductibles ; defaut deterministe)")
        print("  --solver S    : solveur CSP, 'choco' (defaut) ou 'ace' (LEGACY)")
        print("                  Choco est par defaut depuis juin 2026 (cf. doc/choco_vs_ace)")
        print("  --cache-db PATH : active le cache xTB dans cette DB sqlite (methode md)")
        print("  --table-path PATH : utilise cette table de voisinage au lieu de la table par defaut")
        print("Exemple: python main.py data/first.graph --validate --n-runs 10")
        print("Exemple: python main.py data/first.graph --validate --method md")
        sys.exit(1)

    # --- Etape 1 : Lecture du fichier Benzai ---
    print(f"=== Lecture de {filepath} ===")
    graph = parse(filepath)
    print(graph.summary())
    print()

    # --- Etape 2 : Pre-traitement ---
    print("=== Pre-traitement ===")
    preprocessed = preprocess(graph, freeze_b2=not no_freeze, table_path=table_path)
    if no_freeze:
        print("  (contrainte b(v)>=2 DESACTIVEE, seuls les deg=6 sont geles)")
    if table_path:
        print(f"  Table de voisinage : {table_path}")

    frozen = preprocessed['frozen']
    free = preprocessed['free']
    generators = preprocessed['generators']

    print(f"Hexagones geles: {len(frozen)} {frozen}")
    print(f"Hexagones libres: {len(free)} {free}")
    print(f"Generateurs Aut(G_D): {len(generators)}")
    for i, gen in enumerate(generators):
        mapping = ", ".join(f"v{k}->v{v}" for k, v in sorted(gen.items()) if k != v)
        print(f"  pi_{i+1}: {mapping}")

    tables_info = preprocessed['tables']
    for v, t in tables_info.items():
        print(f"  Table v{v}: {len(t)} entrees admissibles")
    print()

    # --- Etape 3 : Resolution ---
    print("=== Resolution CSP ===")
    print(f"  Solveur : {solver_name.upper()}"
          f"{' (LEGACY)' if solver_name == 'ace' else ' (defaut)'}")
    if adj_57:
        print("  Contrainte C5 (adjacence 5-7) : ACTIVEE")
    if no_table:
        print("  Contrainte C3 (table voisinage) : DESACTIVEE")
    if count_hexagon:
        print("  Solution tout-hexagones : INCLUSE (--count-hexagon)")
    else:
        print("  Solution tout-hexagones : EXCLUE (defaut)")
    extras = []
    if preset_name: extras.append(f"preset={preset_name}")
    if K_sym is not None: extras.append(f"sym={K_sym}")
    if K_pb  is not None: extras.append(f"pb={K_pb}")
    if K_hb  is not None: extras.append(f"hb={K_hb}")
    if K_tot is not None: extras.append(f"tot={K_tot}")
    if tau_gb is not None and tau_gb >= 0: extras.append(f"curv={tau_gb}(r={radius_gb})")
    if extras:
        print(f"  Contraintes additionnelles : {' '.join(extras)}")
    solutions = build_and_solve(graph, preprocessed, enumerate_all=enumerate_all,
                                adj_57=adj_57, no_table=no_table,
                                count_hexagon=count_hexagon,
                                K_sym=K_sym, K_pb=K_pb, K_hb=K_hb, K_tot=K_tot,
                                tau_gb=tau_gb, radius_gb=radius_gb,
                                ctopo_filter=ctopo_filter,
                                ctopo_min_n_peri=ctopo_min_n_peri,
                                solver=solver_name)

    if not solutions:
        print("Aucune solution trouvee.")
        return

    print(f"Nombre de solutions: {len(solutions)}")
    print()

    if not count_only:
        # --- Etape 4 : Affichage ---
        print("=== Solutions ===")
        for i, sol in enumerate(solutions, 1):
            print(format_solution(sol, i))

        # Resume
        print()
        print("=== Resume ===")
        print(f"Source: {filepath} (h={graph.h}, |E_D|={graph.dual.number_of_edges()})")
        print(f"Solutions distinctes (apres rupture de symetrie): {len(solutions)}")

        # Statistiques sur les solutions
        counts = {5: 0, 6: 0, 7: 0}
        for sol in solutions:
            for v, size in sol.items():
                counts[size] += 1
        total = len(solutions) * graph.h
        print(f"Repartition des tailles sur toutes les solutions:")
        for size in (5, 6, 7):
            pct = 100 * counts[size] / total if total > 0 else 0
            print(f"  Taille {size}: {counts[size]} ({pct:.1f}%)")

    # --- Etape 5a : Materialisation des sols sans validation xTB ---
    # Cas method=skip (designer) : on veut quand meme avoir les sol_dirs sur
    # disque avec source.xyz (reconstruction plate z=0) pour pouvoir les
    # visualiser dans le viewer 3D, mais sans payer le cout xTB.
    # Cette branche s'active si --output-dir est fourni ET --validate absent.
    if not do_validate and output_dir and solutions:
        from pathlib import Path
        from reconstruction import reconstruct_molecule, export_xyz
        print()
        print("=== Materialisation sans validation xTB (mode skip) ===")
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        n_materialized = 0
        for i, sol in enumerate(solutions):
            sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))
            sol_dir = out / f"sol_{i}_{sizes_str}"
            sol_dir.mkdir(exist_ok=True)
            try:
                mol = reconstruct_molecule(graph, sol)
                export_xyz(mol, str(sol_dir / "source.xyz"),
                            comment=f"sol {i} (method=skip, no xtb)")
                n_materialized += 1
            except Exception as e:
                # Reconstruction echoue : on log mais on continue
                print(f"  sol_{i} : reconstruction echouee ({type(e).__name__}: {e})")
        print(f"  {n_materialized}/{len(solutions)} sols materialisees dans {out}")

    # --- Etape 5b : Validation xTB ---
    if do_validate and solutions:
        print()
        print("=== Validation xTB + planarite ===")
        if cache_db_path:
            from csp_solver.xtb.cache import init_cache_table
            init_cache_table(cache_db_path)
        from reconstruction import reconstruct_and_validate
        reconstruct_and_validate(graph, solutions, output_dir=output_dir,
                                 n_runs=n_runs, method=method,
                                 md_deterministic=md_deterministic,
                                 cache_db_path=cache_db_path)


if __name__ == "__main__":
    main()
