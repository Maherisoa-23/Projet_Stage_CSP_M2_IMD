"""Agrege les resultats de validation et produit le rapport precision/recall.

Lit output_root/*.json (1 fichier par job) et tabule :
  - taux de plan reel (xTB) par (h, config)
  - precision MMFF = parmi mmff_sure_plan, % effectivement plan selon xTB
  - intervalle de confiance 95% (Wilson)

Usage :
    python -m csp_solver.experiments_v3.validation.aggregate \\
        --output-root /home/.../validation_run/output \\
        [--out /home/.../validation_report.txt]
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[3]))
    __package__ = "csp_solver.experiments_v3.validation"


def wilson_ci(p, n, z=1.96):
    """Wilson 95% CI pour une proportion."""
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z**2 / n
    center = (p + z**2 / (2*n)) / denom
    half = z * math.sqrt(p*(1-p)/n + z**2 / (4*n*n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--out", default=None,
                     help="fichier de rapport (sinon stdout)")
    args = ap.parse_args()

    out_root = Path(args.output_root)
    files = sorted(out_root.glob("*.json"))
    print(f"[lecture] {len(files)} fichiers dans {out_root}", flush=True)

    # buckets : (h, config) -> {ok: n, xtb_failed: n, planar: n, non_planar: n}
    buckets = defaultdict(lambda: {
        "ok": 0, "xtb_failed": 0, "failed": 0,
        "planar": 0, "non_planar": 0, "mmff_angles": [], "xtb_angles": [],
    })

    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        key = (d.get("h", "?"), d.get("config", "?"))
        s = d.get("status", "?")
        if s == "ok":
            buckets[key]["ok"] += 1
            if d.get("xtb_planar") is True:
                buckets[key]["planar"] += 1
            elif d.get("xtb_planar") is False:
                buckets[key]["non_planar"] += 1
            if d.get("mmff_angle_deg") is not None:
                buckets[key]["mmff_angles"].append(d["mmff_angle_deg"])
            if d.get("xtb_angle_deg") is not None:
                buckets[key]["xtb_angles"].append(d["xtb_angle_deg"])
        elif s == "xtb_failed":
            buckets[key]["xtb_failed"] += 1
        else:
            buckets[key]["failed"] += 1

    # Output
    lines = []
    lines.append("=" * 92)
    lines.append("VALIDATION MMFF SURE_PLAN PAR ECHANTILLONNAGE xTB")
    lines.append("=" * 92)
    lines.append("")
    lines.append("Pour chaque (h, config), N = nb de samples ok ; precision = "
                  "% reellement plan selon xTB")
    lines.append("CI95 = intervalle de confiance Wilson 95%")
    lines.append("")
    lines.append(f"{'h':<3} {'config':<22} {'N':>5} {'plan':>5} {'non':>5} "
                  f"{'xtb_fail':>9} {'precision':>10} {'CI95%':>16}")
    lines.append("-" * 92)

    total_n = total_plan = total_non = total_failed = 0
    for key in sorted(buckets):
        h, cfg = key
        d = buckets[key]
        n_ok = d["ok"]
        n_plan = d["planar"]
        n_non = d["non_planar"]
        n_xtb_fail = d["xtb_failed"]
        n_eval = n_plan + n_non
        if n_eval > 0:
            prec = n_plan / n_eval
            lo, hi = wilson_ci(prec, n_eval)
            prec_str = f"{prec*100:>7.1f}%"
            ci_str = f"[{lo*100:5.1f}-{hi*100:5.1f}]"
        else:
            prec_str = "    ---"
            ci_str = "    ---"
        lines.append(f"{h:<3} {cfg:<22} {n_ok:>5} {n_plan:>5} {n_non:>5} "
                      f"{n_xtb_fail:>9} {prec_str:>10} {ci_str:>16}")
        total_n += n_eval
        total_plan += n_plan
        total_non += n_non
        total_failed += n_xtb_fail

    lines.append("-" * 92)
    if total_n > 0:
        global_prec = total_plan / total_n
        lo, hi = wilson_ci(global_prec, total_n)
        lines.append(f"{'GLOBAL':<26} {total_n:>5} {total_plan:>5} {total_non:>5} "
                      f"{total_failed:>9} {global_prec*100:>7.1f}%  "
                      f"[{lo*100:.1f}-{hi*100:.1f}]")

    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"[ecrit] {args.out}", flush=True)
    print(text)


if __name__ == "__main__":
    main()
