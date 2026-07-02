// ===== State =====
const state = {
  view: "dashboard",       // "dashboard" | "config" | "mol" | "job"
  h: null,                 // dataset courant ("h3", "h4", ..., "h9")
  datasets: [],            // liste {h, n_solutions, ...} pour le selecteur
  config: null,
  mol: null,
  molPage: 1,
  molSize: 50,
  molSearch: "",
  molSort: "name",
  solPage: 1,
  solSize: 50,
  solFilter: "plans",
  solSort: "angle",
  solSearch: "",
  // Vue job designer (route /?job=<id>)
  jobId: null,             // UUID du job ouvert
  jobData: null,           // { state, summary, config, ... } depuis /api/designer/jobs/<id>
  jobSolutions: [],        // [{name, sol_idx, sizes, verdict, best_xyz_path, ...}]
  jobSolFilter: "all",
  jobSolSearch: "",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ===== Loader =====
let loadCount = 0;
function showLoader(msg = "Chargement…") {
  loadCount++;
  $("#loader-text").textContent = msg;
  $("#loader").classList.remove("hidden");
}
function hideLoader() {
  loadCount = Math.max(0, loadCount - 1);
  if (loadCount === 0) $("#loader").classList.add("hidden");
}
function showFullscreen(label = "Chargement…") {
  let el = document.getElementById("fs-loader");
  if (!el) {
    el = document.createElement("div");
    el.id = "fs-loader";
    el.className = "fullscreen-loader";
    el.innerHTML = `<div class="spinner"></div><div class="label"></div>`;
    document.body.appendChild(el);
  }
  el.querySelector(".label").textContent = label;
  el.classList.remove("hidden");
  return el;
}
function hideFullscreen() {
  const el = document.getElementById("fs-loader");
  if (el) el.classList.add("hidden");
}

async function fetchJSON(url, label, opts = {}) {
  showLoader(label);
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    // silent=true : appel best-effort (ex. peupler le selecteur de dataset
    // en arriere-plan) -- ne pas interrompre l'utilisateur avec une alerte
    // bloquante si la ressource est simplement indisponible (mode
    // designer-only sans table 'configs', par exemple).
    if (!opts.silent) alert(`Erreur réseau : ${e.message}`);
    throw e;
  } finally {
    hideLoader();
  }
}

// ===== Routing / breadcrumb =====
function setView(name) {
  state.view = name;
  $$(".view").forEach((s) => s.classList.add("hidden"));
  $(`#view-${name}`).classList.remove("hidden");
  renderBreadcrumb();
  window.scrollTo(0, 0);
}

function renderBreadcrumb() {
  const bc = $("#breadcrumb");
  let html;
  // Si on est sur la vue job designer, breadcrumb specifique
  if (state.view === "job") {
    html = `<a href="#" data-go="dashboard">Dashboard</a>`
         + `<span class="sep">/</span>`
         + `<span>Job designer #${state.jobId}</span>`;
  } else {
    const hLabel = state.h ? `[${state.h}] ` : "";
    html = `${hLabel}<a href="#" data-go="dashboard">Dashboard</a>`;
    if (state.config) {
      html += `<span class="sep">/</span><a href="#" data-go="config">${state.config}</a>`;
    }
    if (state.mol) {
      html += `<span class="sep">/</span><a href="#" data-go="mol">${state.mol}</a>`;
    }
  }
  bc.innerHTML = html;
  bc.querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const go = a.dataset.go;
      if (go === "dashboard") loadDashboard();
      else if (go === "config") loadConfig(state.config);
      else if (go === "mol") loadMolecule(state.config, state.mol);
    });
  });
}

// ===== Dataset selector =====
async function loadDatasets(silent = false) {
  const data = await fetchJSON("/api/datasets", "Datasets…", { silent });
  state.datasets = data.datasets || [];
  const sel = $("#dataset-select");
  sel.innerHTML = "";
  for (const d of state.datasets) {
    const opt = document.createElement("option");
    opt.value = d.h;
    opt.textContent = `${d.h} (${(d.n_solutions || 0).toLocaleString()} sols)`;
    sel.appendChild(opt);
  }
  // Choisit le dernier (souvent le plus gros) par defaut
  if (state.datasets.length > 0 && !state.h) {
    state.h = state.datasets[state.datasets.length - 1].h;
    sel.value = state.h;
  } else if (state.h) {
    sel.value = state.h;
  }
  sel.addEventListener("change", (ev) => {
    state.h = ev.target.value;
    state.config = null;
    state.mol = null;
    loadDashboard();
  });
}

// ===== Dashboard =====
async function loadDashboard() {
  state.config = null;
  state.mol = null;
  setView("dashboard");
  if (!state.h) return;
  const data = await fetchJSON(`/api/summary?h=${encodeURIComponent(state.h)}`, "Stats…");
  $("#summary-text").textContent =
    `[${data.h}] ${data.n_unique_molecules} molécules uniques × ${data.configs.length} configurations`;
  const grid = $("#configs-grid");
  grid.innerHTML = "";
  for (const c of data.configs) {
    const pct = c.n_solutions > 0 ? (100 * c.n_plans / c.n_solutions) : 0;
    const infeasible = c.n_geom_infeasible || 0;
    const desc = (window.getConfigDescription && window.getConfigDescription(c.name)) || null;
    const subtitle = desc
      ? `<div class="config-card-subtitle${desc.kind === "virtual" ? " virtual" : ""}">${desc.kind === "virtual" ? "[virtuelle] " : ""}${desc.short}</div>`
      : "";
    const card = document.createElement("div");
    card.className = "config-card" + (desc && desc.kind === "virtual" ? " virtual" : "");
    const maxAngle = c.max_angle != null ? `${c.max_angle.toFixed(2)}°` : "—";
    const medAngle = c.median_angle != null ? `${c.median_angle.toFixed(2)}°` : "—";
    card.innerHTML = `
      <h3>${c.name}</h3>
      ${subtitle}
      <div class="row"><span class="label">Molécules</span><span>${c.n_molecules}</span></div>
      <div class="row"><span class="label">Solutions validées</span><span>${c.n_solutions.toLocaleString()}</span></div>
      <div class="row" title="Solutions planes (très plans + acceptables, dièdre < 25°)"><span class="label">Plans</span><span style="color:var(--success)">${c.n_plans.toLocaleString()} (${pct.toFixed(1)}%)</span></div>
      <div class="row" title="Solutions non planes (dièdre ≥ 25°)"><span class="label">Non plans</span><span style="color:var(--danger)">${c.n_non_plans.toLocaleString()}</span></div>
      <div class="row" title="Angle dièdre maximal le plus élevé observé sur toutes les solutions de la config"><span class="label">Angle max</span><span>${maxAngle}</span></div>
      <div class="row" title="Médiane de l'angle dièdre maximal sur les solutions validées"><span class="label">Angle médian</span><span>${medAngle}</span></div>
      ${infeasible > 0 ? `<div class="row"><span class="label">Géom. infaisables</span><span style="color:var(--muted)">${infeasible.toLocaleString()}</span></div>` : ""}
      <div class="pct-bar"><div style="width:${pct}%"></div></div>
    `;
    card.addEventListener("click", () => loadConfig(c.name));
    grid.appendChild(card);
  }
}

// Rendu du bloc descriptif d'une config dans la vue config (sous le titre).
// Si pas de description connue : on cache la zone.
function renderConfigDescription(configName) {
  const box = document.getElementById("config-description");
  if (!box) return;
  const desc = (window.getConfigDescription && window.getConfigDescription(configName)) || null;
  if (!desc) {
    box.innerHTML = "";
    box.classList.add("hidden");
    return;
  }
  const kindBadge = desc.kind === "virtual"
    ? `<span class="kind-badge virtual" title="Configuration obtenue par filtrage a posteriori des solutions C1">virtuelle</span>`
    : `<span class="kind-badge real" title="Configuration produite par un run du solveur CSP">reelle (solveur)</span>`;
  const constraints = (desc.constraints || []).map((c) => `<li>${c}</li>`).join("");
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="config-desc-header">
      <span class="config-desc-short">${desc.short}</span>
      ${kindBadge}
    </div>
    <p class="config-desc-summary">${desc.summary}</p>
    <div class="config-desc-grid">
      <div>
        <h4>Contraintes appliquees</h4>
        <ul class="config-desc-list">${constraints}</ul>
      </div>
      <div>
        <h4>Motivation</h4>
        <p class="config-desc-motivation">${desc.motivation}</p>
      </div>
    </div>
  `;
}

// ===== Config view (liste mols) =====
async function loadConfig(config) {
  state.config = config;
  state.mol = null;
  state.molPage = 1;
  state.molSearch = "";
  state.molSort = "name";
  $("#mol-search").value = "";
  $("#mol-sort").value = "name";
  setView("config");
  $("#config-title").textContent = `Configuration : ${config}`;
  renderConfigDescription(config);
  await fetchMolecules();
}

async function fetchMolecules() {
  const params = new URLSearchParams({
    h: state.h,
    config: state.config,
    search: state.molSearch,
    page: state.molPage,
    size: state.molSize,
    sort: state.molSort,
  });
  const data = await fetchJSON(`/api/molecules?${params}`, "Molécules…");
  renderMolTable(data);
  renderPagination($("#mol-pagination"), data.total, data.page, data.size, (p) => {
    state.molPage = p;
    fetchMolecules();
  });
}

function renderMolTable(data) {
  const wrap = $("#mol-table-wrap");
  if (data.molecules.length === 0) {
    wrap.innerHTML = `<div class="empty">Aucune molécule.</div>`;
    return;
  }
  let h = `<table><thead><tr>
    <th>Molécule</th>
    <th title="Solutions CSP combinatoires (avant validation 3D)">CSP</th>
    <th title="Solutions reconstruites + validées par xTB">xTB validées</th>
    <th title="Solutions CSP-valides mais reconstruction 3D impossible (pentagone/heptagone sur hexagone trop contraint)">Géom. ✗</th>
    <th title="Solutions planes (très plan + acceptable), dièdre &lt; 25°">Plans</th>
    <th title="Solutions très planes, dièdre &lt; 10°">dont TP</th>
    <th title="Solutions non planes, dièdre &ge; 25°">Non plans</th>
    <th title="Plus petit angle dièdre maximal observé sur les sols validées">Angle min</th>
    <th>Job</th>
  </tr></thead><tbody>`;
  for (const m of data.molecules) {
    const pct = m.n_md_completed > 0 ? (100 * m.n_plans / m.n_md_completed).toFixed(0) : "—";
    const infeasible = m.n_geom_infeasible || 0;
    const xtbFailed = m.n_xtb_failed || 0;
    const geomCell = infeasible > 0
      ? `<span class="muted" title="Reconstruction 3D impossible : structure CSP-valide mais inaccessible géométriquement">${infeasible}</span>`
      : `<span class="muted">0</span>`;
    h += `<tr data-mol="${m.mol}">
      <td><strong>${m.mol}</strong></td>
      <td>${m.n_solutions_csp ?? "—"}</td>
      <td>${m.n_md_completed ?? "—"}</td>
      <td>${geomCell}${xtbFailed > 0 ? ` <span class="muted" title="Reconstruction OK mais xTB a échoué">+${xtbFailed} xTB✗</span>` : ""}</td>
      <td style="color:var(--success)"><strong>${m.n_plans}</strong> ${pct !== "—" ? `(${pct}%)` : ""}</td>
      <td><span class="muted">${m.n_tres_plan ?? "—"}</span></td>
      <td style="color:var(--danger)">${m.n_non_plans}</td>
      <td>${m.min_angle === null ? "—" : m.min_angle.toFixed(2) + "°"}</td>
      <td><span class="muted">${m.job_status ?? "—"}${m.job_duration_sec ? ` · ${(m.job_duration_sec/60).toFixed(0)} min` : ""}</span></td>
    </tr>`;
  }
  h += `</tbody></table>`;
  wrap.innerHTML = h;
  wrap.querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => loadMolecule(state.config, tr.dataset.mol));
  });
}

// ===== Molecule view (sols) =====
async function loadMolecule(config, mol) {
  state.config = config;
  state.mol = mol;
  state.solPage = 1;
  state.solFilter = "plans";
  state.solSort = "angle";
  state.solSearch = "";
  $("#sol-filter").value = "plans";
  $("#sol-sort").value = "angle";
  $("#sol-search").value = "";
  setView("mol");
  $("#mol-title").textContent = `Molécule : ${mol}  (${config})`;
  await fetchSolutions();
}

async function fetchSolutions() {
  const params = new URLSearchParams({
    h: state.h,
    config: state.config,
    mol: state.mol,
    filter: state.solFilter,
    page: state.solPage,
    size: state.solSize,
    sort: state.solSort,
    search: state.solSearch,
  });
  const data = await fetchJSON(`/api/solutions?${params}`, "Solutions…");
  renderMolMeta(data.molecule);
  renderSolTable(data);
  renderPagination($("#sol-pagination"), data.total, data.page, data.size, (p) => {
    state.solPage = p;
    fetchSolutions();
  });
}

function renderMolMeta(meta) {
  const box = $("#mol-meta");
  if (!meta) { box.innerHTML = ""; return; }
  const infeasible = meta.n_geom_infeasible || 0;
  const xtbFailed = meta.n_xtb_failed || 0;
  box.innerHTML = `
    <div class="item"><span class="label">CSP combinatoire</span><span class="value">${meta.n_solutions_csp ?? "—"}</span></div>
    <div class="item"><span class="label">xTB validées</span><span class="value">${meta.n_md_completed ?? "—"}</span></div>
    ${infeasible > 0 ? `<div class="item" title="Solutions CSP-valides mais reconstruction 3D impossible"><span class="label">Géom. infaisables</span><span class="value" style="color:var(--muted)">${infeasible}</span></div>` : ""}
    ${xtbFailed > 0 ? `<div class="item" title="Reconstruction OK mais xTB a échoué"><span class="label">xTB échec</span><span class="value" style="color:var(--muted)">${xtbFailed}</span></div>` : ""}
    <div class="item" title="Très plan + acceptable (dièdre < 25°)"><span class="label">Plans</span><span class="value" style="color:var(--success)"><strong>${meta.n_plans ?? 0}</strong></span></div>
    <div class="item" title="Très plan (dièdre < 10°)"><span class="label">dont très plans</span><span class="value">${meta.n_tres_plan ?? 0}</span></div>
    <div class="item" title="Non plans (dièdre ≥ 25°)"><span class="label">Non plans</span><span class="value" style="color:var(--danger)">${meta.n_non_plans ?? 0}</span></div>
    <div class="item" title="Plus petit angle dièdre maximal observé"><span class="label">Angle min</span><span class="value">${meta.min_angle === null ? "—" : meta.min_angle.toFixed(2) + "°"}</span></div>
    <div class="item" title="Plus grand angle dièdre maximal observé"><span class="label">Angle max</span><span class="value">${meta.max_angle === null ? "—" : meta.max_angle.toFixed(2) + "°"}</span></div>
    <div class="item"><span class="label">Job</span><span class="value">${meta.job_status ?? "—"}${meta.job_duration_sec ? ` · ${(meta.job_duration_sec/60).toFixed(0)} min` : ""}</span></div>
  `;
}

function renderSolTable(data) {
  const wrap = $("#sol-table-wrap");
  if (data.solutions.length === 0) {
    wrap.innerHTML = `<div class="empty">Aucune solution dans ce filtre.</div>`;
    return;
  }
  let h = `<table><thead><tr>
    <th>Sol_idx</th>
    <th>Sizes</th>
    <th>Verdict</th>
    <th title="Écart-au-plan max sur dièdres connectés A-B-C-D (seuils : <10 très plan, 10-25 acceptable, ≥25 non plan)">Angle (°)</th>
    <th>RMSD</th>
    <th>Height</th>
    <th>Tentatives MD</th>
    <th>Vue 3D</th>
  </tr></thead><tbody>`;
  for (const s of data.solutions) {
    let badge, rowClass = "", angleCell, rmsdCell, heightCell, attemptsCell, filesCell;

    // Cellule angle coloriee selon les 3 seuils chimistes
    const angleFmt = (v) => {
      if (v == null) return "—";
      const cls = v < 10 ? "dih-good" : (v < 25 ? "dih-mid" : "dih-bad");
      return `<span class="${cls}">${v.toFixed(2)}°</span>`;
    };

    if (s.verdict === "geom_infeasible") {
      badge = `<span class="badge infeasible" title="Reconstruction 3D impossible (CSP-valide mais pentagone/heptagone sur hexagone trop contraint)">GÉOM ✗</span>`;
      rowClass = "row-infeasible";
      angleCell = `—`;
      rmsdCell = `—`;
      heightCell = `—`;
      attemptsCell = `—`;
      filesCell = `<span class="muted">—</span>`;
    } else if (s.verdict === "xtb_failed") {
      badge = `<span class="badge xtb-failed" title="Reconstruction OK mais xTB n'a pas convergé">xTB ✗</span>`;
      rowClass = "row-xtb-failed";
      angleCell = `—`;
      rmsdCell = `—`;
      heightCell = `—`;
      attemptsCell = s.n_attempts ?? "—";
      filesCell = `<span class="muted">—</span>`;
    } else {
      // tres_plan / acceptable / non_plan : 3 badges distincts
      if (s.verdict === "tres_plan") {
        badge = `<span class="badge plan" title="Très plan : dièdre maximal &lt; 10°">PLAN</span>`;
      } else if (s.verdict === "acceptable") {
        badge = `<span class="badge acceptable" title="Acceptable : dièdre maximal entre 10° et 25°">ACC</span>`;
      } else {
        // non_plan
        badge = `<span class="badge non-plan" title="Non plan : dièdre maximal ≥ 25°">NON</span>`;
      }
      angleCell = angleFmt(s.angle_deg);
      rmsdCell = s.rmsd?.toFixed(4) ?? "—";
      heightCell = s.height?.toFixed(4) ?? "—";
      attemptsCell = s.n_attempts ?? "—";
      filesCell = `<button class="btn-3d" data-sol-idx="${s.sol_idx}" data-sol-dir="${encodeURIComponent(s.sol_dir)}" data-sizes="${s.sizes}" data-verdict="${s.verdict}" title="Visualiser en 3D">3D</button>`;
    }

    h += `<tr${rowClass ? ` class="${rowClass}"` : ""}>
      <td><strong>${s.sol_idx}</strong></td>
      <td><code>${s.sizes}</code></td>
      <td>${badge}</td>
      <td>${angleCell}</td>
      <td>${rmsdCell}</td>
      <td>${heightCell}</td>
      <td>${attemptsCell}</td>
      <td>${filesCell}</td>
    </tr>`;
  }
  h += `</tbody></table>`;
  wrap.innerHTML = h;

  // Hook les boutons 3D : ouvre le modal MolViz
  wrap.querySelectorAll(".btn-3d").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openMolViz({
        sol_idx: btn.dataset.solIdx,
        sol_dir: decodeURIComponent(btn.dataset.solDir),
        sizes:   btn.dataset.sizes,
        verdict: btn.dataset.verdict,
      });
    });
  });
}

// Wrapper consistant pour ouvrir le viewer 3D. Centralise le guard
// "MolViz non charge" pour eviter le boilerplate dans chaque handler.
function openMolViz(info) {
  if (!window.MolViz || typeof window.MolViz.openSafe !== "function") {
    alert("MolViz n'est pas charge sur cette page.");
    return false;
  }
  return window.MolViz.openSafe(info);
}

// ===== Designer job view (route /?job=<id>) =====
//
// Vue dediee aux resultats d'un job lance depuis le designer. Pas de
// dataset/config/mol : on a juste l'id de job et on liste ses solutions.
async function loadJobView(jobId) {
  state.view = "job";
  state.jobId = jobId;
  state.jobData = null;
  state.jobSolutions = [];
  state.jobOriginal = null;
  state.jobCounts = null;
  jobSolSelection.clear();  // nouvelle vue job -> selection d'export reinitialisee
  setView("job");
  $("#job-title").textContent = `Job designer #${jobId}`;
  $("#job-meta").innerHTML = '<div class="item"><span class="muted">Chargement…</span></div>';
  $("#job-original-box").innerHTML = '<div class="item"><span class="muted">Chargement…</span></div>';
  $("#job-sol-table-wrap").innerHTML = "";

  try {
    const [job, sols] = await Promise.all([
      fetchJSON(`/api/designer/jobs/${jobId}`, "Job…"),
      fetchJSON(`/api/designer/jobs/${jobId}/solutions`, "Solutions…"),
    ]);
    state.jobData = job;
    state.jobSolutions = sols.solutions || [];
    state.jobOriginal = sols.original || null;
    state.jobCounts = sols.counts || null;
    // Titre : nom personnalise si defini (page "Mes tests"), sinon #job_id.
    $("#job-title").textContent = job.name
      ? `${job.name} (#${jobId})`
      : `Job designer #${jobId}`;
    renderJobMeta(job);
    renderJobOriginal(state.jobOriginal);
    renderJobSolTable();
  } catch (e) {
    $("#job-meta").innerHTML = `<div class="item"><span class="muted">Erreur : ${e.message}</span></div>`;
  }
}

function renderJobMeta(job) {
  const box = $("#job-meta");
  const cfg = job.config || {};
  const cfgPills = Object.entries(cfg).map(([k, v]) => {
    let s;
    if (v === true) s = k;
    else if (v === false) return null;
    else s = `${k}=${v}`;
    return `<span class="pill">${s}</span>`;
  }).filter(Boolean).join(" ");

  const stateClass = {
    "success": "success",
    "running": "running",
    "failed": "danger",
    "cancelled": "muted",
    "pending": "warning",
  }[job.state] || "muted";

  const dur = job.duration_s
    ? (job.duration_s >= 60
        ? `${(job.duration_s / 60).toFixed(1)} min`
        : `${job.duration_s.toFixed(1)} s`)
    : "—";

  const s = job.summary || {};
  const c = state.jobCounts || {};
  box.innerHTML = `
    <div class="item"><span class="label">Statut</span>
      <span class="value" style="color:var(--${stateClass})">${job.state}</span></div>
    <div class="item"><span class="label">Solutions</span>
      <span class="value">${s.n_sol_dirs || 0}</span></div>
    <div class="item"><span class="label">Plans</span>
      <span class="value" style="color:var(--success)">${c.plan || 0}</span></div>
    <div class="item"><span class="label">Non plans</span>
      <span class="value" style="color:var(--danger)">${c.non_plan || 0}</span></div>
    <div class="item"><span class="label">MD echec</span>
      <span class="value" style="color:var(--muted)">${c.md_failed || 0}</span></div>
    <div class="item"><span class="label">Duree</span>
      <span class="value">${dur}</span></div>
    <div class="item" style="grid-column: 1 / -1"><span class="label">Configuration</span>
      <span class="value">${cfgPills || '<span class="muted">defauts</span>'}</span></div>
  `;
}

// Bloc "Benzenoide d'entree" : planarite + bouton 3D du benzenoide original
// (tout-hexagones, opt xTB direct, lu depuis output_dir/original/planarity.json)
function renderJobOriginal(orig) {
  const box = $("#job-original-box");
  if (!orig) {
    box.innerHTML = '<div class="item"><span class="muted">Non disponible (job ancien ou test non execute)</span></div>';
    return;
  }
  if (!orig.success) {
    box.innerHTML = `
      <div class="item" style="grid-column: 1 / -1">
        <span class="label">Erreur</span>
        <span class="value muted" style="font-size:0.85rem;font-weight:normal">${orig.message || "echec"}</span>
      </div>`;
    return;
  }
  const badge = orig.planar
    ? `<span class="badge plan">PLAN</span>`
    : `<span class="badge non-plan">NON PLAN</span>`;
  const btn3d = orig.xyz_path
    ? `<button class="btn-3d btn-3d-orig" id="job-btn-3d-orig" title="Visualiser le benzenoide d'entree optimise">3D</button>`
    : "";
  box.innerHTML = `
    <div class="item"><span class="label">Verdict</span>
      <span class="value">${badge} ${btn3d}</span></div>
    <div class="item"><span class="label">Angle max</span>
      <span class="value">${orig.angle_deg != null ? orig.angle_deg.toFixed(2) + "°" : "—"}</span></div>
    <div class="item"><span class="label">RMSD</span>
      <span class="value">${orig.rmsd != null ? orig.rmsd.toFixed(4) : "—"}</span></div>
    <div class="item"><span class="label">Hauteur</span>
      <span class="value">${orig.height != null ? orig.height.toFixed(4) : "—"}</span></div>
    <div class="item"><span class="label">Seuil</span>
      <span class="value">${orig.threshold_deg ?? 10}°</span></div>
  `;
  const btn = $("#job-btn-3d-orig");
  if (btn && orig.xyz_path) {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openMolViz({
        xyz_path: orig.xyz_path,
        title: "Benzenoide d'entree (opt xTB)",
        subtitle: orig.planar ? "PLAN" : `NON PLAN (${(orig.angle_deg ?? 0).toFixed(1)}°)`,
      });
    });
  }
}

function filteredJobSolutions() {
  let sols = state.jobSolutions;
  if (state.jobSolFilter !== "all") {
    sols = sols.filter((s) => (s.verdict || "unknown") === state.jobSolFilter);
  }
  if (state.jobSolSearch) {
    const q = state.jobSolSearch.toLowerCase();
    sols = sols.filter((s) =>
      (s.sol_idx || "").toString().includes(q) ||
      (s.sizes || "").toLowerCase().includes(q) ||
      (s.name || "").toLowerCase().includes(q)
    );
  }
  return sols;
}

// Selection courante pour l'export zip (cles = best_xyz_path). Reinitialisee
// a chaque changement de job (cf. loadJobView) mais PAS a chaque re-render
// du tableau (filtre/recherche), pour que la selection survive un filtrage.
const jobSolSelection = new Set();

function renderJobSolTable() {
  const wrap = $("#job-sol-table-wrap");
  const sols = filteredJobSolutions();
  if (sols.length === 0) {
    if (state.jobSolutions.length === 0) {
      wrap.innerHTML = `<div class="empty">
        Aucune solution materialisee pour ce job.<br>
        <span class="muted">Active "Validation xTB" pour produire les fichiers .xyz.</span>
      </div>`;
    } else {
      wrap.innerHTML = `<div class="empty">Aucune solution ne correspond au filtre.</div>`;
    }
    updateJobExportBar();
    return;
  }

  // Colonnes alignees sur view-mol + case a cocher (export) en tete.
  // Verdict = plan/non_plan/md_failed/unknown.
  let h = `<table><thead><tr>
    <th><input type="checkbox" id="job-sol-select-all" title="Tout selectionner"></th>
    <th>Sol_idx</th>
    <th>Sizes</th>
    <th>Verdict</th>
    <th>Angle</th>
    <th>RMSD</th>
    <th>Height</th>
    <th>Tentatives MD</th>
    <th>Vue 3D</th>
  </tr></thead><tbody>`;
  for (const s of sols) {
    const sizesDisplay = (s.sizes || "").replace(/_/g, "-") || "?";
    let badge, rowClass = "", angleCell, rmsdCell, heightCell;

    if (s.verdict === "plan") {
      badge = `<span class="badge plan">PLAN</span>`;
    } else if (s.verdict === "non_plan") {
      badge = `<span class="badge non-plan">NON</span>`;
    } else if (s.verdict === "md_failed") {
      badge = `<span class="badge xtb-failed" title="xTB MD n'a pas converge">MD ✗</span>`;
      rowClass = "row-xtb-failed";
    } else {
      badge = `<span class="badge infeasible" title="Planarite non calculee">—</span>`;
    }
    if (s.from_cache) {
      badge += ` <span class="badge cache-hit" title="Solution identique deja calculee : resultat repris du cache, xTB non relance">⚡ cache</span>`;
    }

    angleCell = (s.angle_deg != null) ? s.angle_deg.toFixed(3) + "°" : "—";
    rmsdCell = (s.rmsd != null) ? s.rmsd.toFixed(4) : "—";
    heightCell = (s.height != null) ? s.height.toFixed(4) : "—";
    const attemptsCell = s.n_attempts != null ? s.n_attempts : "—";

    const btn3d = s.best_xyz_path
      ? `<button class="btn-3d" data-path="${s.best_xyz_path}" data-name="${s.name}" data-sizes="${sizesDisplay}" data-verdict="${s.verdict}">3D</button>`
      : `<span class="muted">—</span>`;

    const checkCell = s.best_xyz_path
      ? `<input type="checkbox" class="job-sol-check" data-path="${s.best_xyz_path}"${jobSolSelection.has(s.best_xyz_path) ? " checked" : ""}>`
      : `<input type="checkbox" disabled title="Pas de fichier .xyz pour cette solution">`;

    h += `<tr${rowClass ? ` class="${rowClass}"` : ""}>
      <td>${checkCell}</td>
      <td><strong>${s.sol_idx}</strong></td>
      <td><code>${sizesDisplay}</code></td>
      <td>${badge}</td>
      <td>${angleCell}</td>
      <td>${rmsdCell}</td>
      <td>${heightCell}</td>
      <td>${attemptsCell}</td>
      <td>${btn3d}</td>
    </tr>`;
  }
  h += `</tbody></table>`;
  wrap.innerHTML = h;

  wrap.querySelectorAll(".btn-3d").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openMolViz({
        xyz_path: btn.dataset.path,
        title: `Job #${state.jobId} · ${btn.dataset.name}`,
        subtitle: `sizes ${btn.dataset.sizes} · ${btn.dataset.verdict}`,
      });
    });
  });

  wrap.querySelectorAll(".job-sol-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      if (cb.checked) jobSolSelection.add(cb.dataset.path);
      else jobSolSelection.delete(cb.dataset.path);
      updateJobExportBar();
    });
  });

  // "Tout selectionner" ne porte que sur les lignes actuellement visibles
  // (apres filtre) : coherent avec ce que l'utilisateur voit a l'ecran.
  const selectAll = $("#job-sol-select-all");
  const visiblePaths = sols.map((s) => s.best_xyz_path).filter(Boolean);
  selectAll.checked = visiblePaths.length > 0 && visiblePaths.every((p) => jobSolSelection.has(p));
  selectAll.addEventListener("change", () => {
    for (const p of visiblePaths) {
      if (selectAll.checked) jobSolSelection.add(p);
      else jobSolSelection.delete(p);
    }
    renderJobSolTable();
  });

  updateJobExportBar();
}

/** Met a jour le compteur + l'etat du bouton "Exporter la selection". */
function updateJobExportBar() {
  const bar = $("#job-export-bar");
  const countEl = $("#job-export-count");
  const btn = $("#job-export-btn");
  if (!bar) return;
  const n = jobSolSelection.size;
  bar.classList.toggle("hidden", n === 0);
  if (countEl) countEl.textContent = `${n} solution${n > 1 ? "s" : ""} selectionnee${n > 1 ? "s" : ""}`;
  if (btn) btn.disabled = n === 0;
}

/** Construit l'URL /api/xyz_export pour la selection courante et declenche
 *  le telechargement (navigation directe : Content-Disposition fait le reste).
 */
function exportJobSelection() {
  if (jobSolSelection.size === 0) return;
  const params = new URLSearchParams();
  for (const p of jobSolSelection) params.append("path", p);
  params.set("filename", `job_${state.jobId}_export`);
  window.location.href = `/api/xyz_export?${params.toString()}`;
}

// ===== Pagination =====
function renderPagination(container, total, page, size, onPage) {
  container.innerHTML = "";
  const pages = Math.ceil(total / size);
  if (pages <= 1) {
    container.innerHTML = `<span class="info">${total} entrées</span>`;
    return;
  }
  const mk = (label, p, active = false, disabled = false) => {
    const b = document.createElement("button");
    b.textContent = label;
    if (active) b.classList.add("active");
    if (disabled) b.disabled = true;
    if (!disabled && !active) b.addEventListener("click", () => onPage(p));
    return b;
  };
  container.appendChild(mk("«", 1, false, page === 1));
  container.appendChild(mk("‹", page - 1, false, page === 1));

  // window of pages around current
  const win = 2;
  let start = Math.max(1, page - win);
  let end = Math.min(pages, page + win);
  if (start > 1) {
    container.appendChild(mk("1", 1, page === 1));
    if (start > 2) {
      const span = document.createElement("span");
      span.className = "info";
      span.textContent = "…";
      container.appendChild(span);
    }
  }
  for (let p = start; p <= end; p++) {
    container.appendChild(mk(String(p), p, p === page));
  }
  if (end < pages) {
    if (end < pages - 1) {
      const span = document.createElement("span");
      span.className = "info";
      span.textContent = "…";
      container.appendChild(span);
    }
    container.appendChild(mk(String(pages), pages, page === pages));
  }

  container.appendChild(mk("›", page + 1, false, page === pages));
  container.appendChild(mk("»", pages, false, page === pages));

  const info = document.createElement("span");
  info.className = "info";
  info.textContent = ` ${total.toLocaleString()} entrées`;
  container.appendChild(info);
}

// ===== Bind toolbar events =====
let searchTimer = null;
$("#mol-search").addEventListener("input", (e) => {
  state.molSearch = e.target.value;
  state.molPage = 1;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(fetchMolecules, 250);
});
$("#mol-sort").addEventListener("change", (e) => {
  state.molSort = e.target.value;
  state.molPage = 1;
  fetchMolecules();
});
$("#mol-pagesize").addEventListener("change", (e) => {
  state.molSize = parseInt(e.target.value, 10);
  state.molPage = 1;
  fetchMolecules();
});
let solSearchTimer = null;
$("#sol-search").addEventListener("input", (e) => {
  state.solSearch = e.target.value;
  state.solPage = 1;
  clearTimeout(solSearchTimer);
  solSearchTimer = setTimeout(fetchSolutions, 250);
});
$("#sol-filter").addEventListener("change", (e) => {
  state.solFilter = e.target.value;
  state.solPage = 1;
  fetchSolutions();
});
$("#sol-sort").addEventListener("change", (e) => {
  state.solSort = e.target.value;
  state.solPage = 1;
  fetchSolutions();
});
$("#sol-pagesize").addEventListener("change", (e) => {
  state.solSize = parseInt(e.target.value, 10);
  state.solPage = 1;
  fetchSolutions();
});

// Vue job designer : filtre + recherche
let jobSearchTimer = null;
$("#job-sol-search").addEventListener("input", (e) => {
  state.jobSolSearch = e.target.value;
  clearTimeout(jobSearchTimer);
  jobSearchTimer = setTimeout(renderJobSolTable, 200);
});
$("#job-sol-filter").addEventListener("change", (e) => {
  state.jobSolFilter = e.target.value;
  renderJobSolTable();
});
$("#job-export-btn").addEventListener("click", exportJobSelection);

// ===== Initial load =====
(async () => {
  // Routing : si ?job=<id>, ouvre directement la vue job sans charger
  // les datasets (independant). On charge quand meme la liste des datasets
  // pour que le selecteur soit utilisable si l'utilisateur navigue ailleurs.
  const urlParams = new URLSearchParams(window.location.search);
  const jobId = urlParams.get("job");
  if (jobId) {
    // Verifier que l'id ressemble a un UUID court (alpha-num 6-12 chars)
    if (/^[a-f0-9]{6,12}$/i.test(jobId)) {
      loadDatasets(true).catch(() => {});  // best-effort en background, silencieux
      loadJobView(jobId);
      return;
    }
  }
  // Silencieux : en mode --designer-only (pas de table 'configs'), il n'y a
  // aucun dataset a afficher. loadDashboard() gere deja ce cas (state.h reste
  // null -> retour anticipe), donc pas besoin d'interrompre l'utilisateur
  // avec une alerte bloquante des l'arrivee sur la page.
  await loadDatasets(true).catch(() => {});
  loadDashboard();
})();
