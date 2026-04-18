"""
Cree un zip portable avec les rapports HTML + les fichiers XYZ references.

Usage (depuis csp_solver/experiments/) :
    python bundle.py

Produit : experiments_bundle.zip a cote du script.
Le destinataire dezippe et ouvre report/index.html dans Chrome.
"""

import shutil
import zipfile
from pathlib import Path
from datetime import datetime


README = """Rapport d'experimentation -- Structures planes
================================================

Ouvrir report/index.html dans un navigateur (Chrome recommande).

Contenu :
  report/index.html      -- Rapport global avec graphiques et stats
  output/hX/view.html    -- Viewer interactif par taille (tri, filtres, comparaison de configs)
  output/hX/.../*.xyz    -- Fichiers de coordonnees optimisees (ouverts via les liens)

Navigation :
  - Dans report/index.html : clic sur une ligne h pour voir le detail par molecule.
  - Dans view.html : clic sur "Comparer" pour activer le mode comparaison multi-configs.

Genere le {date}.
"""


def collect_files(experiments_dir):
    """Retourne la liste des fichiers a inclure (chemins relatifs a experiments_dir)."""
    files = []

    # Rapport global
    index = experiments_dir / "report" / "index.html"
    if index.exists():
        files.append(index)
    else:
        print(f"  AVERTISSEMENT : {index} introuvable. Lance 'python update_report.py' d'abord.")

    output_dir = experiments_dir / "output"
    if not output_dir.is_dir():
        print("  AVERTISSEMENT : dossier output/ introuvable.")
        return files

    # view.html agreges par taille
    for view in sorted(output_dir.glob("*/view.html")):
        files.append(view)

    # Fichiers XYZ optimises (uniquement _opt.xyz, uniquement dans solutions/)
    # Couvre les 2 layouts : output/hX/config/mol/solutions/ et output/hX/mol/solutions/
    seen = set()
    for pattern in ("*/*/*/solutions/*_opt.xyz", "*/*/solutions/*_opt.xyz"):
        for xyz in sorted(output_dir.glob(pattern)):
            if xyz not in seen:
                seen.add(xyz)
                files.append(xyz)

    return files


def main():
    experiments_dir = Path(__file__).parent
    out_zip = experiments_dir / "experiments_bundle.zip"

    print("Collecte des fichiers...")
    files = collect_files(experiments_dir)
    if not files:
        print("ERREUR : aucun fichier a bundler.")
        return

    n_html = sum(1 for f in files if f.suffix == ".html")
    n_xyz = sum(1 for f in files if f.suffix == ".xyz")
    total_size = sum(f.stat().st_size for f in files)
    print(f"  {n_html} HTML + {n_xyz} XYZ ({total_size / 1024:.0f} Ko au total)")

    readme_content = README.format(date=datetime.now().strftime("%d/%m/%Y %H:%M"))

    print(f"Creation du zip : {out_zip.name}")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", readme_content)
        for f in files:
            arcname = f.relative_to(experiments_dir).as_posix()
            zf.write(f, arcname)

    zip_size = out_zip.stat().st_size
    print(f"Termine : {out_zip} ({zip_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    main()
