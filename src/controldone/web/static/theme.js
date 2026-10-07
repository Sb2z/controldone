/* Chargé de façon synchrone dans <head> (fichier externe : la CSP interdit tout script en ligne).
   Applique le thème choisi avant le premier affichage et prépare les animations d'entrée (seulement si le
   système n'a pas demandé de réduire les animations). */
(function () {
  "use strict";
  var racine = document.documentElement;
  try {
    var t = window.localStorage.getItem("cd-theme");
    if (t === "clair" || t === "sombre") { racine.setAttribute("data-theme", t); }
  } catch (e) { /* stockage indisponible : thème du système */ }
  racine.classList.add("js");
  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduit && window.Promise) { racine.classList.add("anime"); }
})();
