/**
 * Page d'accueil (hub) : detecte si des datasets sont disponibles
 * (mode normal) ou non (mode --designer-only, cf. viewer/server.py) pour
 * adapter la carte "Explorateur de corpus" en consequence. Best-effort :
 * en cas d'erreur reseau, la carte reste affichee normalement (le clic
 * menera a une page vide mais explicite plutot que de cacher la carte
 * a tort sur un faux negatif).
 */
(function () {
  "use strict";

  async function checkDatasets() {
    try {
      const r = await fetch("/api/datasets");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const datasets = data.datasets || [];
      if (datasets.length === 0) {
        markExplorerEmpty();
      }
    } catch (e) {
      // Mode designer-only : /api/datasets peut renvoyer une erreur
      // (table 'configs' absente). Meme traitement qu'une liste vide.
      markExplorerEmpty();
    }
  }

  function markExplorerEmpty() {
    const card = document.getElementById("card-explorer");
    const desc = document.getElementById("explorer-desc");
    if (card) card.classList.add("hub-card-empty");
    if (desc) desc.textContent = "Aucune donnee disponible dans cette installation (mode designer).";
  }

  checkDatasets();
})();
