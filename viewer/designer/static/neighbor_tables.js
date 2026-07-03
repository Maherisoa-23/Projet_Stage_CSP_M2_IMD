/**
 * Page "Tables de voisinage" : CRUD des tables T(n) (contrainte C3 du CSP).
 *
 * Une table contient, pour chaque taille de cycle n in {5,6,7}, la liste
 * des sequences de voisins admissibles. La table par defaut (migree depuis
 * csp_solver/data/table_voisinage.json) est protegee : non supprimable,
 * mais modifiable/dupliquable comme les autres.
 *
 * Endpoints consommes :
 *   GET    /api/designer/neighbor-tables                  -> liste (sans contenu)
 *   GET    /api/designer/neighbor-tables/<id>              -> detail + contenu + n_jobs_using
 *   POST   /api/designer/neighbor-tables                   -> {source_id, name} duplique
 *   PATCH  /api/designer/neighbor-tables/<id>               -> {name?, description?}
 *   POST   /api/designer/neighbor-tables/<id>/sequences     -> {cycle_size, sequence} ajoute
 *   DELETE /api/designer/neighbor-tables/<id>/sequences     -> {cycle_size, sequence} retire
 *   DELETE /api/designer/neighbor-tables/<id>               -> {confirm?} supprime
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const CYCLE_SIZES = [5, 6, 7];

  const state = {
    tables: [],           // [{id, name, description, is_default, n_seq}]
    selectedId: null,
    current: null,        // detail complet de la table selectionnee (avec content)
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
      try {
        const text = await r.text();
        const m = text.match(/<p>(.+?)<\/p>/);
        if (m) msg = m[1];
      } catch (_) {}
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    return r.json();
  }

  // ===== Sidebar : liste des tables =====
  async function loadTables() {
    try {
      const data = await apiGet("/api/designer/neighbor-tables");
      state.tables = data.tables || [];
      renderTablesList();
    } catch (e) {
      $("#tables-list").innerHTML = `<p class="dz-muted">Erreur : ${e.message}</p>`;
    }
  }

  function renderTablesList() {
    const wrap = $("#tables-list");
    wrap.innerHTML = "";
    if (state.tables.length === 0) {
      wrap.innerHTML = '<p class="dz-muted">Aucune table.</p>';
      return;
    }
    for (const t of state.tables) {
      const item = document.createElement("div");
      item.className = "ntb-table-item" + (t.id === state.selectedId ? " active" : "");
      const nTotal = (t.n_seq[5] || 0) + (t.n_seq[6] || 0) + (t.n_seq[7] || 0);
      item.innerHTML = `
        <div class="ntb-table-item-name">${escapeHtml(t.name)}${t.is_default ? '<span class="ntb-badge-default">par defaut</span>' : ""}</div>
        <div class="ntb-table-item-meta">${nTotal} sequences (5:${t.n_seq[5]||0} 6:${t.n_seq[6]||0} 7:${t.n_seq[7]||0})</div>
      `;
      item.addEventListener("click", () => selectTable(t.id));
      wrap.appendChild(item);
    }
  }

  async function selectTable(id) {
    state.selectedId = id;
    renderTablesList();
    const content = $("#ntb-content");
    content.innerHTML = '<div class="dz-loading-mini">Chargement…</div>';
    try {
      state.current = await apiGet(`/api/designer/neighbor-tables/${id}`);
      renderEditor();
    } catch (e) {
      content.innerHTML = `<p class="dz-muted">Erreur : ${e.message}</p>`;
    }
  }

  // ===== Editeur de la table selectionnee =====
  function renderEditor() {
    const t = state.current;
    const content = $("#ntb-content");
    content.innerHTML = "";

    // Header : nom (editable), badge defaut, actions (dupliquer / supprimer)
    const header = document.createElement("div");
    header.className = "ntb-editor-header";

    const titleBox = document.createElement("div");
    titleBox.style.flex = "1";
    const titleRow = document.createElement("div");
    titleRow.className = "ntb-editor-title";
    const nameInput = document.createElement("input");
    nameInput.className = "ntb-name-field";
    nameInput.value = t.name;
    nameInput.disabled = false;
    nameInput.addEventListener("change", () => commitField("name", nameInput.value.trim()));
    titleRow.appendChild(nameInput);
    if (t.is_default) {
      const badge = document.createElement("span");
      badge.className = "ntb-badge-default";
      badge.textContent = "par defaut — non supprimable";
      titleRow.appendChild(badge);
    }
    titleBox.appendChild(titleRow);

    const descInput = document.createElement("textarea");
    descInput.className = "ntb-desc-field";
    descInput.rows = 1;
    descInput.placeholder = "Description (optionnel)";
    descInput.value = t.description || "";
    descInput.addEventListener("change", () => commitField("description", descInput.value.trim()));
    titleBox.appendChild(descInput);

    header.appendChild(titleBox);

    const actions = document.createElement("div");
    actions.className = "ntb-editor-actions";
    const dupBtn = document.createElement("button");
    dupBtn.textContent = "Dupliquer";
    dupBtn.addEventListener("click", () => openNewTableModal(t.id));
    actions.appendChild(dupBtn);
    if (!t.is_default) {
      const delBtn = document.createElement("button");
      delBtn.className = "ntb-delete-btn";
      delBtn.textContent = "Supprimer";
      delBtn.addEventListener("click", () => deleteTable(t));
      actions.appendChild(delBtn);
    }
    header.appendChild(actions);
    content.appendChild(header);

    if (t.n_jobs_using > 0) {
      const note = document.createElement("div");
      note.className = "ntb-jobs-note";
      note.textContent = `Cette table a deja ete utilisee par ${t.n_jobs_using} job(s). ` +
        `La modifier change le comportement pour les futurs jobs seulement -- ` +
        `les resultats deja calcules ne sont pas affectes.`;
      content.appendChild(note);
    }

    // Un groupe par taille de cycle
    for (const n of CYCLE_SIZES) {
      content.appendChild(renderCycleGroup(n));
    }
  }

  async function commitField(key, value) {
    if (key === "name" && !value) {
      alert("Le nom ne peut pas etre vide.");
      renderEditor();
      return;
    }
    try {
      await apiSend(`/api/designer/neighbor-tables/${state.current.id}`, "PATCH", { [key]: value });
      state.current[key] = value;
      await loadTables();
      renderTablesList();
    } catch (e) {
      alert(`Erreur : ${e.message}`);
      renderEditor();
    }
  }

  function renderCycleGroup(n) {
    const sec = document.createElement("div");
    sec.className = "ntb-cycle-group";
    const title = document.createElement("h3");
    title.textContent = `Cycle taille ${n}`;
    sec.appendChild(title);

    const seqs = (state.current.content[String(n)] || []);
    const list = document.createElement("div");
    list.className = "ntb-seq-list";
    if (seqs.length === 0) {
      const empty = document.createElement("span");
      empty.className = "ntb-seq-empty";
      empty.textContent = "Aucune sequence.";
      list.appendChild(empty);
    } else {
      for (const seq of seqs) {
        const chip = document.createElement("span");
        chip.className = "ntb-seq-chip";
        const txt = document.createElement("span");
        txt.textContent = seq.join("_");
        chip.appendChild(txt);
        const btn = document.createElement("button");
        btn.textContent = "×";
        btn.title = "Retirer cette sequence";
        btn.addEventListener("click", () => removeSequence(n, seq));
        chip.appendChild(btn);
        list.appendChild(chip);
      }
    }
    sec.appendChild(list);

    // Formulaire d'ajout : n selecteurs 0/5/6/7
    const addRow = document.createElement("div");
    addRow.className = "ntb-add-seq";
    const selects = [];
    for (let i = 0; i < n; i++) {
      const sel = document.createElement("select");
      for (const v of [0, 5, 6, 7]) {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = v;
        sel.appendChild(o);
      }
      selects.push(sel);
      addRow.appendChild(sel);
    }
    const addBtn = document.createElement("button");
    addBtn.textContent = "+ Ajouter";
    addBtn.addEventListener("click", () => {
      const sequence = selects.map((s) => parseInt(s.value, 10));
      addSequence(n, sequence);
    });
    addRow.appendChild(addBtn);
    sec.appendChild(addRow);

    return sec;
  }

  async function addSequence(cycleSize, sequence) {
    try {
      await apiSend(
        `/api/designer/neighbor-tables/${state.current.id}/sequences`, "POST",
        { cycle_size: cycleSize, sequence }
      );
      // Re-fetch le detail complet (inclut n_jobs_using, absent de la
      // reponse POST/DELETE sequences) plutot que de le bricoler localement.
      state.current = await apiGet(`/api/designer/neighbor-tables/${state.current.id}`);
      await loadTables();
      renderTablesList();
      renderEditor();
    } catch (e) {
      alert(`Erreur : ${e.message}`);
    }
  }

  async function removeSequence(cycleSize, sequence) {
    try {
      const r = await fetch(`/api/designer/neighbor-tables/${state.current.id}/sequences`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cycle_size: cycleSize, sequence }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      state.current = await apiGet(`/api/designer/neighbor-tables/${state.current.id}`);
      await loadTables();
      renderTablesList();
      renderEditor();
    } catch (e) {
      alert(`Erreur : ${e.message}`);
    }
  }

  async function deleteTable(t) {
    if (!confirm(`Supprimer la table "${t.name}" ?\n\nCette action est irreversible.`)) return;
    try {
      await apiSend(`/api/designer/neighbor-tables/${t.id}`, "DELETE");
    } catch (e) {
      if (e.status === 409) {
        // Table deja utilisee par des jobs : reconfirmer explicitement
        if (confirm(`${e.message}\n\nConfirmer la suppression definitive ?`)) {
          try {
            await apiSend(`/api/designer/neighbor-tables/${t.id}`, "DELETE", { confirm: true });
          } catch (e2) {
            alert(`Erreur : ${e2.message}`);
            return;
          }
        } else {
          return;
        }
      } else {
        alert(`Erreur : ${e.message}`);
        return;
      }
    }
    state.selectedId = null;
    state.current = null;
    $("#ntb-content").innerHTML = '<div class="ntb-empty">Selectionnez une table a gauche, ou creez-en une nouvelle.</div>';
    await loadTables();
  }

  // ===== Modal creation (duplication) =====
  function openNewTableModal(preselectSourceId) {
    const sel = $("#new-table-source");
    sel.innerHTML = "";
    for (const t of state.tables) {
      const o = document.createElement("option");
      o.value = t.id;
      o.textContent = t.name + (t.is_default ? " (par defaut)" : "");
      if (t.id === (preselectSourceId || state.selectedId)) o.selected = true;
      sel.appendChild(o);
    }
    $("#new-table-name").value = "";
    $("#new-table-modal").classList.remove("hidden");
    $("#new-table-name").focus();
  }
  function closeNewTableModal() {
    $("#new-table-modal").classList.add("hidden");
  }
  async function saveNewTable() {
    const name = $("#new-table-name").value.trim();
    if (!name) { alert("Le nom est requis."); return; }
    const sourceId = $("#new-table-source").value;
    try {
      const created = await apiSend("/api/designer/neighbor-tables", "POST",
        { source_id: sourceId, name });
      closeNewTableModal();
      await loadTables();
      await selectTable(created.id);
    } catch (e) {
      alert(`Erreur : ${e.message}`);
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // ===== Boot =====
  function init() {
    $("#btn-new-table").addEventListener("click", () => openNewTableModal(null));
    $("#new-table-cancel").addEventListener("click", closeNewTableModal);
    $("#new-table-save").addEventListener("click", saveNewTable);
    $("#new-table-modal").addEventListener("click", (ev) => {
      if (ev.target.id === "new-table-modal") closeNewTableModal();
    });

    loadTables();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
