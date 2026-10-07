/* ControlDOne : améliorations progressives de l'interface. Tout fonctionne sans JavaScript ; ce script ajoute
   les animations (bibliothèque Motion 14, servie localement : static/vendor/motion.min.js, licence MIT), la palette
   de commandes (Ctrl+K), le thème clair/sombre et la zone de dépôt par glisser-déposer.
   Vocabulaire du mouvement (D-5203) : 120, 200, 280 et 400 ms, décélération cubic-bezier(0.16, 1, 0.3, 1),
   ressorts sans rebond, transform et opacity seulement, aucune boucle, rien en mouvement réduit.
   Aucun contenu de document n'est interprété ici : le script ne lit que la structure de la page. */
(function () {
  "use strict";
  var racine = document.documentElement;
  var M = window.Motion || null;
  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var EASE = [0.16, 1, 0.3, 1];
  var D = { micro: 0.12, courte: 0.2, moyenne: 0.28, section: 0.4 };
  var RESSORT = { type: "spring", visualDuration: 0.3, bounce: 0 };
  var REVELER = ".titre-page, .fil, .bilan > *, .prochaine, .kpi, .carte, .constat, .ancres, .lien-dossier, .accueil-texte > *";

  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function bouge() { return !!(M && !reduit); }

  /* --- textes de l'interface dans la langue de la page (D-3803) : bloc JSON inerte produit par le serveur ----------- */
  var TEXTES = {};
  try {
    var blocTextes = document.getElementById("cd-textes");
    if (blocTextes) { TEXTES = JSON.parse(blocTextes.textContent || "{}") || {}; }
  } catch (e) { TEXTES = {}; }
  var ANGLAIS = racine.lang === "en";
  function T(cle, params) {
    var t = Object.prototype.hasOwnProperty.call(TEXTES, cle) ? TEXTES[cle] : cle;
    if (params) { Object.keys(params).forEach(function (k) { t = t.split("{" + k + "}").join(String(params[k])); }); }
    return t;
  }
  function anime(el, kf, opts) {
    if (bouge()) { return M.animate(el, kf, opts); }
    return null;
  }

  /* --- entrée de page : ce qui est visible arrive en cascade courte, le reste à son entrée dans la vue (une fois) ---- */
  function entrees() {
    var elements = $$(REVELER);
    racine.classList.remove("anime");
    if (!bouge()) { return; }
    var hauteur = window.innerHeight;
    var visibles = [], plus_bas = [];
    elements.forEach(function (el) {
      (el.getBoundingClientRect().top < hauteur * 1.02 ? visibles : plus_bas).push(el);
    });
    if (visibles.length) {
      visibles.forEach(function (el) { el.style.opacity = "0"; });
      visibles.forEach(function (el, i) {
        M.animate(el, { opacity: [0, 1], y: [12, 0] }, { duration: D.section, ease: EASE, delay: Math.min(i, 8) * 0.05 });
      });
    }
    plus_bas.forEach(function (el) {
      // Hors de l'écran : laissé visible (impression, captures, lecteurs) ; animé à son entrée dans la vue.
      M.inView(el, function () {
        M.animate(el, { opacity: [0, 1], y: [12, 0] }, { duration: D.section, ease: EASE });
      }, { margin: "0px 0px -6% 0px" });
    });
  }

  /* --- lignes des tableaux visibles au chargement : cascade de 30 ms ------------------------------------------------ */
  function lignes() {
    if (!bouge()) { return; }
    $$("table.donnees > tbody").forEach(function (tb) {
      if (tb.closest("details:not([open])") || tb.getBoundingClientRect().top > window.innerHeight) { return; }
      var rangs = $$(":scope > tr", tb).slice(0, 14);
      if (rangs.length < 2) { return; }
      rangs.forEach(function (r) { r.style.opacity = "0"; });
      M.animate(rangs, { opacity: [0, 1], y: [4, 0] }, { duration: D.moyenne, ease: EASE, delay: M.stagger(0.03, { startDelay: 0.12 }) });
    });
  }

  /* --- compteurs : les montants défilent une fois jusqu'à la valeur exacte affichée par le serveur ------------------- */
  var MOTIF_NOMBRE = ANGLAIS ? /^([^\d-]*)(-?[\d,]+)(?:\.(\d+))?(\s*(?:€|EUR|%)?)$/
    : /^([^\d-]*)(-?[\d   ]+)(?:,(\d+))?(\s*(?:€|EUR|%)?)$/;
  function compteurs() {
    if (!bouge()) { return; }
    $$(".kpi-val, [data-compteur]").forEach(function (bloc) {
      var cible = bloc.querySelector("a") || bloc;
      var texte = cible.textContent.trim();
      var m = MOTIF_NOMBRE.exec(texte);
      if (!m) { return; }
      var entier = parseInt(m[2].replace(/[,\s  ]/g, ""), 10);
      var decimales = m[3] ? m[3].length : 0;
      var valeur = entier + (decimales ? (entier < 0 ? -1 : 1) * parseInt(m[3], 10) / Math.pow(10, decimales) : 0);
      if (!isFinite(valeur) || valeur === 0) { return; }
      var fmt = new Intl.NumberFormat(ANGLAIS ? "en-GB" : "fr-FR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
      cible.textContent = m[1] + fmt.format(0) + m[4];
      M.inView(bloc, function () {
        M.animate(0, valeur, {
          duration: Math.min(0.9, 0.45 + Math.log10(Math.abs(valeur) + 1) * 0.08), ease: EASE,
          onUpdate: function (v) { cible.textContent = m[1] + fmt.format(v) + m[4]; },
          onComplete: function () { cible.textContent = texte; }
        });
      });
    });
  }

  /* --- barres de proportion ------------------------------------------------------------------------------------ */
  function barres() {
    if (!bouge()) { return; }
    $$(".barre > span, .jauge > span").forEach(function (b, i) {
      b.style.transform = "scaleX(0)";
      M.inView(b, function () {
        M.animate(b, { transform: ["scaleX(0)", "scaleX(1)"] }, { duration: 0.6, ease: EASE, delay: 0.1 + (i % 8) * 0.04 });
      });
    });
  }

  /* --- pastille de navigation qui glisse (ressort sans rebond) ---------------------------------------------------- */
  function pastille() {
    var nav = document.querySelector(".nav");
    var ul = nav && nav.querySelector("ul");
    if (!ul || !bouge()) { return; }
    var p = document.createElement("span");
    p.className = "pastille"; p.setAttribute("aria-hidden", "true");
    ul.appendChild(p);
    nav.classList.add("avec-pastille");
    var actif = ul.querySelector('a[aria-current="page"]');
    function place(a, instant) {
      if (!a) { M.animate(p, { opacity: 0 }, { duration: D.courte }); return; }
      var li = a.parentElement; // les <li> sont positionnés : offsetLeft du lien est relatif à son <li>
      var cible = { x: li.offsetLeft + a.offsetLeft, y: li.offsetTop + a.offsetTop, width: a.offsetWidth, height: a.offsetHeight, opacity: 1 };
      if (instant) {
        p.style.transform = "translate(" + cible.x + "px," + cible.y + "px)";
        p.style.width = cible.width + "px"; p.style.height = cible.height + "px"; p.style.opacity = 1;
        return;
      }
      M.animate(p, cible, RESSORT);
    }
    place(actif, true);
    // Les largeurs changent quand la police Inter est chargée : on recale la pastille.
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { place(actif, true); }); }
    if (window.ResizeObserver) { new ResizeObserver(function () { place(actif, true); }).observe(ul); }
    $$("a", ul).forEach(function (a) {
      a.addEventListener("pointerenter", function () { place(a); });
      a.addEventListener("focus", function () { place(a); });
    });
    ul.addEventListener("pointerleave", function () { place(actif); });
    window.addEventListener("resize", function () { place(actif, true); });
  }

  /* --- barre de lecture (pages longues seulement) ------------------------------------------------------------------- */
  function progression() {
    var b = document.querySelector(".progression");
    if (!b || !bouge() || document.documentElement.scrollHeight < window.innerHeight * 2.5) { return; }
    M.scroll(function (avance) { b.style.transform = "scaleX(" + avance + ")"; });
  }

  /* --- messages (confirmation, erreur) : arrivée douce et bouton pour les fermer --------------------------------------- */
  function messages() {
    $$(".page > .message").forEach(function (msg) {
      anime(msg, { opacity: [0, 1], y: [-8, 0] }, { duration: D.moyenne, ease: EASE });
      if (!msg.classList.contains("succes")) { return; }
      var b = document.createElement("button");
      b.type = "button"; b.className = "fermer"; b.setAttribute("aria-label", T("Fermer ce message"));
      var ns = "http://www.w3.org/2000/svg";
      var svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("aria-hidden", "true");
      var trait = document.createElementNS(ns, "path"); trait.setAttribute("d", "M4 4l8 8M12 4l-8 8");
      trait.setAttribute("stroke", "currentColor"); trait.setAttribute("stroke-width", "1.6"); trait.setAttribute("stroke-linecap", "round");
      svg.appendChild(trait); b.appendChild(svg);
      b.addEventListener("click", function () {
        var fin = function () { msg.remove(); };
        var a = anime(msg, { opacity: 0, y: -4 }, { duration: D.courte, ease: [0.4, 0, 1, 1] });
        if (a && a.finished) { a.finished.then(fin); } else { fin(); }
      });
      msg.appendChild(b);
    });
  }

  /* --- preuves d'un constat : le contenu révélé se pose en 280 ms ---------------------------------------------------- */
  function preuves() {
    $$("details.preuves-bloc, details.valeurs").forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (!d.open) { return; }
        var contenu = $$(":scope > :not(summary)", d);
        anime(contenu, { opacity: [0, 1], y: [-4, 0] }, { duration: D.moyenne, ease: EASE });
      });
    });
  }

  /* --- exemple de constat sur l'écran de connexion : les deux montants, puis le trait, puis l'écart (une fois) ---------- */
  function exemple() {
    var bloc = document.querySelector("[data-exemple]");
    if (!bloc || !bouge()) { return; }
    var valeurs = $$("[data-exemple-valeur]", bloc);
    var trait = bloc.querySelector(".exemple-trait");
    var ecart = $$("[data-exemple-ecart]", bloc);
    valeurs.concat(ecart).forEach(function (el) { el.style.opacity = "0"; });
    if (trait) { trait.style.transform = "scaleX(0)"; }
    var depart = 0.5;
    valeurs.forEach(function (el, i) {
      M.animate(el, { opacity: [0, 1], y: [6, 0] }, { duration: D.moyenne, ease: EASE, delay: depart + i * 0.12 });
    });
    var apres = depart + valeurs.length * 0.12 + 0.1;
    if (trait) { M.animate(trait, { transform: ["scaleX(0)", "scaleX(1)"] }, { duration: D.section, ease: EASE, delay: apres }); }
    ecart.forEach(function (el) {
      M.animate(el, { opacity: [0, 1], y: [6, 0] }, { duration: D.moyenne, ease: EASE, delay: apres + 0.25 });
    });
  }

  /* --- thème clair / sombre (dévoilement circulaire de 400 ms) --------------------------------------------------------- */
  function themeEffectif() {
    var t = racine.getAttribute("data-theme");
    if (t) { return t; }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "sombre" : "clair";
  }
  function basculerTheme(e) {
    var suivant = themeEffectif() === "clair" ? "sombre" : "clair";
    var appliquer = function () {
      racine.setAttribute("data-theme", suivant);
      try { window.localStorage.setItem("cd-theme", suivant); } catch (err) { /* sans mémoire */ }
    };
    if (!document.startViewTransition || reduit) { appliquer(); return; }
    var x = e && e.clientX ? e.clientX : window.innerWidth - 40, y = e && e.clientY ? e.clientY : 30;
    var rayon = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    racine.classList.add("bascule-theme");
    var t = document.startViewTransition(appliquer);
    t.ready.then(function () {
      racine.animate({ clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + rayon + "px at " + x + "px " + y + "px)"] },
        { duration: 400, easing: "cubic-bezier(0.16, 1, 0.3, 1)", pseudoElement: "::view-transition-new(root)" });
    });
    t.finished.finally(function () { racine.classList.remove("bascule-theme"); });
  }

  /* --- palette de commandes (Ctrl+K / ⌘K) --------------------------------------------------------------------------------- */
  function palette() {
    var dlg = document.querySelector("dialog[data-palette]");
    if (!dlg || typeof dlg.showModal !== "function") { return; }
    var champ = dlg.querySelector("input");
    var liste = dlg.querySelector("ul");
    var entrees = [];
    $$(".nav a").forEach(function (a) { entrees.push({ lib: a.textContent.trim(), aide: T("Aller à"), url: a.getAttribute("href") }); });
    $$(".ancres a").forEach(function (a) { entrees.push({ lib: a.textContent.trim(), aide: T("Sur cette page"), url: a.getAttribute("href") }); });
    $$(".carte-tete a.petit-lien, .carte h2 a.petit-lien").forEach(function (a) {
      var bloc = a.closest(".carte, .bandeau-alertes");
      var h = bloc && bloc.querySelector("h2");
      entrees.push({ lib: (h ? h.firstChild.textContent.trim() + " · " : "") + a.textContent.trim(), aide: T("Lien"), url: a.getAttribute("href") });
    });
    var moncompte = document.querySelector('.compte a[href="/compte"]');
    if (moncompte) { entrees.push({ lib: T("Mon compte"), aide: T("Compte"), url: moncompte.getAttribute("href") }); }
    var compte = document.querySelector('.compte a[href="/compte/mot-de-passe"]');
    if (compte) { entrees.push({ lib: T("Changer de mot de passe"), aide: T("Compte"), url: compte.getAttribute("href") }); }
    var sessions = document.querySelector('.compte a[href="/compte/sessions"]');
    if (sessions) { entrees.push({ lib: T("Mes sessions actives"), aide: T("Compte"), url: sessions.getAttribute("href") }); }
    entrees.push({ lib: T("Passer en thème clair ou sombre"), aide: T("Affichage"), action: function () { basculerTheme(); } });
    if (document.querySelector("[data-imprimer]")) { entrees.push({ lib: T("Imprimer cette page"), aide: T("Affichage"), action: function () { window.print(); } }); }
    var vues = [], sel = 0;

    function normaliser(s) { return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
    function rendre() {
      var q = normaliser(champ.value.trim());
      vues = entrees.filter(function (x) { return !q || normaliser(x.lib + " " + x.aide).indexOf(q) !== -1; });
      sel = Math.min(sel, Math.max(0, vues.length - 1));
      liste.textContent = "";
      if (!vues.length) {
        var vide = document.createElement("li"); vide.className = "rien"; vide.textContent = T("Aucun résultat");
        vide.setAttribute("role", "option"); vide.setAttribute("aria-disabled", "true");
        liste.appendChild(vide); return;
      }
      vues.forEach(function (x, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "none");
        var a = document.createElement("a");
        a.href = x.url || "#"; a.setAttribute("role", "option"); a.id = "pal-" + i;
        a.setAttribute("aria-selected", i === sel ? "true" : "false");
        var t = document.createElement("span"); t.textContent = x.lib;
        var s = document.createElement("small"); s.textContent = x.aide;
        a.appendChild(t); a.appendChild(s);
        a.addEventListener("click", function (e) { if (x.action) { e.preventDefault(); fermer(); x.action(); } });
        a.addEventListener("pointermove", function () { if (sel !== i) { sel = i; maj(); } });
        li.appendChild(a); liste.appendChild(li);
      });
      champ.setAttribute("aria-activedescendant", "pal-" + sel);
    }
    function maj() {
      $$("a[role=option]", liste).forEach(function (a, i) { a.setAttribute("aria-selected", i === sel ? "true" : "false"); });
      var a = liste.querySelector("#pal-" + sel);
      if (a) { a.scrollIntoView({ block: "nearest" }); champ.setAttribute("aria-activedescendant", a.id); }
    }
    function ouvrir() {
      champ.value = ""; sel = 0; rendre();
      dlg.showModal();
      anime(dlg, { opacity: [0, 1], scale: [0.98, 1], y: [-4, 0] }, { duration: D.courte, ease: EASE });
      champ.focus();
    }
    function fermer() { if (dlg.open) { dlg.close(); } }
    champ.addEventListener("input", function () { sel = 0; rendre(); });
    champ.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(vues.length - 1, sel + 1); maj(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); maj(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var x = vues[sel]; if (!x) { return; }
        fermer();
        if (x.action) { x.action(); } else { window.location.href = x.url; }
      }
    });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) { fermer(); } });
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); if (dlg.open) { fermer(); } else { ouvrir(); } }
    });
    $$("[data-palette-ouvrir]").forEach(function (b) { b.addEventListener("click", ouvrir); });
  }

  /* --- dépôt : glisser-déposer, liste des fichiers choisis, envoi ---------------------------------------------------------- */
  function depot() {
    var form = document.querySelector("form[data-depot]");
    if (!form) { return; }
    var champ = form.querySelector("input[type=file]");
    var zone = form.querySelector(".zone-depot");
    var resume = form.querySelector("[data-resume]");
    var liste = form.querySelector(".liste-fichiers");
    function taille(o) { var t = (o / 1048576).toFixed(1); return ANGLAIS ? t + " MB" : t.replace(".", ",") + " Mo"; }
    function afficher() {
      var n = champ.files.length, total = 0;
      for (var i = 0; i < n; i++) { total += champ.files[i].size; }
      resume.textContent = n ? T("{n} fichier(s) prêt(s) à envoyer, {taille}", { n: n, taille: taille(total) }) : "";
      if (zone) { zone.classList.toggle("rempli", n > 0); }
      if (liste) {
        liste.textContent = "";
        for (var j = 0; j < Math.min(n, 40); j++) {
          var li = document.createElement("li");
          var s = document.createElement("span"); s.textContent = champ.files[j].name;
          var em = document.createElement("em"); em.textContent = taille(champ.files[j].size);
          li.appendChild(s); li.appendChild(em); liste.appendChild(li);
        }
        if (n > 40) { var plus = document.createElement("li"); plus.textContent = T("+ {n} autre(s)", { n: n - 40 }); liste.appendChild(plus); }
        if (bouge() && n) {
          M.animate($$("li", liste), { opacity: [0, 1], y: [6, 0] }, { duration: D.moyenne, ease: EASE, delay: M.stagger(0.03) });
        }
      }
    }
    champ.addEventListener("change", afficher);
    if (zone) {
      ["dragenter", "dragover"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.add("survol"); }); });
      ["dragleave", "drop"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.remove("survol"); }); });
    }
    form.addEventListener("submit", function () {
      var b = form.querySelector("button[type=submit]");
      b.disabled = true; b.textContent = T("Envoi en cours…");
      if (resume && champ.files.length) {
        resume.textContent = T("Envoi de {n} fichier(s) en cours. Gardez cette page ouverte.", { n: champ.files.length });
      }
    });
  }


  /* --- suivi en direct du traitement d'un dépôt (D-3402) ------------------------------------------------------------------------
     Interroge le point JSON de la même origine (session, périmètre du client) ; seuls des codes d'état et des textes fixes sont
     affichés (textContent). Arrêt quand le traitement est fini, pause quand l'onglet est masqué, attente plus longue après 429. */
  function interroger(url, surDonnees, intervalle) {
    var essais = 0, minuterie = null, arrete = false;
    function suivant(delai) { if (!arrete) { minuterie = window.setTimeout(tour, delai); } }
    function tour() {
      if (document.hidden) { suivant(intervalle); return; }
      essais++;
      fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" }, cache: "no-store" })
        .then(function (r) {
          if (r.status === 429) { suivant(10000); return null; }
          if (!r.ok) { arrete = true; return null; }
          return r.json();
        })
        .then(function (d) {
          if (!d) { return; }
          if (surDonnees(d) === false) { arrete = true; return; }
          suivant(essais > 30 ? intervalle * 2.5 : intervalle);
        })
        .catch(function () { suivant(intervalle * 3); });
    }
    suivant(intervalle);
    return function () { arrete = true; if (minuterie) { window.clearTimeout(minuterie); } };
  }

  function suiviLot() {
    var bloc = document.querySelector("[data-suivi]");
    if (!bloc || bloc.getAttribute("data-suivi-fini") === "oui") { return; }
    var barre = bloc.querySelector("[data-suivi-barre]");
    var texte = bloc.querySelector("[data-suivi-texte]");
    var etapeAffichee = null;
    interroger(bloc.getAttribute("data-suivi"), function (d) {
      // rang, pourcentage et textes viennent du serveur (étapes fines du pipeline, D-3805 ; langue de la page)
      var etapes = $$("li[data-etape]", bloc);
      var rang = typeof d.rang === "number" ? d.rang : 0;
      if (d.erreur) { rang = etapes.length - 1; }
      etapes.forEach(function (li, i) {
        var fait = i < rang || (d.fini && !d.erreur);
        li.classList.toggle("fait", fait);
        li.classList.toggle("en-cours", !fait && i === rang);
        li.classList.toggle("a-venir", !fait && i > rang);
        li.classList.toggle("erreur", !!d.erreur && i === rang);
        if (!fait && i === rang && !d.fini) { li.setAttribute("aria-current", "step"); } else { li.removeAttribute("aria-current"); }
        var lib = li.querySelector(".suivi-lib");
        if (lib && d.erreur && i === rang) { lib.textContent = d.libelle || T("Erreur"); }
      });
      if (barre) {
        // la barre avance par transform (transition CSS de 400 ms) : la classe w-N porte l'échelle
        var pct = Math.max(0, Math.min(100, Math.round((d.pourcentage || 5) / 5) * 5));
        if (d.fini) { pct = 100; }
        barre.className = "w-" + pct;
      }
      bloc.classList.toggle("suivi-erreur", !!d.erreur);
      bloc.classList.toggle("suivi-fini", !!d.fini && !d.erreur);
      $$(".suivi-compteur", bloc).forEach(function (c) { c.textContent = ""; });
      var compteurEtape = bloc.querySelector("li.en-cours .suivi-compteur");
      if (compteurEtape && typeof d.fait === "number" && d.total) { compteurEtape.textContent = d.fait + "/" + d.total; }
      if (texte) {
        texte.textContent = d.fini && !d.erreur ? T("Traitement terminé. Les résultats s'affichent…") : (d.texte || "");
      }
      if (d.etape !== etapeAffichee) {
        etapeAffichee = d.etape;
        var actuelle = bloc.querySelector("li.en-cours .suivi-puce");
        if (actuelle) { anime(actuelle, { scale: [0.8, 1] }, RESSORT); }
      }
      if (d.fini) {
        var lien = document.querySelector("[data-rafraichir]");
        if (lien) { lien.remove(); }
        if (!d.erreur) { window.setTimeout(function () { window.location.reload(); }, reduit ? 300 : 1200); }
        return false;
      }
      return true;
    }, 2000);
  }

  function suiviListes() {
    $$("[data-suivi-liste]").forEach(function (liste) {
      var enCours = $$('[data-lot][data-fini="non"]', liste);
      if (!enCours.length) { return; }
      interroger(liste.getAttribute("data-suivi-liste"), function (d) {
        var restants = 0;
        (d.lots || []).forEach(function (l) {
          var b = null;
          $$("[data-lot]", liste).forEach(function (x) { if (x.getAttribute("data-lot") === l.lot_id) { b = x; } });
          if (!b) { return; }
          var avant = b.textContent;
          b.textContent = l.libelle;
          b.className = "badge " + (l.erreur ? "b-rejete" : (l.fini ? "b-valide" : "b-verifier en-cours"));
          b.setAttribute("data-fini", l.fini ? "oui" : "non");
          if (!l.fini) { restants++; }
          if (avant !== l.libelle) { anime(b, { opacity: [0.4, 1], scale: [0.96, 1] }, { duration: D.moyenne, ease: EASE }); }
        });
        return restants > 0;
      }, 4000);
    });
  }

  /* --- filtres des listes : résultats mis à jour pendant la saisie (amélioration ; sans script, le bouton « Filtrer » suffit) ----
     La page filtrée est demandée à la même adresse (GET, même origine) et reçue en document inerte (aucun script exécuté) ;
     seule la région [data-resultats] est remplacée par sa version produite et échappée par le serveur. */
  function filtresDirects() {
    if (!window.XMLHttpRequest || !window.history || !history.replaceState) { return; }
    $$("form[data-filtres]").forEach(function (form) {
      var annonce = document.createElement("p");
      annonce.className = "vh"; annonce.setAttribute("aria-live", "polite"); annonce.setAttribute("role", "status");
      form.appendChild(annonce);
      var minuterie = null, requete = null;
      function adresse() {
        var params = new URLSearchParams();
        $$("input, select", form).forEach(function (c) {
          if (!c.name || c.disabled || c.type === "submit") { return; }
          var v = (c.value || "").trim();
          if (v !== "" && !(c.name === "taille" && v === "25")) { params.append(c.name, v); }
        });
        var action = new URL(form.getAttribute("action") || window.location.pathname, window.location.href);
        var q = params.toString();
        return action.pathname + (q ? "?" + q : "");
      }
      function charger() {
        var url = adresse();
        var region = document.querySelector("[data-resultats]");
        if (!region) { return; }
        if (requete) { requete.abort(); }
        // XMLHttpRequest « document » : le navigateur analyse la réponse en document inerte, sans passer de
        // chaîne HTML à un point d'injection (compatible avec Trusted Types « trusted-types 'none' »).
        var xhr = new XMLHttpRequest();
        requete = xhr;
        xhr.open("GET", url);
        xhr.responseType = "document";
        xhr.setRequestHeader("Accept", "text/html");
        region.classList.add("charge");
        xhr.onload = function () {
          requete = null;
          var type = xhr.getResponseHeader("content-type") || "";
          var doc = xhr.response;
          var ok = xhr.status === 200 && type.indexOf("text/html") === 0 && doc &&
            new URL(xhr.responseURL, window.location.href).origin === window.location.origin;
          var neuve = ok ? doc.querySelector("[data-resultats]") : null;
          if (!neuve) { region.classList.remove("charge"); return; }
          var importee = document.importNode(neuve, true);
          region.replaceWith(importee);
          history.replaceState(null, "", url + (window.location.hash || ""));
          var compte = importee.querySelector("[data-compte]");
          annonce.textContent = compte ? compte.textContent.trim() : "";
          anime(importee, { opacity: [0.6, 1] }, { duration: D.courte, ease: EASE });
        };
        xhr.onerror = function () { requete = null; region.classList.remove("charge"); };
        xhr.send();
      }
      function plusTard() { window.clearTimeout(minuterie); minuterie = window.setTimeout(charger, 400); }
      $$("input[type=search], input:not([type])", form).forEach(function (c) { c.addEventListener("input", plusTard); });
      $$("select, input[type=date]", form).forEach(function (c) { c.addEventListener("change", plusTard); });
    });
  }


  /* --- graphiques : barres qui poussent à leur entrée dans la vue (le SVG final est celui du serveur) ---------------------------- */
  function graphes() {
    if (!bouge()) { return; }
    $$(".graphe").forEach(function (fig) {
      var rects = $$(".g-barre", fig);
      // seulement les graphiques visibles au chargement : plus bas, ils restent tels que rendus (captures, impression)
      if (!rects.length || fig.getBoundingClientRect().top > window.innerHeight) { return; }
      var axe = fig.classList.contains("graphe-colonnes") ? "scaleY" : "scaleX";
      rects.forEach(function (r) { r.style.transform = axe + "(0)"; });
      M.inView(fig, function () {
        M.animate(rects, { transform: [axe + "(0)", axe + "(1)"] }, { duration: 0.6, ease: EASE, delay: M.stagger(0.04) });
      });
    });
  }

  /* --- comportements existants ----------------------------------------------------------------------------------------------- */
  document.addEventListener("click", function (e) {
    var cible = e.target.closest("[data-imprimer]");
    if (cible) { e.preventDefault(); window.print(); }
    var t = e.target.closest("[data-theme-basculer]");
    if (t) { e.preventDefault(); basculerTheme(e); }
  });
  // Un motif est exigé : le navigateur le vérifie déjà (required) ; on évite le double envoi.
  // (délégation : vaut aussi pour les formulaires des résultats remplacés par les filtres directs)
  document.addEventListener("submit", function (e) {
    var f = e.target.closest && e.target.closest("form.decision");
    if (!f) { return; }
    var b = f.querySelector("button"); if (b) { setTimeout(function () { b.disabled = true; }, 0); }
  });

  function demarrer() {
    entrees(); lignes(); compteurs(); barres(); pastille(); progression(); messages(); preuves(); exemple(); palette(); depot();
    suiviLot(); suiviListes(); filtresDirects(); graphes();
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", demarrer); } else { demarrer(); }
})();
