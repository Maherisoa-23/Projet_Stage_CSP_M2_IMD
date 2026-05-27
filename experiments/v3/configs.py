"""Presets CSP-LEVEL pour experiments_v3.

Chaque preset = nom + dict de parametres K_sym, K_pb, K_hb, K_tot, tau_gb.

Les parametres de filtrage MMFF/xTB (th_sure_plan, th_sure_non_plan,
xtb_mode) sont separes : ils relevent du pipeline post-CSP, pas du
modele CSP. Cela permet de tester la meme config CSP avec et sans MMFF.

Selon validation B (~111k mols db_v2), le preset par defaut conseille
est "sym1_pb2_curv1" qui combine les 3 contraintes les plus utiles :
  K_sym=1, K_pb=2, tau_gb=1 (radius_gb=2)
Gain mesure (S3 combine) : speedup xTB 2.7-3.2x, ~80% des plans capture.
"""

CONFIGS = {
    "baseline_v3": {
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": None,
        "radius_gb": 2,
    },
    "curv1": {
        # Gauss-Bonnet seul (tau=1, r=2) -- defaut conseille pour Gauss-Bonnet
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "curv0": {
        # Gauss-Bonnet strict (tau=0, r=2) -- forte filtrage, perd ~75% plans
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 0,
        "radius_gb": 2,
    },
    "sym1_curv1": {
        "K_sym": 1,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "pb2_curv1": {
        "K_sym": None,
        "K_pb": 2,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "sym1_pb2_curv1": {
        # PRESET PAR DEFAUT recommande (compromis efficacite/diversite)
        "K_sym": 1,
        "K_pb": 2,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "pb1_curv1": {
        # Decouverte experimentale (autre piste) : pb1 seul donne 68.9% plan
        # sur h7 (vs 50.5% baseline, +18 pts). Combine ici avec curv1.
        "K_sym": None,
        "K_pb": 1,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "sym1_pb1_curv1": {
        # Variante plus stricte : pb=1 ET sym=1 ET curv=1
        "K_sym": 1,
        "K_pb": 1,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "all_strict_curv0": {
        # Strict : sym=0, pb=2, hb=3, curv=0 -- garde uniquement les
        # candidats vraiment surs (peu de diversite).
        "K_sym": 0,
        "K_pb": 2,
        "K_hb": 3,
        "K_tot": None,
        "tau_gb": 0,
        "radius_gb": 2,
    },
}


def get(config_name: str) -> dict:
    return CONFIGS[config_name]


def all_names() -> list:
    return list(CONFIGS.keys())
