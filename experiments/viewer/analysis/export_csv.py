"""
Export CSV des top-K candidates pour partage aux chimistes.

Genere deux CSV dans analysis/output/ :
  - top_aromatic_<h>.csv     : structures planes + aromatiques
  - top_radical_<h>.csv      : structures planes + radicalaires

Chaque CSV contient les coordonnees (h, config, mol, sol_idx) et un
lien vers le viewer 3D (http://localhost:8765 par defaut). Cliquable
depuis Excel/LibreOffice.

Usage :
    python -m experiments.viewer.analysis.export_csv --h h6
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "experiments.viewer.analysis"

from .queries import top_aromatic_planar, top_radical_planar  # noqa: E402


_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = _HERE.parent / "db_v2.db"
_OUTPUT_DIR = _HERE / "output"


def _viewer_url(host: str, h: str, config: str, mol: str, sol_idx: int) -> str:
    """Construit une URL vers le viewer pointant sur cette solution.
    Utilise les query params attendus par la SPA."""
    return (
        f"http://{host}/?h={h}&config={config}&mol={mol}&sol={sol_idx}"
    )


def export_aromatic(conn, h, output_dir, host="127.0.0.1:8765",
                    k=50, max_angle=5.0, min_clar=2):
    rows = top_aromatic_planar(conn, h=h, k=k,
                                max_angle=max_angle, min_clar=min_clar)
    out_path = output_dir / f"top_aromatic_{h}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "h", "config", "mol", "sol_idx", "sizes", "angle_deg",
            "clar_number", "n_clar_covers", "cbo_mean_hex",
            "n_radicals", "viewer_url",
        ])
        for r in rows:
            url = _viewer_url(host, r["h"], r["config"], r["mol"], r["sol_idx"])
            writer.writerow([
                r["h"], r["config"], r["mol"], r["sol_idx"], r["sizes"],
                f"{r['angle_deg']:.4f}",
                r["clar_number"], r["n_clar_covers"],
                f"{r['cbo_mean_hex']:.4f}" if r["cbo_mean_hex"] is not None else "",
                r["n_radicals"],
                url,
            ])
    print(f"[export] {len(rows)} aromatiques planes -> {out_path}")
    return len(rows)


def export_radical(conn, h, output_dir, host="127.0.0.1:8765",
                   k=50, max_angle=5.0, min_radicals=1):
    rows = top_radical_planar(conn, h=h, k=k,
                                max_angle=max_angle, min_radicals=min_radicals)
    out_path = output_dir / f"top_radical_{h}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "h", "config", "mol", "sol_idx", "sizes", "angle_deg",
            "n_radicals", "clar_number", "n_kekule", "viewer_url",
        ])
        for r in rows:
            url = _viewer_url(host, r["h"], r["config"], r["mol"], r["sol_idx"])
            writer.writerow([
                r["h"], r["config"], r["mol"], r["sol_idx"], r["sizes"],
                f"{r['angle_deg']:.4f}",
                r["n_radicals"], r["clar_number"], r["n_kekule"],
                url,
            ])
    print(f"[export] {len(rows)} radicalaires planes -> {out_path}")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    parser.add_argument("--h", required=True, help="ex: h6")
    parser.add_argument("--k", type=int, default=50)
    parser.add_argument("--max-angle", type=float, default=5.0)
    parser.add_argument("--min-clar", type=int, default=2)
    parser.add_argument("--min-radicals", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1:8765",
                        help="host:port du viewer pour les URLs")
    parser.add_argument("--output", default=str(_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    export_aromatic(conn, args.h, output_dir,
                    host=args.host, k=args.k,
                    max_angle=args.max_angle, min_clar=args.min_clar)
    export_radical(conn, args.h, output_dir,
                   host=args.host, k=args.k,
                   max_angle=args.max_angle, min_radicals=args.min_radicals)

    conn.close()


if __name__ == "__main__":
    main()
