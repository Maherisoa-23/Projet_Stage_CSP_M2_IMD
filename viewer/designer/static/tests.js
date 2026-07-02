/**
 * Page "Mes tests" : organisation des jobs designer en collections.
 *
 * Modele : un job appartient a AU PLUS UNE collection (collection_id
 * nullable). Les jobs sans collection sont regroupes sous le
 * pseudo-dossier "Non classes" (toujours affiche en tete de la sidebar).
 *
 * Endpoints consommes :
 *   GET    /api/designer/collections                -> liste + unfiled_count
 *   POST   /api/designer/collections                 -> creer
 *   PATCH  /api/designer/collections/<id>             -> renommer/decrire
 *   DELETE /api/designer/collections/<id>             -> supprimer (jobs -> non classes)
 *   GET    /api/designer/jobs?collection_id=&unfiled=&search=
 *   PATCH  /api/designer/jobs/<id>                    -> {name?, collection_id?}
 *   DELETE /api/designer/jobs/<id>                    -> supprime job + fichiers
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const state = {
    collections: [],       // [{id, name, description, job_count}]
    unfiledCount: 0,
    selectedCollectionId: null,   // null = "Tous les jobs" (aucun filtre)
    selectedIsUnfiled: false,      // true = filtre "Non classes" specifiquement
    jobs: [],
    search: "",
    editingCollectionId: null,     // null = mode creation dans la modale
  };

  // ===== Fetch helpers =====
  async function apiGet(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }
  async function apiSend(url, method, body) {
    const r = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { const d = await r.json(); if (d.description) msg = d.description; } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  // ===== Collections sidebar =====
  async function loadCollections() {
    try {
      const data = await apiGet("/api/designer/collections");
      state.collections = data.collections || [];
      state.unfiledCount = data.unfiled_count || 0;
      renderCollections();
    } catch (e) {
      $("#collections-list").innerHTML = `<p class="dz-muted">Erreur : ${e.message}</p>`;
    }
  }

  function renderCollections() {
    const wrap = $("#collections-list");
    wrap.innerHTML = "";

    // "Tous les jobs" (aucun filtre)
    wrap.appendChild(makeCollItem({
      label: "Tous les jobs",
      count: null,
      active: state.selectedCollectionId === null && !state.selectedIsUnfiled,
      onClick: () => selectCollection(null, false),
    }));

    // "Non classes"
    wrap.appendChild(makeCollItem({
      label: "📥 Non classes",
      count: state.unfiledCount,
      active: state.selectedIsUnfiled,
      onClick: () => selectCollection(null, true),
    }));

    if (state.collections.length > 0) {
      const sep = document.createElement("div");
      sep.style.cssText = "height:1px;background:#e5e7eb;margin:0.5rem 0.2rem;";
      wrap.appendChild(sep);
    }

    for (const c of state.collections) {
      wrap.appendChild(makeCollItem({
        label: c.name,
        count: c.job_count,
        active: state.selectedCollectionId === c.id,
        onClick: () => selectCollection(c.id, false),
        onEdit: () => openCollectionModal(c),
        onDelete: () => deleteCollection(c),
      }));
    }
  }

  function makeCollItem({ label, count, active, onClick, onEdit, onDelete }) {
    const item = document.createElement("div");
    item.className = "tst-coll-item" + (active ? " active" : "");
    const name = document.createElement("span");
    name.className = "tst-coll-name";
    name.textContent = label;
    name.title = label;
    item.appendChild(name);

    if (count != null) {
      const badge = document.createElement("span");
      badge.className = "tst-coll-count";
      badge.textContent = count;
      item.appendChild(badge);
    }

    if (onEdit || onDelete) {
      const actions = document.createElement("span");
      actions.className = "tst-coll-actions";
      if (onEdit) {
        const b = document.createElement("button");
        b.textContent = "✎";
        b.title = "Renommer / editer";
        b.addEventListener("click", (ev) => { ev.stopPropagation(); onEdit(); });
        actions.appendChild(b);
      }
      if (onDelete) {
        const b = document.createElement("button");
        b.textContent = "🗑";
        b.title = "Supprimer la collection (les jobs redeviennent non classes)";
        b.addEventListener("click", (ev) => { ev.stopPropagation(); onDelete(); });
        actions.appendChild(b);
      }
      item.appendChild(actions);
    }

    item.addEventListener("click", onClick);
    return item;
  }

  function selectCollection(collId, isUnfiled) {
    state.selectedCollectionId = collId;
    state.selectedIsUnfiled = isUnfiled;
    renderCollections();
    loadJobs();
  }

  // ===== Collection modal (creer / editer) =====
  function openCollectionModal(coll) {
    state.editingCollectionId = coll ? coll.id : null;
    $("#collection-modal-title").textContent = coll ? "Modifier la collection" : "Nouvelle collection";
    $("#collection-name-input").value = coll ? coll.name : "";
    $("#collection-desc-input").value = coll ? (coll.description || "") : "";
    $("#collection-modal").classList.remove("hidden");
    $("#collection-name-input").focus();
  }
  function closeCollectionModal() {
    $("#collection-modal").classList.add("hidden");
    state.editingCollectionId = null;
  }
  async function saveCollectionModal() {
    const name = $("#collection-name-input").value.trim();
    if (!name) { alert("Le nom est requis."); return; }
    const description = $("#collection-desc-input").value.trim();
    try {
      if (state.editingCollectionId) {
        await apiSend(`/api/designer/collections/${state.editingCollectionId}`, "PATCH",
                      { name, description });
      } else {
        await apiSend("/api/designer/collections", "POST", { name, description });
      }
      closeCollectionModal();
      await loadCollections();
    } catch (e) {
      alert(`Erreur : ${e.message}`);
    }
  }
  async function deleteCollection(coll) {
    if (!confirm(`Supprimer la collection "${coll.name}" ?\n\nLes ${coll.job_count} job(s) qu'elle contient ne seront PAS supprimes, ils redeviendront "non classes".`)) return;
    try {
      await apiSend(`/api/designer/collections/${coll.id}`, "DELETE");
      if (state.selectedCollectionId === coll.id) {
        state.selectedCollectionId = null;
        state.selectedIsUnfiled = false;
      }
      await loadCollections();
      await loadJobs();
    } catch (e) {
      alert(`Erreur : ${e.message}`);
    }
  }

  // ===== Jobs table =====
  async function loadJobs() {
    const wrap = $("#jobs-table-wrap");
    wrap.innerHTML = '<div class="dz-loading-mini">Chargement…</div>';

    const title = $("#content-title");
    if (state.selectedIsUnfiled) title.textContent = "Non classes";
    else if (state.selectedCollectionId) {
      const c = state.collections.find((c) => c.id === state.selectedCollectionId);
      title.textContent = c ? c.name : "Collection";
    } else {
      title.textContent = "Tous les jobs";
    }

    const params = new URLSearchParams();
    params.set("limit", "200");
    if (state.selectedIsUnfiled) params.set("unfiled", "1");
    else if (state.selectedCollectionId) params.set("collection_id", state.selectedCollectionId);
    if (state.search) params.set("search", state.search);

    try {
      const data = await apiGet(`/api/designer/jobs?${params.toString()}`);
      state.jobs = data.jobs || [];
      renderJobsTable();
    } catch (e) {
      wrap.innerHTML = `<p class="dz-muted">Erreur : ${e.message}</p>`;
    }
  }

  const STATE_LABELS = {
    pending: "en attente", running: "en cours", success: "termine",
    failed: "echoue", cancelled: "annule",
  };

  function renderJobsTable() {
    const wrap = $("#jobs-table-wrap");
    if (state.jobs.length === 0) {
      wrap.innerHTML = `<div class="tst-empty">Aucun job ici.<br>
        <span class="dz-muted">Lancez une generation depuis le <a href="/designer">designer</a>.</span></div>`;
      return;
    }

    let h = `<table class="tst-table"><thead><tr>
      <th style="width:35%">Nom</th>
      <th>Etat</th>
      <th>Cree le</th>
      <th>Collection</th>
      <th style="text-align:right">Actions</th>
    </tr></thead><tbody>`;

    for (const j of state.jobs) {
      const displayName = j.name || `#${j.job_id}`;
      const dateStr = (j.created_at || "").replace("T", " ").slice(0, 16);
      const badge = `<span class="dz-job-state ${j.state}">${STATE_LABELS[j.state] || j.state}</span>`;

      let collSelect = `<select class="tst-coll-select" data-job="${j.job_id}">`;
      collSelect += `<option value="">— Non classe —</option>`;
      for (const c of state.collections) {
        const sel = c.id === j.collection_id ? " selected" : "";
        collSelect += `<option value="${c.id}"${sel}>${escapeHtml(c.name)}</option>`;
      }
      collSelect += `</select>`;

      const canOpen = ["success", "failed", "cancelled"].includes(j.state);

      h += `<tr data-job="${j.job_id}">
        <td>
          <div class="tst-job-name" data-job="${j.job_id}" title="Cliquer pour renommer">
            ${escapeHtml(displayName)}${j.name ? ` <span class="tst-job-id-muted">#${j.job_id}</span>` : ""}
          </div>
        </td>
        <td>${badge}</td>
        <td class="dz-muted">${dateStr}</td>
        <td>${collSelect}</td>
        <td>
          <div class="tst-job-actions">
            ${canOpen ? `<button class="tst-open-btn" data-job="${j.job_id}">Ouvrir</button>` : ""}
            <button class="tst-delete-btn" data-job="${j.job_id}">Supprimer</button>
          </div>
        </td>
      </tr>`;
    }
    h += `</tbody></table>`;
    wrap.innerHTML = h;

    bindJobRowEvents(wrap);
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function bindJobRowEvents(wrap) {
    // Renommage inline : clic -> input
    wrap.querySelectorAll(".tst-job-name").forEach((el) => {
      el.addEventListener("click", () => startRename(el));
    });
    // Deplacement vers une collection
    wrap.querySelectorAll(".tst-coll-select").forEach((sel) => {
      sel.addEventListener("change", async () => {
        const jobId = sel.dataset.job;
        const collId = sel.value || null;
        try {
          await apiSend(`/api/designer/jobs/${jobId}`, "PATCH", { collection_id: collId });
          await loadCollections();
          // Si on est filtre sur une collection specifique, le job qui vient
          // d'en sortir doit disparaitre de la vue courante.
          if (state.selectedCollectionId || state.selectedIsUnfiled) loadJobs();
        } catch (e) {
          alert(`Erreur : ${e.message}`);
          loadJobs();
        }
      });
    });
    // Ouvrir (vue detail existante, /?job=<id>)
    wrap.querySelectorAll(".tst-open-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        window.location.href = `/?job=${btn.dataset.job}`;
      });
    });
    // Supprimer
    wrap.querySelectorAll(".tst-delete-btn").forEach((btn) => {
      btn.addEventListener("click", () => deleteJob(btn.dataset.job));
    });
  }

  function startRename(el) {
    const jobId = el.dataset.job;
    const job = state.jobs.find((j) => j.job_id === jobId);
    if (!job) return;
    const current = job.name || "";
    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 200;
    input.value = current;
    input.placeholder = `#${jobId}`;
    el.innerHTML = "";
    el.appendChild(input);
    input.focus();
    input.select();

    let done = false;
    const commit = async () => {
      if (done) return;
      done = true;
      const newName = input.value.trim();
      if (newName === current) { renderJobsTable(); return; }
      try {
        await apiSend(`/api/designer/jobs/${jobId}`, "PATCH", { name: newName });
        job.name = newName || null;
      } catch (e) {
        alert(`Erreur : ${e.message}`);
      }
      renderJobsTable();
    };
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") input.blur();
      if (ev.key === "Escape") { done = true; renderJobsTable(); }
    });
  }

  async function deleteJob(jobId) {
    const job = state.jobs.find((j) => j.job_id === jobId);
    const label = job && job.name ? `"${job.name}"` : `#${jobId}`;
    if (!confirm(`Supprimer definitivement le job ${label} ?\n\nCette action supprime aussi tous les fichiers .xyz generes. Impossible a annuler.`)) return;
    try {
      await apiSend(`/api/designer/jobs/${jobId}`, "DELETE");
      await loadCollections();
      await loadJobs();
    } catch (e) {
      alert(`Erreur : ${e.message}`);
    }
  }

  // ===== Boot =====
  function init() {
    $("#btn-new-collection").addEventListener("click", () => openCollectionModal(null));
    $("#collection-modal-cancel").addEventListener("click", closeCollectionModal);
    $("#collection-modal-save").addEventListener("click", saveCollectionModal);
    $("#collection-modal").addEventListener("click", (ev) => {
      if (ev.target.id === "collection-modal") closeCollectionModal();
    });

    let searchTimer = null;
    $("#job-search").addEventListener("input", (ev) => {
      state.search = ev.target.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadJobs, 250);
    });

    loadCollections().then(loadJobs);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
