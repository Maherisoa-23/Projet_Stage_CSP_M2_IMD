import sqlite3, numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path

BLUE   = "#2563EB"
ORANGE = "#EA580C"
DARK   = "#1E293B"
GRAY   = "#94A3B8"
CONFIGS = ["C1", "C2", "C3", "Ctopo"]   # noms tels que stockés dans la base
LABELS  = ["Cf1", "Cf2", "Cf3", "Ctopo"]  # noms affichés sur le graphique
OUT     = Path(".")   # dossier de sortie

import seaborn as sns
sns.set_theme(style="whitegrid", font="DejaVu Sans")
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#CBD5E1", "axes.labelcolor": DARK,
    "xtick.color": DARK, "ytick.color": DARK, "text.color": DARK,
    "grid.color": "#E2E8F0", "grid.linewidth": 0.8,
    "font.size": 11, "axes.titlesize": 13,
    "axes.titleweight": "bold", "axes.titlepad": 12,
})

conn = sqlite3.connect(r"C:\Projets\Projet_Stage_CSP_M2_IMD\experiments\script choco vs ace\solver_bench_final.db")
df = pd.read_sql_query(
    "SELECT config, t_ace_ms, t_choco_ms FROM solver_bench WHERE status='done'", conn)
conn.close()

cfg_stats = df.groupby("config").agg(
    ace_mean=("t_ace_ms","mean"), ace_std=("t_ace_ms","std"),
    choco_mean=("t_choco_ms","mean"), choco_std=("t_choco_ms","std")
).reindex(CONFIGS).reset_index()

x     = np.arange(len(CONFIGS))
width = 0.35
fig, ax = plt.subplots(figsize=(10, 6))

bars1 = ax.bar(x - width/2, cfg_stats["ace_mean"],   width,
               yerr=cfg_stats["ace_std"],   capsize=5,
               color=BLUE,   alpha=0.85, label="ACE",
               ecolor="#1E40AF", linewidth=0)
bars2 = ax.bar(x + width/2, cfg_stats["choco_mean"], width,
               yerr=cfg_stats["choco_std"], capsize=5,
               color=ORANGE, alpha=0.85, label="Choco",
               ecolor="#9A3412", linewidth=0)

for bar, mean, std in zip(bars1, cfg_stats["ace_mean"], cfg_stats["ace_std"]):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + std + 15,
            f"{mean:.0f}ms\n±{std:.0f}", ha="center", va="bottom",
            fontsize=8.5, color=BLUE, fontweight="bold")
for bar, mean, std in zip(bars2, cfg_stats["choco_mean"], cfg_stats["choco_std"]):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + std + 15,
            f"{mean:.0f}ms\n±{std:.0f}", ha="center", va="bottom",
            fontsize=8.5, color=ORANGE, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=12)
ax.set_xlabel("Configuration", fontsize=12)
ax.set_ylabel("Temps d'exécution moyen (ms)", fontsize=12)
ax.legend(framealpha=0.9)
ax.set_ylim(0, ax.get_ylim()[1] * 1.25)

for i, (_, row) in enumerate(cfg_stats.iterrows()):
    ratio = row["ace_mean"] / row["choco_mean"]
    ax.text(i, 50, f"×{ratio:.2f}", ha="center", fontsize=9,
            color=DARK, style="italic")
ax.text(0.01, 0.05, "× = ratio ACE/Choco", transform=ax.transAxes,
        fontsize=8, color=GRAY, style="italic")

plt.tight_layout()
plt.savefig(OUT/"fig4_barplot_config.png", dpi=150, bbox_inches="tight")
plt.close()