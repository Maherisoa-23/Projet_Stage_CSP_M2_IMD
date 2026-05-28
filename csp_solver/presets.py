"""Catalogue centralise des presets du solveur CSP.

Un preset = un ensemble de parametres (K_sym, K_pb, K_hb, K_tot, tau_gb,
adj_57) qui definit une configuration de contraintes. Utilise par
csp_solver.main via le flag --preset NAME.

Historique :
  * v1 (~ baseline) : aucun K_* (regime hexagones standard)
  * v2 a teste : sym1, pb1, pb2, pb0 (UNSAT), sym1_pb2, all_strict
    -> winner : pb1 (+9 a +19 pts vs baseline)
  * v3 a teste : curv1 (Gauss-Bonnet), pb1_curv1, sym1_pb2_curv1,
                  pb1_adj57 (combinaison gagnante : +17 a +32 pts vs baseline)
    -> winner : pb1_adj57

Les flags individuels (--sym K --pb K ...) restent disponibles et
priment sur le preset si specifies explicitement.
"""

PRESETS = {
    # === v1 / baseline ===
    "baseline": {
        # Aucune contrainte additionnelle. Reference.
    },

    # === Issus de v2 (contraintes pb/sym/hb/tot) ===
    "sym1": {
        "K_sym": 1,
    },
    "pb2": {
        "K_pb": 2,
    },
    "pb1": {
        # Winner de v2 : +9 a +19 pts plan vs baseline.
        "K_pb": 1,
    },
    "pb0": {
        # UNSAT sur h6-h9 dans nos tests.
        "K_pb": 0,
    },
    "sym1_pb2": {
        "K_sym": 1,
        "K_pb": 2,
    },
    "all_strict": {
        "K_sym": 0,
        "K_pb": 2,
        "K_hb": 3,
    },

    # === Issus de v3 (Gauss-Bonnet + combinaisons) ===
    "curv1": {
        # Gauss-Bonnet local seul : redondant avec pb1.
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "curv0": {
        "tau_gb": 0,
        "radius_gb": 2,
    },
    "sym1_pb2_curv1": {
        "K_sym": 1,
        "K_pb": 2,
        "tau_gb": 1,
        "radius_gb": 2,
    },
    "pb1_curv1": {
        # Equivalent a pb1 (curv1 est redondant avec pb1 dans nos tests).
        "K_pb": 1,
        "tau_gb": 1,
        "radius_gb": 2,
    },

    # === Winner global v3 ===
    "pb1_adj57": {
        # Combinaison gagnante : +17 a +32 pts plan vs baseline.
        # Stone-Wales : pent et hept apparies localement.
        "K_pb": 1,
        "adj_57": True,
    },
    "sym1_pb1_adj57": {
        # Variante plus stricte (rarement utile en pratique).
        "K_sym": 1,
        "K_pb": 1,
        "adj_57": True,
    },
}


def all_names() -> list[str]:
    """Retourne la liste de tous les presets disponibles."""
    return list(PRESETS.keys())


def get_preset(name: str) -> dict:
    """Retourne le dict de parametres d'un preset. Leve KeyError si absent.

    Le dict retourne ne contient QUE les cles non-defaut (pas de cles
    'None' parasites). Les cles possibles sont :
        K_sym, K_pb, K_hb, K_tot, tau_gb, radius_gb, adj_57
    """
    if name not in PRESETS:
        raise KeyError(
            f"Preset inconnu : '{name}'. "
            f"Disponibles : {', '.join(sorted(PRESETS.keys()))}"
        )
    return dict(PRESETS[name])


def describe() -> str:
    """Resume textuel des presets, pour --help / docs."""
    lines = ["Presets disponibles :"]
    for name in PRESETS:
        params = PRESETS[name]
        if not params:
            desc = "(aucune contrainte additionnelle)"
        else:
            desc = " ".join(f"{k}={v}" for k, v in params.items())
        lines.append(f"  {name:<20s} {desc}")
    return "\n".join(lines)
