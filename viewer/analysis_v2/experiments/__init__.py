"""Experiences d'analyse croisee.

Chaque experience est une fonction `run(conn, h) -> dict` retournant
{title, summary, plots: [{title, svg}], tables: [{title, headers, rows}]}.

Le rapport HTML (report/build_report.py) consomme ce format uniforme.
"""
