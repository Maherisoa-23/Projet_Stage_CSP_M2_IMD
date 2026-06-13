// Descriptions des configurations CSP affichees dans le viewer.
//
// Chaque entree expose :
//   - short    : sous-titre court (affiche sous le titre de la carte dashboard)
//   - summary  : phrase resumant l'objectif de la config
//   - constraints : liste de contraintes appliquees (puces)
//   - motivation  : pourquoi cette config existe / ce qu'elle teste
//   - kind     : "real" (issue du solveur CSP) | "virtual" (filtre a posteriori sur C1)

window.CONFIG_DESCRIPTIONS = {
  C1: {
    short: "Base — topologie minimale",
    kind: "real",
    summary:
      "Configuration de reference du run final. Aucune contrainte additionnelle " +
      "au-dela du squelette du benzenoide : le solveur explore librement toutes " +
      "les affectations de tailles (5, 6, 7) sur les cycles, sous la seule " +
      "contrainte de la table de voisinage.",
    constraints: [
      "Squelette : benzenoide d'entree (cycles 6 connexes)",
      "Affectations : chaque cycle prend une taille dans {5, 6, 7}",
      "Table de voisinage : interdit les voisinages localement infaisables",
      "Somme des deviations : Sigma x = 6h (conservation atomes)",
      "Symetrie C1/C3 : activee (canonisation des solutions equivalentes)",
    ],
    motivation:
      "C1 sert de baseline. Elle donne la plus grande population de solutions " +
      "valides et permet de mesurer le gain en %PLAN des contraintes plus " +
      "strictes (C2, C3) ou des filtres topologiques (Ctopo).",
  },
  C2: {
    short: "Pb1 + adj 5-7",
    kind: "real",
    summary:
      "Configuration intermediaire : on impose la presence d'au moins une " +
      "adjacence pentagone-heptagone (motif Stone-Wales local) et on limite " +
      "le nombre de pentagones a 1 (Pb1).",
    constraints: [
      "Toutes les contraintes de C1",
      "Pb1 : n_pent <= 1 (au plus un pentagone)",
      "adj_57 >= 1 : au moins une paire pentagone-heptagone adjacente",
    ],
    motivation:
      "Le motif 5-7 adjacent compense localement la courbure gaussienne " +
      "(pentagone +pi/3, heptagone -pi/3). En forcant cette alternance et en " +
      "limitant la concentration de defauts, on cible des structures plus " +
      "susceptibles d'etre planes. Resultat empirique : ~82% PLAN sur h8.",
  },
  C3: {
    short: "Pb1 + adj 5-7 + tau_gb = 0",
    kind: "real",
    summary:
      "Configuration la plus stricte : C2 augmentee de l'interdiction stricte " +
      "des adjacences heptagone-heptagone.",
    constraints: [
      "Toutes les contraintes de C2",
      "tau_gb = 0 (rayon 2) : aucune paire d'heptagones adjacents",
    ],
    motivation:
      "Deux heptagones cote a cote concentrent la courbure negative et " +
      "amplifient le hors-plan. Les interdire ferme cette source de " +
      "non-planarite. Resultat empirique : ~97% PLAN sur h8, mais le nombre " +
      "de solutions chute fortement (selectivite vs purete).",
  },
  Ctopo: {
    short: "Topologie complete (rayon-2 + squelette compact)",
    kind: "real",
    summary:
      "Configuration combinant deux descripteurs topologiques independants : " +
      "aucun motif rayon-2 deletere autour de chaque cycle (blacklist universelle), " +
      "ET squelette structurellement compact (>=4 atomes partages par 3 cycles, " +
      "pre-check sur le squelette avant assignment).",
    constraints: [
      "Toutes les contraintes de C1 (table de voisinage, conservation atomique)",
      "Contrainte rayon-2 : aucun cycle n'a un voisinage (taille + tailles voisins) " +
        "dans la blacklist universelle (ex. 7|[6,7,7], 7|[6,6,7,7], 5|[5])",
      "Pre-check squelette : >=4 atomes peri-condenses (partages par 3 cycles)",
    ],
    motivation:
      "L'analyse des sols non-plans h8/h9 montre deux mecanismes d'echec " +
      "complementaires : (1) frustration locale autour d'un cycle (capturee " +
      "par les motifs rayon-2 du graphe dual), et (2) flexibilite globale du " +
      "squelette (les squelettes etales se replient, les squelettes compacts " +
      "tiennent plats). En croisant les deux filtres, Ctopo bat C3 sur h9 : " +
      "71.4% PLAN sur 30 742 solutions planes (vs 60.1% sur 1 711 plans pour C3, " +
      "soit x18 candidats plans). Initialement materialisee a posteriori sur les " +
      "sols C1 (cf. csp_solver/analysis/materialize_ctopo.py), Ctopo a ete " +
      "re-implementee comme vraie contrainte CSP solveur en Phase E (juin 2026, " +
      "cf. csp_solver/utils/model.py).",
  },
};

// Helper : retourne la description ou null si la config est inconnue.
window.getConfigDescription = function (configName) {
  return window.CONFIG_DESCRIPTIONS[configName] || null;
};
