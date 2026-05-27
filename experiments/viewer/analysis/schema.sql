-- Schema additif : table topology_metrics + indexes.
-- A appliquer sur db_v2.db via : sqlite3 db_v2.db < analysis/schema.sql
-- Ne touche PAS aux tables existantes (configs, molecules, solutions,
-- xyz_files, designer_jobs).
--
-- Toutes les operations sont idempotentes (CREATE IF NOT EXISTS) : peut
-- etre re-applique sans risque.

CREATE TABLE IF NOT EXISTS topology_metrics (
    -- Cle composite alignee avec solutions(h, config, mol, sol_idx) pour
    -- permettre les joins natifs. Pas de FK explicite (SQLite ne les
    -- impose pas par defaut, et la table solutions a un id auto-increment
    -- en plus de cette cle composite).
    h TEXT NOT NULL,
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    sol_idx INTEGER NOT NULL,

    -- Comptages topologiques principaux
    n_kekule INTEGER,            -- # de matchings max enumereees (Kekule ou radicalaire)
    is_exact INTEGER,            -- 0/1 : True si l'enumeration n'a pas plafonne
    n_radicals INTEGER,          -- nb de radicaux du matching max (0 = Kekule stricte)
    clar_number INTEGER,         -- nombre de Clar (= max nb de sextets)
    n_clar_covers INTEGER,       -- nb de couvertures de Clar atteignant ce max

    -- RBO/CBO agreges par taille de cycle. NULL si molecule radicalaire
    -- (RBO non defini au sens strict Pauling/Randic).
    cbo_available INTEGER,       -- 0/1 (0 = radicalaire, valeurs NULL)
    cbo_mean_hex REAL,           -- moyenne CBO sur les hexagones
    cbo_max_hex REAL,            -- max CBO observe (= cbo_max d'au moins un hex)
    cbo_mean_pent REAL,          -- moyenne CBO sur les pentagones (notre extension)
    cbo_max_pent REAL,
    cbo_mean_hept REAL,
    cbo_max_hept REAL,

    -- Contexte (cycles dans la molecule)
    n_hex INTEGER,
    n_pent INTEGER,
    n_hept INTEGER,

    -- Versioning : permet d'invalider/recalculer selectivement.
    -- Format YYYY-MM-DD HH:MM:SS (UTC).
    computed_at TEXT NOT NULL,
    -- Version de l'algo de compute. A bumper si on change la semantique
    -- d'un calcul (ex. nouvelle convention pour cas radicalaire). Le
    -- script compute.py compare cette colonne a sa version pour decider
    -- s'il faut recalculer.
    compute_version TEXT NOT NULL,

    PRIMARY KEY (h, config, mol, sol_idx)
);

-- Indexes pour les requetes d'analyse (filtre par h + tri).
CREATE INDEX IF NOT EXISTS idx_topo_h_clar       ON topology_metrics(h, clar_number);
CREATE INDEX IF NOT EXISTS idx_topo_h_radicals   ON topology_metrics(h, n_radicals);
CREATE INDEX IF NOT EXISTS idx_topo_h_cbo_hex    ON topology_metrics(h, cbo_mean_hex);
CREATE INDEX IF NOT EXISTS idx_topo_h_kekule     ON topology_metrics(h, n_kekule);
