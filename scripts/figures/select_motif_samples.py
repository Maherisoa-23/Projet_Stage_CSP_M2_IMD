"""Selectionne le top 10 favorisants + top 10 defavorisants pour w=4 et w=5,
et resout pour chaque motif un sol_id exemple avec son sol_dir
(URL utilisee par le viewer pour ouvrir le modal 3D).

Output : tmp/motif_samples.json
{
  "samples": [
    {
      "motif": "6-6-6-6",
      "w": 4,
      "category": "fav",
      "n_total": ..., "pct_plan": ..., "delta_pp": ...,
      "sol_id": ..., "sol_dir": "...", "angle_deg": ..., "verdict": "...",
      "xyz_rel_path": "..."  // pour /api/mol3d?path=...
    },
    ...
  ]
}
"""

import csv
import json
import math
import sqlite3
import sys


def load_motif_csv(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        r["n_total"] = int(r["n_total"])
        r["n_plan"] = int(r["n_plan"])
        r["n_nonplan"] = int(r["n_nonplan"])
        r["pct_plan"] = float(r["pct_plan"])
        r["delta_pp"] = float(r["delta_pp"])
        r["score"] = abs(r["delta_pp"]) * math.sqrt(r["n_total"])
    return rows


def select_top(rows, n=10, sense=+1, min_total=1000):
    filt = [r for r in rows if r["n_total"] >= min_total and (sense * r["delta_pp"]) > 0]
    filt.sort(key=lambda r: -r["score"])
    return filt[:n]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect("experiments/final/final_h3_h9.db")
    conn.row_factory = sqlite3.Row

    rows_w4 = load_motif_csv("tmp/motifs_h8_w4.csv")
    rows_w5 = load_motif_csv("tmp/motifs_h8_w5.csv")

    samples = []
    for w, rows in [(4, rows_w4), (5, rows_w5)]:
        for cat, sense in [("fav", +1), ("def", -1)]:
            top = select_top(rows, n=10, sense=sense)
            for r in top:
                # Choisit le sol_id exemple : pour fav on prend un PLAN, pour def un NON_PLAN
                ex_str = r["ex_plan"] if (cat == "fav" and r["ex_plan"]) else r["ex_nonplan"]
                if not ex_str:
                    ex_str = r["ex_plan"] or r["ex_nonplan"]
                sol_id = int(ex_str.split(",")[0])
                row = conn.execute("""
                    SELECT s.sol_dir, s.angle_deg, s.verdict, fs.size_h
                    FROM solutions s
                    JOIN final_solutions fs ON fs.sol_id = s.id
                    WHERE s.id = ?
                """, (sol_id,)).fetchone()
                if not row:
                    # Fallback : direct depuis final_solutions
                    row2 = conn.execute("""
                        SELECT angle_deg, verdict, size_h, config, graph_name, sol_index
                        FROM final_solutions WHERE sol_id = ?
                    """, (sol_id,)).fetchone()
                    if not row2:
                        continue
                    sol_dir = f"final/h{row2['size_h']}/C1/{row2['graph_name']}/sol{row2['sol_index']}"
                    angle = row2["angle_deg"]
                    verdict = row2["verdict"]
                else:
                    sol_dir = row["sol_dir"]
                    angle = row["angle_deg"]
                    verdict = row["verdict"]
                xyz_rel = f"{sol_dir}/md_validation/md_final_opt.xyz"
                samples.append({
                    "motif": r["motif"],
                    "w": w,
                    "category": cat,
                    "n_total": r["n_total"],
                    "pct_plan": r["pct_plan"],
                    "delta_pp": r["delta_pp"],
                    "sol_id": sol_id,
                    "sol_dir": sol_dir,
                    "angle_deg": angle,
                    "verdict": verdict,
                    "xyz_rel_path": xyz_rel,
                })

    out = {"samples": samples, "n_samples": len(samples)}
    with open("tmp/motif_samples.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Ecrit tmp/motif_samples.json ({len(samples)} samples)")
    # Resume
    for s in samples:
        print(f"  w={s['w']} {s['category']:3s} {s['motif']:<11} sol_id={s['sol_id']:>7d} angle={s['angle_deg']:6.2f}° {s['verdict']}")
    conn.close()


if __name__ == "__main__":
    main()
