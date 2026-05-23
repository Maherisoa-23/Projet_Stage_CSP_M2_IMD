"""Contraintes CSP additionnelles pour experiments_v2.

Chaque module expose une fonction `apply(x, graph, K, ...) -> None` qui
ajoute des contraintes au modele PyCSP3 en cours (la variable `x` est la
VarArray principale, x[v] in {5,6,7}).

Toutes les contraintes sont optionnelles ; sans appel, comportement
identique au CSP de base.
"""
