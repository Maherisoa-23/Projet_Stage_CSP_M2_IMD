# Résultats agrégés — effet de la table de voisinage (C5)

Généré le 2026-06-28 13:56 UTC. Seuil de planéité : dièdre < 25°. Totaux agrégés sur h3 à h9. Les solutions `status='failed'` (reconstruction géométrique impossible) sont exclues de tous les comptes.

## Slide 1 — C structurel vs C structurel + C5

|  | C structurel | C structurel + C5 |
|---|---|---|
| Planes trouvées | 363913 | 327321 |
| Non-planes trouvées | 324707 | 187860 |
| Planes manquées | -- | 36592 |

## Slide 2 — C structurel + C6 vs C structurel + C6 + C5

|  | C structurel + C6 | C structurel + C6 + C5 |
|---|---|---|
| Planes trouvées | 42756 | 21022 |
| Non-planes trouvées | 48086 | 10087 |
| Planes manquées | -- | 21734 |

## Détail brut (agrégé)

- **C structurel** : plan=363913  non-plan=324707
- **C structurel + C6** : plan=42756  non-plan=48086
- **C structurel + C5** : plan=327321  non-plan=187860
- **C structurel + C6 + C5** : plan=21022  non-plan=10087

## Détail par taille h (pour slides annexe)

### Slide 1 détaillée — C structurel vs + C5

| h | plan (Cstr) | nonplan (Cstr) | plan (+C5) | nonplan (+C5) | manquées |
|---|---|---|---|---|---|
| h3 | 7 | 0 | 7 | 0 | 0 |
| h4 | 49 | 2 | 43 | 1 | 6 |
| h5 | 347 | 55 | 258 | 20 | 89 |
| h6 | 2900 | 656 | 1907 | 239 | 993 |
| h7 | 20668 | 8992 | 12157 | 2847 | 8511 |
| h8 | 166032 | 95228 | 85819 | 26981 | 80213 |
| h9 | 173910 | 219774 | 227130 | 157772 | -53220 |

### Slide 2 détaillée — C structurel + C6 vs + C6 + C5

| h | plan (+C6) | nonplan (+C6) | plan (+C6+C5) | nonplan (+C6+C5) | manquées |
|---|---|---|---|---|---|
| h3 | 2 | 0 | 2 | 0 | 0 |
| h4 | 13 | 0 | 10 | 0 | 3 |
| h5 | 85 | 14 | 47 | 6 | 38 |
| h6 | 546 | 176 | 256 | 32 | 290 |
| h7 | 3090 | 1889 | 1219 | 276 | 1871 |
| h8 | 20169 | 15345 | 6494 | 1794 | 13675 |
| h9 | 18851 | 30662 | 12994 | 7979 | 5857 |
