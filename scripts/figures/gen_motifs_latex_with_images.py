"""Genere doc/motifs_bord_h8.tex qui inclut les captures PNG produites par
tmp/capture_motif_views.py.

Layout :
  - Section "Methodologie"
  - 4 sections : Top w4 fav / Top w4 def / Top w5 fav / Top w5 def
  - Chaque section : grille 4 colonnes x 3 lignes (10 images donc 2.5 lignes)
  - Sous chaque image : motif, N, %PLAN, delta_pp, sol_id, angle, verdict
  - Lecture statistique a la fin
"""

import json
import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    samples = json.load(open("tmp/motif_samples.json"))["samples"]

    # Regrouper par (w, category)
    groups = {}
    for s in samples:
        key = (s["w"], s["category"])
        groups.setdefault(key, []).append(s)

    preamble = r"""\documentclass[a4paper,11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1.5cm]{geometry}
\usepackage{graphicx}
\usepackage{caption}
\usepackage{subcaption}
\usepackage{float}
\usepackage{xcolor}

\title{Motifs de bord -- non-benzenoides h8 \\
\large{Caracterisation topologique de la planarite par sequences de cycles le long du bord externe}}
\author{}
\date{}

\begin{document}
\maketitle

\section{Methodologie}

Pour chaque solution h8 \texttt{C1 done} (107~764 sols, baseline 60.08\% PLAN),
nous extrayons la sequence ordonnee des cycles le long du \emph{bord externe}
du graphe dual. Chaque arete de la frontiere appartient a un unique cycle ;
le parcours cyclique de ces aretes definit une suite de cycles.
Sur cette suite, nous extrayons toutes les fenetres glissantes de longueur
$w \in \{4, 5\}$ (canonisees par symetrie miroir).

Pour chaque motif canonique $m$, on calcule
\[
\Delta_{\mathrm{pp}}(m) = \mathrm{P}(\mathrm{PLAN} \mid m \in \text{sol}) - \mathrm{baseline}
\]
ou la baseline vaut $60.08\%$ (frequence globale de PLAN pour h8 C1).
Le score d'interet est $|\Delta_{\mathrm{pp}}| \cdot \sqrt{N}$, qui favorise
les motifs simultanement \emph{discriminants} et \emph{frequents}.

\paragraph{Convention graphique.} Les captures 3D suivantes utilisent
\textbf{3Dmol.js} avec une vue \emph{top-down} alignee sur l'axe principal
d'inertie (l'axe normal au plan principal de la molecule).
Pentagone = rouge clair, hexagone = gris clair, heptagone = bleu clair.
Les cycles de la \textbf{fenetre du motif} sont colories en teinte plus
saturee. Les liaisons sont en gris, les hydrogenes en blanc.

\paragraph{Selection des exemples.} Pour les motifs favorisants, l'exemple
illustre est un sol \texttt{PLAN}. Pour les motifs defavorisants, l'exemple
est un sol \texttt{NON\_PLAN}. La vue top-down rend visibles les hexagones
plats (pour les \texttt{PLAN}) et le repliement (pour les \texttt{NON\_PLAN}).

"""

    def section(title, intro, samples_list):
        body = [f"\\section{{{title}}}", intro]
        body.append("\\begin{figure}[H]")
        body.append("\\centering")
        for i, s in enumerate(samples_list):
            png_name = f"captures/motif_w{s['w']}_{s['category']}_{s['motif']}.png"
            caption = (
                f"\\texttt{{{s['motif']}}} \\\\"
                f"\\footnotesize $N{{=}}{s['n_total']}$, "
                f"\\%PLAN${{=}}{s['pct_plan']:.1f}$, "
                f"$\\Delta{{=}}{s['delta_pp']:+.1f}$ pp \\\\"
                f"sol\\_id=\\texttt{{{s['sol_id']}}}, "
                f"angle=${s['angle_deg']:.2f}^\\circ$"
            )
            body.append("\\begin{minipage}[t]{0.235\\textwidth}")
            body.append("\\centering")
            body.append(f"\\includegraphics[width=\\linewidth]{{{png_name}}}\\\\")
            body.append(caption)
            body.append("\\end{minipage}")
            if (i + 1) % 4 == 0 and (i + 1) < len(samples_list):
                body.append("\\\\[0.8em]")
            else:
                body.append("\\hfill")
        body.append("\\end{figure}")
        body.append("\\clearpage")
        return "\n".join(body)

    parts = [preamble]
    parts.append(section(
        "Top 10 motifs FAVORISANT la planarite (w = 4)",
        r"Motifs a 4 cycles consecutifs sur le bord, associes a un \emph{plus grand} taux de planarite. La fenetre du motif est mise en evidence par des couleurs saturees.",
        groups[(4, "fav")]
    ))
    parts.append(section(
        "Top 10 motifs DEFAVORISANT la planarite (w = 4)",
        r"Motifs a 4 cycles consecutifs sur le bord, associes a un \emph{plus faible} taux de planarite. Le repliement caracteristique est visible sur la vue top-down.",
        groups[(4, "def")]
    ))
    parts.append(section(
        "Top 10 motifs FAVORISANT la planarite (w = 5)",
        r"Fenetres etendues a 5 cycles consecutifs.",
        groups[(5, "fav")]
    ))
    parts.append(section(
        "Top 10 motifs DEFAVORISANT la planarite (w = 5)",
        r"Fenetres etendues a 5 cycles, les plus penalisantes. Les motifs purs \texttt{7-7-7-7-7} et \texttt{5-5-5-5-5} chutent respectivement a 14\% et 20.5\% PLAN.",
        groups[(5, "def")]
    ))

    parts.append(r"""
\section{Lecture}

\begin{itemize}
\item Un \textbf{motif favorisant} contient typiquement un defaut isole
(un seul pent ou hept) entoure d'hexagones, qui realise la compensation
locale de courbure (motif Stone-Wales generalise).

\item Un \textbf{motif defavorisant} concentre plusieurs cycles de meme
nature (\texttt{7-7-7-7}, \texttt{5-5-5-5}) ou un melange mal positionne
(\texttt{5-7-7-7}, \texttt{5-5-7-7}). Ces motifs accumulent la courbure
de meme signe (deux heptagones consecutifs : $-2\pi/3$) sans possibilite
de compensation locale.

\item Le contraste est tres net en $w=5$ : la pure chaine \texttt{7-7-7-7-7}
chute a 14\% PLAN (versus 60\% baseline), et \texttt{5-5-5-5-5} a 20\%.

\item Par analogie avec la nomenclature des bords benzenoidiens
(zigzag, cove, bay, deep bay, ultra-deep bay), nous proposons les noms
suivants pour les motifs non-benzenoidiens identifies :
\begin{itemize}
  \item \emph{Plateau} : tout-hexagone ou un seul defaut isole
        (\texttt{6-6-6-6}, \texttt{6-6-6-7}, \texttt{5-6-6-6}).
  \item \emph{Soft cove} : Stone-Wales relache en hex
        (\texttt{5-7-6-6}, \texttt{6-6-5-7}).
  \item \emph{Gorge negative} : amas d'heptagones consecutifs
        (\texttt{7-7-7-7}, \texttt{7-7-7-7-7}).
  \item \emph{Dome} : amas de pentagones consecutifs
        (\texttt{5-5-5-5}, \texttt{5-5-5-5-5}, analogue calotte fullerene).
  \item \emph{Frustration mixte} : melange pent/hept mal positionne
        (\texttt{5-7-7-7}, \texttt{5-5-5-7}).
  \item \emph{Vallee profonde} : compensations en amas
        (\texttt{5-5-7-7}, \texttt{5-7-7-5}, analogue \emph{deep bay} mais
        avec des cycles non-hexagonaux).
\end{itemize}
\end{itemize}

\end{document}
""")

    out = Path("doc/motifs_bord_h8.tex")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"Ecrit : {out}")


if __name__ == "__main__":
    main()
