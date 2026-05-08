// ===== State =====
const state = {
  view: "dashboard",       // "dashboard" | "config" | "molecule"
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

async function fetchJSON(url, label) {
  showLoader(label);
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    alert(`Erreur réseau : ${e.message}`);
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
  let html = `<a href="#" data-go="dashboard">Dashboard</a>`;
  if (state.config) {
    html += `<span class="sep">/</span><a href="#" data-go="config">${state.config}</a>`;
  }
  if (state.mol) {
    html += `<span class="sep">/</span><a href="#" data-go="mol">${state.mol}</a>`;
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

// ===== Dashboard =====
async function loadDashboard() {
  state.config = null;
  state.mol = null;
  setView("dashboard");
  const data = await fetchJSON("/api/summary", "Stats…");
  $("#summary-text").textContent =
    `${data.n_unique_molecules} molécules uniques × ${data.configs.length} configurations`;
  const grid = $("#configs-grid");
  grid.innerHTML = "";
  for (const c of data.configs) {
    const pct = c.n_solutions > 0 ? (100 * c.n_plans / c.n_solutions) : 0;
    const infeasible = c.n_geom_infeasible || 0;
    const card = document.createElement("div");
    card.className = "config-card";
    card.innerHTML = `
      <h3>${c.name}</h3>
      <div class="row"><span class="label">Molécules</span><span>${c.n_molecules}</span></div>
      <div class="row"><span class="label">Solutions validées</span><span>${c.n_solutions.toLocaleString()}</span></div>
      <div class="row"><span class="label">Plans</span><span style="color:var(--success)">${c.n_plans.toLocaleString()} (${pct.toFixed(1)}%)</span></div>
      <div class="row"><span class="label">Non plans</span><span style="color:var(--danger)">${c.n_non_plans.toLocaleString()}</span></div>
      ${infeasible > 0 ? `<div class="row"><span class="label">Géom. infaisables</span><span style="color:var(--muted)">${infeasible.toLocaleString()}</span></div>` : ""}
      <div class="pct-bar"><div style="width:${pct}%"></div></div>
    `;
    card.addEventListener("click", () => loadConfig(c.name));
    grid.appendChild(card);
  }
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
  await fetchMolecules();
}

async function fetchMolecules() {
  const params = new URLSearchParams({
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
    <th title="Solutions reconstruites + validées par xTB">MD validées</th>
    <th title="Solutions CSP-valides mais reconstruction 3D impossible (pentagone/heptagone sur hexagone trop contraint)">Géom. ✗</th>
    <th>Plans</th>
    <th>Non plans</th>
    <th>Angle min</th>
    <th>Original</th>
    <th>Job</th>
  </tr></thead><tbody>`;
  for (const m of data.molecules) {
    const pct = m.n_md_completed > 0 ? (100 * m.n_plans / m.n_md_completed).toFixed(0) : "—";
    const infeasible = m.n_geom_infeasible || 0;
    const xtbFailed = m.n_xtb_failed || 0;
    // Cellule "MD validées" : juste le compte (sans badge orange).
    // Cellule "Géom ✗" affiche les sols CSP-valides mais infaisables 3D.
    const orig = m.original_planar === null ? "—"
      : m.original_planar
        ? `<span class="badge plan">PLAN ${(m.original_angle_deg ?? 0).toFixed(1)}°</span>`
        : `<span class="badge non-plan">NON ${(m.original_angle_deg ?? 0).toFixed(1)}°</span>`;
    const geomCell = infeasible > 0
      ? `<span class="muted" title="Reconstruction 3D impossible : structure CSP-valide mais inaccessible géométriquement">${infeasible}</span>`
      : `<span class="muted">0</span>`;
    h += `<tr data-mol="${m.mol}">
      <td><strong>${m.mol}</strong></td>
      <td>${m.n_solutions_csp ?? "—"}</td>
      <td>${m.n_md_completed ?? "—"}</td>
      <td>${geomCell}${xtbFailed > 0 ? ` <span class="muted" title="Reconstruction OK mais xTB a échoué">+${xtbFailed} xTB✗</span>` : ""}</td>
      <td style="color:var(--success)"><strong>${m.n_plans}</strong> ${pct !== "—" ? `(${pct}%)` : ""}</td>
      <td style="color:var(--danger)">${m.n_non_plans}</td>
      <td>${m.min_angle === null ? "—" : m.min_angle.toFixed(2) + "°"}</td>
      <td>${orig}</td>
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
  $("#sol-filter").value = "plans";
  $("#sol-sort").value = "angle";
  setView("mol");
  $("#mol-title").textContent = `Molécule : ${mol}  (${config})`;
  await fetchSolutions();
}

async function fetchSolutions() {
  const params = new URLSearchParams({
    config: state.config,
    mol: state.mol,
    filter: state.solFilter,
    page: state.solPage,
    size: state.solSize,
    sort: state.solSort,
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
  const orig = meta.original_planar === null ? "—"
    : (meta.original_planar ? "PLAN" : "NON PLAN") + ` (${(meta.original_angle_deg ?? 0).toFixed(2)}°)`;
  const infeasible = meta.n_geom_infeasible || 0;
  const xtbFailed = meta.n_xtb_failed || 0;
  box.innerHTML = `
    <div class="item"><span class="label">CSP combinatoire</span><span class="value">${meta.n_solutions_csp ?? "—"}</span></div>
    <div class="item"><span class="label">MD validées</span><span class="value">${meta.n_md_completed ?? "—"}</span></div>
    ${infeasible > 0 ? `<div class="item" title="Solutions CSP-valides mais reconstruction 3D impossible"><span class="label">Géom. infaisables</span><span class="value" style="color:var(--muted)">${infeasible}</span></div>` : ""}
    ${xtbFailed > 0 ? `<div class="item" title="Reconstruction OK mais xTB a échoué"><span class="label">xTB échec</span><span class="value" style="color:var(--muted)">${xtbFailed}</span></div>` : ""}
    <div class="item"><span class="label">Plans</span><span class="value" style="color:var(--success)">${meta.n_plans}</span></div>
    <div class="item"><span class="label">Non plans</span><span class="value" style="color:var(--danger)">${meta.n_non_plans}</span></div>
    <div class="item"><span class="label">Angle min</span><span class="value">${meta.min_angle === null ? "—" : meta.min_angle.toFixed(2) + "°"}</span></div>
    <div class="item"><span class="label">Angle max</span><span class="value">${meta.max_angle === null ? "—" : meta.max_angle.toFixed(2) + "°"}</span></div>
    <div class="item"><span class="label">Original</span><span class="value">${orig}</span></div>
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
    <th>Angle</th>
    <th>RMSD</th>
    <th>Height</th>
    <th>Tentatives MD</th>
    <th>Fichiers</th>
  </tr></thead><tbody>`;
  for (const s of data.solutions) {
    const v = s.planar
      ? `<span class="badge plan">PLAN</span>`
      : `<span class="badge non-plan">NON</span>`;
    const finalRel = `${s.sol_dir}/md_validation/md_final_opt.xyz`;
    const sourceRel = `${s.sol_dir}/source.xyz`;
    h += `<tr>
      <td><strong>${s.sol_idx}</strong></td>
      <td><code>${s.sizes}</code></td>
      <td>${v}</td>
      <td>${s.angle_deg.toFixed(3)}°</td>
      <td>${s.rmsd?.toFixed(4) ?? "—"}</td>
      <td>${s.height?.toFixed(4) ?? "—"}</td>
      <td>${s.n_attempts ?? "—"}</td>
      <td>
        <a href="/file?path=${encodeURIComponent(sourceRel)}" target="_blank">source</a>
        ·
        <a href="/file?path=${encodeURIComponent(finalRel)}" target="_blank">final</a>
      </td>
    </tr>`;
  }
  h += `</tbody></table>`;
  wrap.innerHTML = h;
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

// ===== Initial load =====
loadDashboard();
