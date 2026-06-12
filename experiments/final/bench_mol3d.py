"""Mesure empirique du cout des appels backend /api/mol3d, /api/kekule_list,
/api/clar_list, /api/rbo pour 3 sols h9 (angles ~0, ~20, ~89).

3 iterations par etape, moyenne reportee en ms. Pas de serveur Flask, on
appelle directement les fonctions du backend.
"""
import gzip
import sqlite3
import statistics
import time
from pathlib import Path

from viewer.molviz.bonds import build_mol_graph_from_text
from viewer.molviz.clar import enumerate_clar_covers
from viewer.molviz.kekule import assign_kekule, enumerate_kekule
from viewer.molviz.rbo import compute_rbo, DEFAULT_MAX_KEKULE

DB = Path("experiments/final/final_h3_h9.db")
N_ITER = 3


def fetch_sols():
    c = sqlite3.connect(DB)
    out = []
    for target in (0.0, 20.0, 89.0):
        row = c.execute(
            """SELECT sol_id, angle_deg, xyz_optimized_gz FROM final_solutions
               WHERE size_h=9 AND xyz_optimized_gz IS NOT NULL AND angle_deg IS NOT NULL
               ORDER BY ABS(angle_deg - ?) LIMIT 1""",
            (target,),
        ).fetchone()
        sol_id, angle, gz = row
        xyz = gzip.decompress(gz).decode("utf-8")
        out.append((target, sol_id, angle, xyz))
    c.close()
    return out


def timeit(fn, n=N_ITER):
    """Retourne (moyenne_ms, ecart_type_ms, dernier_resultat)."""
    samples = []
    res = None
    for _ in range(n):
        t0 = time.perf_counter()
        res = fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    mean = statistics.mean(samples)
    std = statistics.stdev(samples) if n > 1 else 0.0
    return mean, std, res


def bench_one(label, sol_id, angle, xyz):
    print(f"\n=== {label} : sol_id={sol_id} angle={angle:.2f} deg, "
          f"len(xyz)={len(xyz)} chars ===")

    # Warmup pour eviter le cout d'import/initialisation des modules
    # sur la premiere molecule mesuree.
    _ = build_mol_graph_from_text(xyz)

    # Etape 1 : parse XYZ + graphe + cycles
    m_parse, s_parse, mol = timeit(lambda: build_mol_graph_from_text(xyz))
    n_atoms = len(mol.atoms)
    n_bonds = len(mol.bonds)
    n_cycles = len(mol.cycles)
    print(f"  build_mol_graph     : {m_parse:7.2f} +/- {s_parse:5.2f} ms"
          f"   (atoms={n_atoms}, bonds={n_bonds}, cycles={n_cycles})")

    # Etape 2 : Kekule unique (assign_kekule, ce que fait /api/mol3d)
    m_k1, s_k1, kek = timeit(lambda: assign_kekule(mol))
    print(f"  assign_kekule (1)   : {m_k1:7.2f} +/- {s_k1:5.2f} ms"
          f"   (n_doubles={kek.n_doubles}, n_radicals={len(kek.radicals)},"
          f" perfect={kek.is_perfect})")

    # Etape 3 : enumerate_kekule (cap par defaut 200)
    m_ke, s_ke, (klist, exact_k) = timeit(lambda: enumerate_kekule(mol, max_count=200))
    print(f"  enumerate_kekule    : {m_ke:7.2f} +/- {s_ke:5.2f} ms"
          f"   (n={len(klist)}, exact={exact_k})")

    # Etape 4 : Clar Option A (hex)
    m_ca, s_ca, (covers_a, exa) = timeit(
        lambda: enumerate_clar_covers(mol, max_count=200, include_huckel_4n2=False)
    )
    print(f"  enumerate_clar A    : {m_ca:7.2f} +/- {s_ca:5.2f} ms"
          f"   (n={len(covers_a)}, exact={exa})")

    # Etape 5 : Clar Option B (hex + pent + hept)
    m_cb, s_cb, (covers_b, exb) = timeit(
        lambda: enumerate_clar_covers(mol, max_count=200, include_huckel_4n2=True)
    )
    print(f"  enumerate_clar B    : {m_cb:7.2f} +/- {s_cb:5.2f} ms"
          f"   (n={len(covers_b)}, exact={exb})")

    # Etape 6 : RBO (cap 10000)
    m_rbo, s_rbo, rbo = timeit(lambda: compute_rbo(mol, max_count=DEFAULT_MAX_KEKULE))
    print(f"  compute_rbo         : {m_rbo:7.2f} +/- {s_rbo:5.2f} ms"
          f"   (available={rbo.available}, n_kekule={rbo.n_kekule},"
          f" exact={rbo.is_exact})")

    total = m_parse + m_k1 + m_ke + m_ca + m_cb + m_rbo
    print(f"  TOTAL (somme moy.)  : {total:7.2f} ms")
    return {
        "label": label,
        "sol_id": sol_id,
        "angle": angle,
        "parse": m_parse,
        "kekule_1": m_k1,
        "kekule_enum": m_ke,
        "clar_a": m_ca,
        "clar_b": m_cb,
        "rbo": m_rbo,
        "n_kekule_enum": len(klist),
        "kekule_exact": exact_k,
        "n_clar_a": len(covers_a),
        "n_clar_b": len(covers_b),
        "rbo_n_kekule": rbo.n_kekule,
        "rbo_exact": rbo.is_exact,
    }


def main():
    sols = fetch_sols()
    results = []
    for target, sol_id, angle, xyz in sols:
        label = f"h9 angle~{int(target)}"
        results.append(bench_one(label, sol_id, angle, xyz))

    # Tableau recap
    print("\n\n=== RECAP (ms) ===")
    headers = ["label", "parse", "kek_1", "kek_enum", "clar_A", "clar_B", "rbo", "TOTAL"]
    print(" | ".join(f"{h:>10}" for h in headers))
    for r in results:
        total = r["parse"] + r["kekule_1"] + r["kekule_enum"] + r["clar_a"] + r["clar_b"] + r["rbo"]
        row = [r["label"], r["parse"], r["kekule_1"], r["kekule_enum"],
               r["clar_a"], r["clar_b"], r["rbo"], total]
        print(" | ".join([f"{row[0]:>10}"] + [f"{x:>10.2f}" for x in row[1:]]))


if __name__ == "__main__":
    main()
