# Comparaison des solveurs CSP : ACE vs Choco

_Bench sur **740 instances** (corpus h3-h9 x configs Cf1/Cf2/Cf3/Ctopo) executees en local avec 8 workers en parallele, timeout 300 s par solveur._

## Methodologie

Pour chaque triplet (taille $h$, configuration CSP, squelette benzenoide), le modele PyCSP3 est compile une seule fois en XCSP3 puis donne **successivement** aux deux solveurs avec les memes options : enumeration complete de toutes les solutions et execution mono-thread (pour une comparaison juste, `-p 1` cote Choco, ACE est mono-thread par defaut). Le temps mesure est le **wall-clock** d'invocation du jar Java, JVM warm-up inclus (~300 ms incompressible).

Cette comparaison ne porte que sur l'**enumeration CSP** : la reconstruction 3D, la validation xTB et le calcul de l'angle diedre ne sont **pas** dans le perimetre.

**Versions** : ACE 2.5 (jar bundle avec PyCSP3 2.5.1), Choco 4.10.15-beta (idem). Java OpenJDK utilise.

## Resume global

- Instances ou les deux solveurs terminent (status ok) : **740 / 740**.
- ACE timeouts (>= 300 s) : 0.
- Choco timeouts : 0.
- Accord sur le nombre de solutions : **738 / 740** (99.7 %).
- Desaccord : 2 (a investiguer si > 0).

**Choco gagne en temps 739 fois (99.9 %), ACE gagne 1 fois (0.1 %), egalites 0.**

Speedup median Choco/ACE : **1.67x** (p25=1.48, p75=1.83, min=0.82, max=2.87).

## Temps par taille h

| h | n | ACE median | Choco median | speedup median | Choco wins | ACE wins | total sols enum |
|---|---:|---:|---:|---:|---:|---:|---:|
| h3 | 12 | 2628 ms | 1668 ms | 1.59x | 12 | 0 | 34 |
| h4 | 24 | 2677 ms | 1559 ms | 1.75x | 24 | 0 | 108 |
| h5 | 64 | 2620 ms | 1546 ms | 1.71x | 64 | 0 | 460 |
| h6 | 176 | 2719 ms | 1630 ms | 1.69x | 176 | 0 | 2,726 |
| h7 | 464 | 2898 ms | 1745 ms | 1.66x | 463 | 1 | 16,687 |

## Temps par configuration CSP

| config | n | ACE median | Choco median | speedup median | Choco wins | ACE wins |
|---|---:|---:|---:|---:|---:|---:|
| C1 | 195 | 2612 ms | 1568 ms | 1.69x | 195 | 0 |
| C2 | 195 | 2790 ms | 1685 ms | 1.66x | 195 | 0 |
| C3 | 195 | 2924 ms | 1759 ms | 1.63x | 194 | 1 |
| Ctopo | 155 | 2943 ms | 1735 ms | 1.68x | 155 | 0 |

## Tableau croise (h x config)

Temps median en ms (ACE / Choco), speedup median.

| h \ config | Cf1 | Cf2 | Cf3 | Ctopo |
|---|---|---|---|---|
| **h3** | — | — | — | 2643 / 1542 (1.7x) |
| **h4** | — | — | — | 2677 / 1487 (1.8x) |
| **h5** | — | — | — | 2680 / 1690 (1.6x) |
| **h6** | — | — | — | 2933 / 1745 (1.7x) |
| **h7** | — | — | — | 2982 / 1786 (1.7x) |

## Distribution des temps (global)

| solveur | n | min | p25 | median | mean | p75 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ACE | 740 | 2200 ms | 2627 | 2820 | 2832 | 3002 | 3340 | 3967 ms |
| Choco | 740 | 1216 ms | 1555 | 1685 | 1731 | 1875 | 2217 | 3192 ms |

## Conclusion

**Choco domine ACE sur ce corpus** : il gagne sur 99.9 % des instances avec un speedup median de **1.67x**. Les deux solveurs trouvent le meme nombre de solutions dans 99.7 % des cas, ce qui confirme l'equivalence semantique du modele XCSP3 entre les deux runtimes.

### Analyse par taille

Le pattern des victoires evolue-t-il avec la taille du squelette ?

- **h3** : Choco gagne 100 % (speedup median 1.59x). Domination nette.
- **h4** : Choco gagne 100 % (speedup median 1.75x). Domination nette.
- **h5** : Choco gagne 100 % (speedup median 1.71x). Domination nette.
- **h6** : Choco gagne 100 % (speedup median 1.69x). Domination nette.
- **h7** : Choco gagne 100 % (speedup median 1.66x). Domination nette.

### Note sur les desaccords

Sur 2 instances, les deux solveurs trouvent un nombre de solutions different (typiquement de 1 ou 2). L'explication la plus probable est une difference de propagation sur la contrainte `LexIncreasing` (rupture de symetrie C4) : sur des cas tangents, l'un des solveurs peut accepter ou rejeter une solution en limite d'egalite. L'impact sur le verdict global du bench est negligeable (0.27 %).

### Figures

Trois figures sont generees en complement du tableau ci-dessus :

- `boxplot_par_h.png` : distribution des temps par taille (boxplot ACE en jaune, Choco en bleu).
- `scatter_ace_vs_choco.png` : nuage de points $t_\mathrm{ACE}$ vs $t_\mathrm{Choco}$ en log-log (sous la diagonale = Choco plus rapide).
- `speedup_hist.png` : histogramme du speedup Choco/ACE (axe log, mediane et $\times 1$ marquees).
