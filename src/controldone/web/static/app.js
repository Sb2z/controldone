/* Améliorations progressives (l'interface fonctionne sans JavaScript). */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var cible = e.target.closest("[data-imprimer]");
    if (cible) { e.preventDefault(); window.print(); }
  });
  var depot = document.querySelector("form[data-depot]");
  if (depot) {
    var champ = depot.querySelector("input[type=file]");
    var resume = depot.querySelector("[data-resume]");
    champ.addEventListener("change", function () {
      var n = champ.files.length, total = 0;
      for (var i = 0; i < n; i++) { total += champ.files[i].size; }
      resume.textContent = n + " fichier(s) sélectionné(s), " + (total / 1048576).toFixed(1).replace(".", ",") + " Mo";
    });
    depot.addEventListener("submit", function () {
      var b = depot.querySelector("button[type=submit]");
      b.disabled = true; b.textContent = "Envoi en cours…";
    });
  }
  // Un motif est exigé : le navigateur le vérifie déjà (required) ; on évite le double envoi.
  document.querySelectorAll("form.decision").forEach(function (f) {
    f.addEventListener("submit", function () {
      var b = f.querySelector("button"); if (b) { setTimeout(function () { b.disabled = true; }, 0); }
    });
  });
})();
