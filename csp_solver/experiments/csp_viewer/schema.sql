-- Schema SQLite pour le viewer CSP (h3..h9 dans une seule base).
-- Indexes optimises pour les requetes du viewer :
--   * liste des datasets disponibles
--   * liste des mols d'un (h, config) avec compteurs
--   * liste paginee des solutions d'une mol pour une (h, config)
--   * filtre par planeite (plans only / non plans only)
--   * tri par angle.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS configs (
    h TEXT NOT NULL,
    name TEXT NOT NULL,
    n_molecules INTEGER NOT NULL DEFAULT 0,
    n_solutions INTEGER NOT NULL DEFAULT 0,           -- somme n_md_completed
    n_geom_infeasible INTEGER NOT NULL DEFAULT 0,     -- somme n_geom_infeasible
    n_plans INTEGER NOT NULL DEFAULT 0,
    n_non_plans INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (h, name)
);

CREATE TABLE IF NOT EXISTS molecules (
    h TEXT NOT NULL,                 -- 'h3', 'h4', ..., 'h9'
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
    PRIMARY KEY (h, config, mol)
);
CREATE INDEX IF NOT EXISTS idx_mol_name ON molecules(mol);
CREATE INDEX IF NOT EXISTS idx_mol_h_config_plans ON molecules(h, config, n_plans DESC);

CREATE TABLE IF NOT EXISTS solutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    h TEXT NOT NULL,
    config TEXT NOT NULL,
    mol TEXT NOT NULL,
    sol_idx INTEGER NOT NULL,
    sizes TEXT NOT NULL,
    verdict TEXT NOT NULL,           -- 'plan' | 'non_plan' | 'geom_infeasible' | 'xtb_failed'
    planar INTEGER,                  -- 0 / 1 / NULL (si verdict != plan/non_plan)
    angle_deg REAL,                  -- NULL si geom_infeasible
    rmsd REAL,
    height REAL,
    n_attempts INTEGER,
    deterministic INTEGER,
    sol_dir TEXT NOT NULL            -- chemin relatif depuis project root
);
CREATE INDEX IF NOT EXISTS idx_sol_mol ON solutions(h, config, mol);
CREATE INDEX IF NOT EXISTS idx_sol_verdict ON solutions(h, config, mol, verdict);
CREATE INDEX IF NOT EXISTS idx_sol_angle ON solutions(h, config, mol, angle_deg);
