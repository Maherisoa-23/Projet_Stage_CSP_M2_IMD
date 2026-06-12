"""Definitions declaratives des configurations CSP et options de validation
exposees au frontend du designer.

Structure :

  CSP_PRESETS_CANONICAL :
      Les 4 configurations recommandees (C1, C2, C3, Ctopo) presentees
      comme radios dans l'onglet "Preset" du designer. Chaque preset est
      un dict avec :
        - label    : nom court affiche
        - help     : description courte
        - flags    : dict de flags CSP passes au solveur

  CSP_PRESETS_LEGACY :
      Anciens presets (pb1, pb1_adj57, sym1, ...) conserves pour
      retro-compat avec les jobs deja stockes en DB. Pas exposes en UI.

  CSP_ADVANCED_OPTIONS :
      Liste declarative des contraintes individuelles affichables dans
      l'onglet "Avance" (tableau de bord). Le frontend les groupe via le
      champ `group`.

  VALIDATION_OPTIONS :
      Options de validation xTB affichees dans le bloc dedie en bas de
      la sidebar (methode, n_runs, cluster, ...).

Le frontend lit ces 3 listes via /api/designer/configs et construit l'UI.
"""

# =====================================================================
#  Presets canoniques (4 radios dans l'onglet "Preset")
# =====================================================================
# Mapping vers les 4 configurations C1/C2/C3/Ctopo du memoire.
# Reference : doc/experimentation.md
CSP_PRESETS_CANONICAL = [
    {
        "key": "C1",
        "label": "C1 -- Baseline (topologie minimale)",
        "help": "Aucune contrainte additionnelle. Table de voisinage + "
                "conservation atomique uniquement. Reference pour comparaison.",
        "flags": {},
    },
    {
        "key": "C2",
        "label": "C2 -- Pb1 + adj 5-7",
        "help": "n_pent <= 1 et au moins une paire pent-hept adjacente "
                "(motif Stone-Wales). ~82% planarite sur h8.",
        "flags": {"K_pb": 1, "adj_57": True},
    },
    {
        "key": "C3",
        "label": "C3 -- Pb1 + adj 5-7 + pas de 7-7 adjacents",
        "help": "C2 + interdiction stricte de 2 heptagones adjacents "
                "(tau_gb=0). ~97% planarite sur h8.",
        "flags": {"K_pb": 1, "adj_57": True, "tau_gb": 0, "radius_gb": 2},
    },
    {
        "key": "Ctopo",
        "label": "Ctopo -- Topologie complete (rayon-2 + squelette compact)",
        "help": "Recommande pour h9. Combine motifs rayon-2 deleteres "
                "interdits + squelette peri-condense (n_peri >= 4). "
                "~71% planarite sur h9 avec x18 plans vs C3. "
                "Necessite un squelette compact (au moins 4 atomes peri).",
        "flags": {
            "K_pb": 1, "adj_57": True, "tau_gb": 0, "radius_gb": 2,
            "ctopo_filter": True,
            "ctopo_min_n_peri": 4,
        },
        # Phase E : implemente comme contrainte CSP solveur (rayon-2 blacklist)
        # + pre-check n_peri_atoms >= 4 sur le squelette.
    },
]


# =====================================================================
#  Presets legacy (compatibilite jobs anciens, pas exposes en UI)
# =====================================================================
CSP_PRESETS_LEGACY = {
    "custom": {
        "label": "Custom (configurer manuellement)",
        "flags": {},
    },
    "baseline": {
        "label": "Baseline (= C1)",
        "flags": {},
    },
    "pb1": {
        "label": "pb1 (au plus 1 pent en bord)",
        "flags": {"K_pb": 1},
    },
    "pb1_adj57": {
        "label": "pb1 + adj-57 (= C2)",
        "flags": {"K_pb": 1, "adj_57": True},
    },
    "sym1": {
        "label": "sym1 (equilibre 5/7)",
        "flags": {"K_sym": 1},
    },
    "sym1_pb2": {
        "label": "sym1 + pb2",
        "flags": {"K_sym": 1, "K_pb": 2},
    },
    "all_strict": {
        "label": "all_strict (sym=0, pb=2, hb=3)",
        "flags": {"K_sym": 0, "K_pb": 2, "K_hb": 3},
    },
}


# =====================================================================
#  Options avancees (onglet "Avance" / tableau de bord)
# =====================================================================
# Chaque option est groupee thematiquement via `group`. Les groupes
# affiches dans l'ordre suivant :
#   1. contraintes-bord (Pb*, count_hexagon)
#   2. contraintes-symetrie (K_sym, K_hb, K_tot)
#   3. contraintes-adjacence (adj_57, tau_gb, radius_gb)
#   4. preprocessing (no_freeze, no_table)
CSP_ADVANCED_OPTIONS = [
    # --- Contraintes de bord ---
    {
        "key": "K_pb", "type": "int_or_none", "default": None,
        "min": 0, "max": 6,
        "label": "K_pb (cap pentagones en bord)",
        "help": "Nombre max de pentagones au bord du squelette. "
                "Pb1 = 1 (recommande). Laisser vide pour ne pas contraindre.",
        "group": "bord",
    },
    {
        "key": "K_hb", "type": "int_or_none", "default": None,
        "min": 0, "max": 6,
        "label": "K_hb (cap heptagones en bord)",
        "help": "Nombre max d'heptagones au bord. Laisser vide pour pas de contrainte.",
        "group": "bord",
    },
    {
        "key": "count_hexagon", "type": "bool", "default": False,
        "label": "Inclure le benzenoide original (tout-hexagones)",
        "help": "Garde la solution tout-hex dans les resultats. "
                "Par defaut elle est exclue (objectif = substitutions non-benzenoides).",
        "group": "bord",
    },

    # --- Contraintes de symetrie / balance ---
    {
        "key": "K_sym", "type": "int_or_none", "default": None,
        "min": 0, "max": 6,
        "label": "K_sym (|n_pent - n_hept| <=)",
        "help": "Difference max entre nombre de pentagones et d'heptagones. "
                "K_sym=0 = equilibre exact. Laisser vide pour pas de contrainte.",
        "group": "symetrie",
    },
    {
        "key": "K_tot", "type": "int_or_none", "default": None,
        "min": 0, "max": 12,
        "label": "K_tot (cap n_pent + n_hept)",
        "help": "Borne superieure du nombre total de defauts (pent + hept). "
                "Laisser vide pour pas de contrainte.",
        "group": "symetrie",
    },

    # --- Contraintes d'adjacence ---
    {
        "key": "adj_57", "type": "bool", "default": False,
        "label": "Forcer >= 1 adjacence pent-hept",
        "help": "Chaque pentagone doit avoir au moins un voisin heptagone "
                "(et inversement). Favorise les motifs azuleniques.",
        "group": "adjacence",
    },
    {
        "key": "tau_gb", "type": "int_or_none", "default": None,
        "min": 0, "max": 10,
        "label": "tau_gb (max paires meme-signe adjacentes)",
        "help": "Nombre max de paires d'heptagones adjacents dans un rayon donne. "
                "tau_gb=0 = aucune paire 7-7 adjacente (C3). "
                "Laisser vide pour pas de contrainte.",
        "group": "adjacence",
    },
    {
        "key": "radius_gb", "type": "int", "default": 2,
        "min": 1, "max": 4,
        "label": "radius_gb (rayon pour tau_gb)",
        "help": "Rayon d'evaluation de la contrainte tau_gb dans le graphe dual. "
                "Defaut 2.",
        "group": "adjacence",
    },

    # --- Preprocessing ---
    {
        "key": "no_freeze", "type": "bool", "default": False,
        "label": "Desactiver le gel b(v) >= 2",
        "help": "Sans cette option, les hexagones a 2+ blocs d'aretes libres "
                "separes sont geles. Active = considere libres (--no-freeze).",
        "group": "preprocessing",
    },
    {
        "key": "no_table", "type": "bool", "default": False,
        "label": "Desactiver la table de voisinage",
        "help": "Sans la table, le CSP explore plus de solutions mais beaucoup "
                "seront geom-infaisables.",
        "group": "preprocessing",
    },
]

ADVANCED_GROUPS = [
    ("bord",          "Contraintes de bord"),
    ("symetrie",      "Symetrie et balance"),
    ("adjacence",     "Adjacences entre cycles"),
    ("preprocessing", "Preprocessing"),
]


# =====================================================================
#  Options de validation xTB (bloc separe en bas de la sidebar)
# =====================================================================
VALIDATION_OPTIONS = [
    {
        "key": "method", "type": "select", "default": "det-opt",
        "options": [
            {"value": "det-opt",    "label": "det-opt (recommande, reproductible)"},
            {"value": "md",         "label": "MD + opt (non-deterministe, legacy)"},
            {"value": "multi-runs", "label": "Multi-runs (N optimisations independantes)"},
            {"value": "skip",       "label": "Skip xTB (geometrie plate z=0, pas d'opt)"},
        ],
        "label": "Methode de validation",
        "help": "det-opt : perturbation analytique deterministe + xtb --opt "
                "(byte-reproductible, recommande). "
                "MD : ancienne methode, non-deterministe. "
                "Multi-runs : N optimisations independantes. "
                "Skip : reconstruit la geometrie plate (z=0) sans optimiser, "
                "tres rapide pour visualiser la sol CSP sans xTB.",
    },
    {
        "key": "n_runs", "type": "int", "default": 1, "min": 1, "max": 10,
        "label": "n_runs (multi-runs uniquement)",
        "help": "Nombre d'optimisations xTB par solution. Utilise uniquement "
                "avec methode = multi-runs. Ignore sinon.",
    },
    {
        "key": "test_original", "type": "bool", "default": True,
        "label": "Tester le benzenoide d'origine (xTB sur tout-hexagones)",
        "help": "Avant les sols substituees, lance xTB sur le benzenoide pur "
                "(tous cycles = hex) pour servir de reference de planarite. "
                "Cout : ~5-15s. Decoche pour gagner du temps quand seule la "
                "topologie t'interesse.",
    },
    {
        "key": "cluster", "type": "bool", "default": False,
        "label": "Executer xTB sur cluster (distant)",
        "help": "Si active, le calcul xTB tourne sur le cluster (SSH). "
                "Beaucoup plus rapide pour h >= 5. "
                "Necessite SSH sans password et DESIGNER_CLUSTER_ENABLED=1 cote serveur.",
        "cluster_feature": True,  # masque si cluster_enabled=False
    },
]


# =====================================================================
#  Helpers
# =====================================================================

def resolve_preset_flags(preset_key: str) -> dict:
    """Retourne les flags d'un preset (canonical ou legacy).

    Cherche d'abord dans CSP_PRESETS_CANONICAL, puis dans CSP_PRESETS_LEGACY.
    Retourne {} si preset_key est "custom" ou inconnu.
    """
    for p in CSP_PRESETS_CANONICAL:
        if p["key"] == preset_key:
            return dict(p["flags"])
    if preset_key in CSP_PRESETS_LEGACY:
        return dict(CSP_PRESETS_LEGACY[preset_key]["flags"])
    return {}
