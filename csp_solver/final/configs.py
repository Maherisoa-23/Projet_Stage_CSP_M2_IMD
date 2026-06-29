"""Configurations du run final h3-h9 x 3 configs.

3 configurations contraintes :
  C1 (Base)           : aucune contrainte additionnelle, topologie minimale
  C2 (Pb1 + adj_57)   : preset 'pb1_adj57' du catalogue presets.py
  C3 (Pb1 + adj_57 + tau_gb=0) : C2 + interdiction adjacence 7-7

Toutes : symetrie C1/C3 ACTIVEE par defaut (pas de flag pour la desactiver),
gel d'hexagone DESACTIVE (--no-freeze), table de voisinage ACTIVE.

Seed xTB fixee a 42 pour reproductibilite (le code md.py est byte-deterministe
avec OMP=1).
"""

from pathlib import Path


CONFIGS = {
    "C1": {
        "label": "Base (topologie minimale)",
        "preset_name": None,
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": None,
        "radius_gb": 2,
        "adj_57": False,
        "no_table": False,
        "freeze_b2": False,
    },
    "C2": {
        "label": "Pb1 + adj_57",
        "preset_name": "pb1_adj57",
        "K_sym": None,
        "K_pb": 1,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": None,
        "radius_gb": 2,
        "adj_57": True,
        "no_table": False,
        "freeze_b2": False,
    },
    "C3": {
        "label": "Pb1 + adj_57 + tau_gb=0 (interdiction 7-7 adjacents)",
        "preset_name": "pb1_adj57",
        "K_sym": None,
        "K_pb": 1,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": 0,
        "radius_gb": 2,
        "adj_57": True,
        "no_table": False,
        "freeze_b2": False,
    },
    # ------------------------------------------------------------------
    # Configs "isolation de C5 (table de voisinage)" -- ajoutees pour les
    # 2 slides annexe « C structurel vs C structurel + C5 ».
    #
    # On ne lance QUE Cstr (no_table, no adj_57) : c'est le sur-ensemble.
    # Les 3 autres configs de la comparaison se DERIVENT sans nouveau run :
    #   - « C structurel + C5 »       = C1 (deja en base finale, meme table)
    #   - « C structurel + C6 »        = Cstr filtre par le predicat adj_57
    #   - « C structurel + C6 + C5 »   = C1 filtre par le predicat adj_57
    # (le verdict xTB est deterministe en (mol, sizes), donc filtrer ne
    #  change pas les verdicts -- cf. analysis/c5_isolation/).
    #
    # MEMES reglages structurels que C1 (freeze_b2=False, gel deg=6 via
    # preprocessing), SEULE la table est desactivee (no_table=True).
    "Cstr": {
        "label": "C structurel seul (sans table de voisinage)",
        "preset_name": None,
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": None,
        "radius_gb": 2,
        "adj_57": False,
        "no_table": True,
        "freeze_b2": False,
    },
    # Variante optionnelle (NON lancee par defaut : derivable de Cstr par
    # filtrage adj_57). Definie ici comme filet de securite si l'on veut la
    # comparer directement plutot que par derivation.
    "Cstr_C6": {
        "label": "C structurel + C6 (adj 5-7, sans table)",
        "preset_name": None,
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
        "tau_gb": None,
        "radius_gb": 2,
        "adj_57": True,
        "no_table": True,
        "freeze_b2": False,
    },
}


SEED_MD = 42  # Note : md.py est deterministe par perturbation z structuree
              # (pas de RNG), la seed est documentaire.


def get_config(name: str) -> dict:
    if name not in CONFIGS:
        raise KeyError(f"Config inconnue : {name}. Disponibles : {list(CONFIGS)}")
    return dict(CONFIGS[name])


def all_config_names() -> list:
    return list(CONFIGS.keys())


# === Mapping taille -> dossier de .graph ===

# h3, h4, h5 : ajoutes a la main par l'utilisateur dans data/ a la racine
# h6-h9 : sous-ensemble plan extraits de la base de Hosoya, dans
#         experiments/v1/plane/benzdb/
GRAPH_DIRS = {
    3: "data/h3",
    4: "data/h4",
    5: "data/h5",
    6: "experiments/v1/plane/benzdb/h6",
    7: "experiments/v1/plane/benzdb/h7",
    8: "experiments/v1/plane/benzdb/h8",
    9: "experiments/v1/plane/benzdb/h9",
}


def list_graphs(project_root: str, size_h: int) -> list:
    """Retourne liste de chemins absolus de .graph pour une taille.

    Trie alphabetiquement pour reproductibilite.
    """
    if size_h not in GRAPH_DIRS:
        raise ValueError(f"Taille inconnue : h{size_h}")
    root = Path(project_root) / GRAPH_DIRS[size_h]
    if not root.exists():
        return []
    return sorted(str(p) for p in root.glob("*.graph"))
