/* =========================================================================
   report.js -- Navigation et lignes depliables du rapport.
   Pur JS, pas de substitution Python.
   ========================================================================= */

(function () {
  'use strict';

  /* Deplie / replie la ligne detail associee a un h donne.
     Expose en global car appele via onclick inline dans le HTML. */
  function toggleDetail(id) {
    var row = document.getElementById('detail-' + id);
    var chev = document.getElementById('chev-' + id);
    if (!row) return;
    if (row.style.display === 'none') {
      row.style.display = 'table-row';
      if (chev) chev.innerHTML = '&#9660;';
    } else {
      row.style.display = 'none';
      if (chev) chev.innerHTML = '&#9654;';
    }
  }
  window.toggleDetail = toggleDetail;

  /* Smooth scroll sur les liens de nav */
  document.querySelectorAll('.nav-bar a').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      var target = document.querySelector(this.getAttribute('href'));
      if (target) target.scrollIntoView({ behavior: 'smooth' });
    });
  });

  /* Highlight du lien nav correspondant a la section visible.
     rootMargin fait en sorte qu'une section n'est "active" que lorsqu'elle
     occupe ~30% haut du viewport (pas au premier pixel visible). */
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        document.querySelectorAll('.nav-bar a').forEach(function (a) {
          a.classList.toggle('active', a.getAttribute('href') === '#' + entry.target.id);
        });
      }
    });
  }, { rootMargin: '-20% 0px -70% 0px' });
  document.querySelectorAll('section[id]').forEach(function (s) { observer.observe(s); });
})();
