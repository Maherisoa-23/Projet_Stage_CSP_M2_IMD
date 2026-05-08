-- Schema SQLite pour le viewer h9.
-- Conçu pour ~2419 mol × 8 configs ≈ 19k entrées molecules,
-- et ~1.5M entrées solutions au total.
-- Indexes optimisés pour les requêtes du viewer :
--   * liste des mols d'une config (avec compteurs)
--   * liste paginée des solutions d'une mol pour une config
--   * filtre par planéité (plans only / non plans only)
--   * tri par angle.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS configs (
    name TEXT PRIMARY KEY,
    n_molecules INTEGER NOT NULL DEFAULT 0,
    n_solutions INTEGER NOT NULL DEFAULT 0,           -- somme n_md_completed
    n_geom_infeasible INTEGER NOT NULL DEFAULT 0,     -- somme n_geom_infeasible
    n_plans INTEGER NOT NULL DEFAULT 0,
    n_non_plans INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS molecules (
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    n_solutions_csp INTEGER,         -- job_status.n_solutions (CSP)
    n_md_completed INTEGER,          -- sol_dirs avec md_final_opt.xyz
    n_geom_infeasible INTEGER NOT NULL DEFAULT 0,
                                     -- sol_dirs vides (pas de source.xyz) :
                                     -- la reconstruction 3D a leve ValueError
                                     -- (CSP-valide mais geometriquement
                                     -- infaisable, ex. pentagone demande sur
                                     -- un hexagone trop contraint).
    n_xtb_failed INTEGER NOT NULL DEFAULT 0,
                                     -- sol_dirs avec source.xyz mais sans
                                     -- md_final_opt.xyz : reconstruction OK,
                                     -- xtb a echoue ou time-out.
    n_plans INTEGER NOT NULL DEFAULT 0,
    n_non_plans INTEGER NOT NULL DEFAULT 0,
    min_angle REAL,
    max_angle REAL,
    original_planar INTEGER,        -- 0/1
    original_angle_deg REAL,
    job_status TEXT,
    job_duration_sec REAL,
    PRIMARY KEY (config, mol)
);
CREATE INDEX IF NOT EXISTS idx_mol_name ON molecules(mol);
CREATE INDEX IF NOT EXISTS idx_mol_plans ON molecules(config, n_plans DESC);

CREATE TABLE IF NOT EXISTS solutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    sol_idx INTEGER NOT NULL,
    sizes TEXT NOT NULL,
    planar INTEGER NOT NULL,        -- 0/1
    angle_deg REAL,
    rmsd REAL,
    height REAL,
    n_attempts INTEGER,
    deterministic INTEGER,
    sol_dir TEXT NOT NULL           -- chemin relatif depuis project root
);
CREATE INDEX IF NOT EXISTS idx_sol_mol ON solutions(config, mol);
CREATE INDEX IF NOT EXISTS idx_sol_planar ON solutions(config, mol, planar);
CREATE INDEX IF NOT EXISTS idx_sol_angle ON solutions(config, mol, angle_deg);
