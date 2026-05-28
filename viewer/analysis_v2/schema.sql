-- Table additive : solution_descriptors (~50 colonnes).
-- A appliquer sur db_v2.db. Ne touche PAS aux tables existantes.
-- Idempotent.

CREATE TABLE IF NOT EXISTS solution_descriptors (
    -- Cle (FK conceptuelle vers solutions)
    h TEXT NOT NULL,
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    sol_idx INTEGER NOT NULL,

    -- ========== Famille A : cycles et leurs relations ==========
    n_pent INTEGER, n_hex INTEGER, n_hept INTEGER,
    n_cycles_total INTEGER,
    n_55 INTEGER,                       -- nb paires pent-pent fusionnees (arete partagee)
    n_57 INTEGER,                       -- nb paires pent-hept fusionnees (azulene si arete)
    n_56 INTEGER, n_66 INTEGER, n_67 INTEGER, n_77 INTEGER,
    n_azulene_units INTEGER,            -- paires 5+7 partageant une arete
    n_stone_wales INTEGER,              -- cluster 5-7-7-5 fusionnes
    n_3_fused_atoms INTEGER,            -- atomes partages par >=3 cycles (sites de stress)
    dual_diameter INTEGER,              -- diametre du graphe des cycles
    dual_radius INTEGER,
    dual_max_degree INTEGER,            -- nb max de cycles adjacents a un cycle
    dual_n_components INTEGER,          -- nb de composantes connexes du graphe des cycles

    -- ========== Famille B : bordure ==========
    n_boundary_atoms INTEGER,           -- atomes au bord (deg 2)
    n_interior_atoms INTEGER,           -- atomes a l'interieur (deg 3)
    boundary_length INTEGER,            -- nb d'aretes au bord
    n_solo INTEGER, n_duo INTEGER, n_trio INTEGER, n_quatuor INTEGER,  -- groupes Varet
    n_groups_5plus INTEGER,             -- groupes de taille >=5 (rare benzenoides, possible 5/7)
    irregularity_param REAL,            -- (N3+N4)/(N1+N2+N3+N4), Bouwman et al.
    n_pent_at_boundary INTEGER,         -- pentagones touchant le bord
    n_hept_at_boundary INTEGER,         -- heptagones touchant le bord
    n_hex_at_boundary INTEGER,
    pent_boundary_ratio REAL,           -- n_pent_at_boundary / n_pent (NULL si n_pent=0)
    hept_boundary_ratio REAL,

    -- ========== Famille C : geometrie 3D ==========
    max_angle_deg REAL,                 -- redondant avec solutions.angle_deg, mais auto-contenu
    buckling_height REAL,               -- deviation max au plan moyen (A)
    radius_of_gyration REAL,            -- compacite (A)
    aspect_ratio REAL,                  -- elongation (max axis / min axis dans plan ACP)
    convex_hull_area REAL,              -- etendue 2D apres projection plan moyen (A^2)
    curvature_discrete_mean REAL,       -- courbure discrete moyenne (angle entre normales de cycles voisins, deg)
    curvature_discrete_max REAL,        -- courbure discrete max (deg)
    n_atoms_above_plane INTEGER,        -- nb atomes z > 0 apres centrage
    n_atoms_below_plane INTEGER,
    plane_asymmetry REAL,               -- |n_above - n_below| / n_atoms

    -- ========== Famille D : electronique (existant + nouveau) ==========
    -- Existant (recopie de topology_metrics pour auto-contenance)
    n_kekule INTEGER, is_exact INTEGER, n_radicals INTEGER,
    clar_number INTEGER, n_clar_covers INTEGER,
    cbo_available INTEGER,
    cbo_mean_hex REAL, cbo_max_hex REAL,
    cbo_mean_pent REAL, cbo_max_pent REAL,
    cbo_mean_hept REAL, cbo_max_hept REAL,
    -- Nouveau : localization des radicaux
    radical_on_pent_freq REAL,          -- fraction des configurations radicalaires ou un atome de pent porte un radical
    radical_on_hex_freq REAL,
    radical_on_hept_freq REAL,
    radical_at_boundary_freq REAL,      -- fraction ou les radicaux sont sur la bordure
    -- Nouveau : aromatic islands
    n_aromatic_islands INTEGER,         -- composantes connexes d'hex avec cbo > 2.5
    largest_aromatic_island INTEGER,    -- taille max d'une ile aromatique

    -- ========== Famille E : croisements ==========
    aromatic_planarity_score REAL,      -- (clar_number / max(n_hex,1)) * (1 - max_angle_deg/30)
    radical_planarity_score REAL,       -- n_radicals * (1 - max_angle_deg/30)

    -- ========== Metadonnees ==========
    computed_at TEXT NOT NULL,
    compute_version TEXT NOT NULL,

    PRIMARY KEY (h, config, mol, sol_idx)
);

-- Indexes pour les requetes d'analyse.
CREATE INDEX IF NOT EXISTS idx_desc_h               ON solution_descriptors(h);
CREATE INDEX IF NOT EXISTS idx_desc_h_clar         ON solution_descriptors(h, clar_number);
CREATE INDEX IF NOT EXISTS idx_desc_h_radicals     ON solution_descriptors(h, n_radicals);
CREATE INDEX IF NOT EXISTS idx_desc_h_planar       ON solution_descriptors(h, max_angle_deg);
CREATE INDEX IF NOT EXISTS idx_desc_h_pent_hept    ON solution_descriptors(h, n_pent, n_hept);
CREATE INDEX IF NOT EXISTS idx_desc_h_azulene      ON solution_descriptors(h, n_azulene_units);
CREATE INDEX IF NOT EXISTS idx_desc_h_irregularity ON solution_descriptors(h, irregularity_param);
