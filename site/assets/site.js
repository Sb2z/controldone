/* ControlDOne, site public : améliorations progressives.
   Tout le contenu est lisible sans ce script. Il ajoute le mouvement (bibliothèque Motion, servie par ce site :
   assets/vendor/motion.min.js, licence MIT) et le calculateur de seuil de la page Tarifs.
   Il n'envoie rien, n'enregistre rien et ne lit aucun cookie. Si l'utilisateur a demandé moins d'animations
   (prefers-reduced-motion), aucun déplacement n'est joué : les valeurs finales s'affichent directement. */
(function () {
  "use strict";
  var doc = document;
  var racine = doc.documentElement;
  var M = window.Motion || null;
  var reduit = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var anime = !!M && !reduit;
  var ANGLAIS = racine.lang === "en";
  var LOCALE = ANGLAIS ? "en-GB" : "fr-FR";
  var EASE = [0.16, 1, 0.3, 1];
  var D = { micro: 0.12, court: 0.2, moyen: 0.28, section: 0.4 };

  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }
  function $(sel, ctx) { return (ctx || doc).querySelector(sel); }
  function dansLaVue(el) {
    var r = el.getBoundingClientRect();
    return r.top < window.innerHeight && r.bottom > 0;
  }

  /* --- 7. En-tête qui se condense après 80 px de défilement ------------------------------------------------- */
  function entete() {
    var h = $(".site-header");
    if (!h) { return; }
    var etat = null;
    function maj() {
      var c = window.scrollY > 80;
      if (c !== etat) { etat = c; h.classList.toggle("is-condensed", c); }
    }
    maj();
    window.addEventListener("scroll", maj, { passive: true });
  }

  /* --- 8. Barre de lecture sur les pages longues ----------------------------------------------------------- */
  function barreDeLecture() {
    if (!anime || !doc.body.hasAttribute("data-lecture")) { return; }
    var b = doc.createElement("div");
    b.className = "progress";
    b.setAttribute("aria-hidden", "true");
    doc.body.appendChild(b);
    M.scroll(M.animate(b, { scaleX: [0, 1] }, { ease: "linear" }));
  }

  /* --- 3 et 4. Révélation des blocs au défilement, en cascade dans un même groupe, une seule fois ----------- */
  var REVELER = ".section-head, .ledger li, .card, .measure, .fact, .price, .commission, .founder, .faq details, " +
    ".split > *, .shot, .frame, .steps li, .calc, .offer, .table-wrap";
  function revelations() {
    if (!anime) { return; }
    $$(REVELER).forEach(function (el) {
      if (el.closest(".hero") || el.closest(".cmp.is-playing") || dansLaVue(el)) { return; }
      if (el.parentElement && el.parentElement.closest(REVELER)) { return; }   // un seul niveau animé
      var freres = el.parentElement ? $$(":scope > *", el.parentElement) : [];
      var rang = Math.max(0, freres.indexOf(el));
      el.style.opacity = "0";
      M.inView(el, function () {
        M.animate(el, { opacity: [0, 1], y: [12, 0] },
          { duration: D.section, ease: EASE, delay: Math.min(rang, 6) * 0.05 });
      }, { amount: 0.2 });
    });
  }

  /* --- 2. Compteurs : la valeur exacte affichée dans la page est la valeur d'arrivée ------------------------ */
  function compteurs() {
    $$("[data-count]").forEach(function (el) {
      var fin = el.textContent;
      var valeur = parseFloat(el.getAttribute("data-count"));
      var dec = parseInt(el.getAttribute("data-decimals") || "0", 10);
      var suffixe = el.getAttribute("data-suffix") || "";
      var prefixe = el.getAttribute("data-prefix") || "";
      var retard = parseFloat(el.getAttribute("data-delay") || "0");
      if (!anime || !isFinite(valeur) || valeur === 0) { return; }
      // Haut de page : si le script arrive tard, on laisse la valeur finale plutôt que de la faire clignoter.
      if (retard && window.performance && performance.now() > retard * 1000 - 150) { return; }
      var fmt = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: dec, maximumFractionDigits: dec });
      el.setAttribute("aria-label", fin.replace(/\s+/g, " ").trim());
      el.textContent = prefixe + fmt.format(0) + suffixe;
      function lancer() {
        M.animate(0, valeur, {
          duration: Math.min(1.2, 0.5 + Math.log10(valeur + 1) * 0.15), ease: EASE, delay: retard,
          onUpdate: function (v) { el.textContent = prefixe + fmt.format(v) + suffixe; },
          onComplete: function () { el.textContent = fin; }
        });
      }
      if (retard) { lancer(); } else { M.inView(el, lancer, { amount: 0.6 }); }
    });
  }

  /* --- 6. Fil des étapes qui se trace au défilement --------------------------------------------------------- */
  function filDesEtapes() {
    if (!anime) { return; }
    $$(".steps").forEach(function (liste) {
      var fil = doc.createElement("span");
      fil.className = "fil";
      fil.setAttribute("aria-hidden", "true");
      liste.appendChild(fil);
      M.scroll(M.animate(fil, { scaleY: [0, 1] }, { ease: "linear" }),
        { target: liste, offset: ["start 75%", "end 55%"] });
    });
  }

  /* --- Démonstration du rapprochement : ligne de facture contre ligne de déclaration ---------------------- */
  function rapprochement() {
    var bloc = $(".cmp");
    if (!bloc || !anime) { return; }   // sans script ou mouvement réduit : état final, statique
    var lignes = $$(".cmp-row", bloc);
    var total = $(".cmp-total", bloc);
    var etapes = lignes.concat(total ? [total] : []);
    var jalons = $$(".cmp-steps span", bloc);
    var actuel = -1;
    function montrer(n) {
      if (n === actuel) { return; }
      actuel = n;
      etapes.forEach(function (el, i) { el.classList.toggle("on", i < n); });
      jalons.forEach(function (j, i) { j.classList.toggle("on", i < n); });
    }
    bloc.classList.add("is-playing");
    montrer(0);
    var large = window.matchMedia("(min-width: 900px) and (min-height: 640px)").matches;
    if (large) {
      // Écran large : la scène reste fixe et chaque palier de défilement révèle une comparaison.
      bloc.classList.add("is-scrolly");
      M.scroll(function (p) {
        montrer(Math.min(etapes.length, Math.floor(p * (etapes.length + 0.6))));
      }, { target: bloc, offset: ["start start", "end end"] });
    } else {
      // Téléphone : la séquence se joue une fois à l'entrée dans la vue (moins de cinq secondes).
      M.inView(bloc, function () {
        etapes.forEach(function (_e, i) { setTimeout(function () { montrer(i + 1); }, 350 + i * 650); });
      }, { amount: 0.35 });
    }
  }

  /* --- Appel à l'action collant sur téléphone --------------------------------------------------------------- */
  function ctaCollant() {
    var source = $("[data-cta-principal]");
    if (!source || !("IntersectionObserver" in window)) { return; }
    var barre = doc.createElement("div");
    barre.className = "cta-sticky";
    var texte = doc.createElement("span");
    texte.textContent = source.getAttribute("data-cta-texte") || "";
    var lien = doc.createElement("a");
    lien.className = "btn btn-primary";
    lien.href = source.getAttribute("href");
    lien.textContent = source.textContent.replace(/\s+/g, " ").replace("→", "").trim();
    lien.tabIndex = -1;
    barre.appendChild(texte);
    barre.appendChild(lien);
    barre.setAttribute("aria-hidden", "true");
    doc.body.appendChild(barre);
    var sourceVisible = true, finVisible = false;
    function maj() {
      var v = !sourceVisible && !finVisible && source.getBoundingClientRect().top < 0;
      barre.classList.toggle("is-visible", v);
      barre.setAttribute("aria-hidden", v ? "false" : "true");
      lien.tabIndex = v ? 0 : -1;
    }
    new IntersectionObserver(function (e) { sourceVisible = e[0].isIntersecting; maj(); }).observe(source);
    var fin = $(".offer") || $(".site-footer");
    if (fin) { new IntersectionObserver(function (e) { finVisible = e[0].isIntersecting; maj(); }).observe(fin); }
  }

  /* --- FAQ : ouverture et fermeture adoucies (opacité et translation du contenu) ----------------------------- */
  function faq() {
    if (!anime) { return; }
    $$(".faq details").forEach(function (d) {
      var s = $("summary", d), rep = $(".rep", d);
      if (!s || !rep) { return; }
      s.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (!d.open) {
          d.open = true;
          M.animate(rep, { opacity: [0, 1], y: [-6, 0] }, { duration: D.moyen, ease: EASE });
        } else {
          M.animate(rep, { opacity: [1, 0], y: [0, -4] }, { duration: D.court, ease: [0.4, 0, 1, 1] })
            .then(function () { d.open = false; rep.style.opacity = ""; rep.style.transform = ""; });
        }
      });
    });
  }

  /* --- 9. Calculateur de seuil (Tarifs) : aucun taux d'erreur supposé, formule affichée -------------------- */
  var T = ANGLAIS ? {
    lot: "Files in the batch reviewed", an: "Import files per year",
    devis: "Above 150 files a month, the price is quoted on request. Write to me for a quote.",
    parDossier: "per file", formule: "Break-even = cost ÷ (1 − 0.20) = ", ht: " excl. VAT",
    solde: "Balance for you", sous: "below the break-even point", commission: "Commission (20 %)", cout: "Cost over the period",
    palier: function (p, q) { return "Monthly plan at €" + p + " excl. VAT (up to " + q + " files a month), 12 months"; },
    diag: "Diagnostic, paid once", offert: "Diagnostic offered (launch offer; the 20 % commission is still due)"
  } : {
    lot: "Dossiers dans le lot analysé", an: "Dossiers d'import par an",
    devis: "Au-delà de 150 dossiers par mois, le prix est établi sur devis. Écrivez-moi pour en recevoir un.",
    parDossier: "par dossier", formule: "Seuil = coût ÷ (1 − 0,20) = ", ht: " HT",
    solde: "Solde pour vous", sous: "en dessous du seuil", commission: "Commission (20 %)", cout: "Coût sur la période",
    palier: function (p, q) { return "Contrôle continu à " + p + " € HT par mois (jusqu'à " + q + " dossiers par mois), 12 mois"; },
    diag: "Diagnostic, payé une fois", offert: "Diagnostic offert (offre de lancement ; la commission de 20 % reste due)"
  };
  var PALIERS = [[20, 99], [60, 199], [150, 349]];
  var TAUX = 0.2;

  function euros(v) {
    var s = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(v));
    var signe = v < 0 ? "−" : "";
    return ANGLAIS ? signe + "€" + s : signe + s + " €";
  }
  function lireNombre(champ) {
    var t = (champ.value || "").replace(/[\s  ]/g, "").replace(",", ".");
    if (t === "") { return null; }
    var n = Number(t);
    return isFinite(n) && n >= 0 ? n : NaN;
  }

  /* Calcul pur, exposé pour vérification (aucune donnée envoyée). */
  function seuil(formule, dossiers) {
    var cout, palier = null;
    if (formule === "diagnostic") { cout = 390; }
    else if (formule === "offert") { cout = 0; }
    else {
      var parMois = Math.ceil((dossiers || 0) / 12);
      for (var i = 0; i < PALIERS.length; i++) { if (parMois <= PALIERS[i][0]) { palier = PALIERS[i]; break; } }
      if (!palier) { return { devis: true }; }
      cout = palier[1] * 12;
    }
    var s = cout / (1 - TAUX);
    return { cout: cout, seuil: s, parDossier: dossiers ? s / dossiers : null, palier: palier };
  }
  window.ControlDOneSeuil = seuil;

  function calculateur() {
    var bloc = $("#calc");
    if (!bloc) { return; }
    bloc.hidden = false;
    var fFormule = $("#calc-formule"), fDossiers = $("#calc-dossiers"), fAvoirs = $("#calc-credits");
    var lDossiers = $("label[for=calc-dossiers]"), sortie = $("#calc-seuil"), detail = $("#calc-detail"),
      formuleTxt = $("#calc-formule-txt"), parDossier = $("#calc-par-dossier"), hypothese = $("#calc-hypothese");
    var affiche = 0, enCours = null;

    function ecrireSeuil(v) {
      if (!anime) { sortie.textContent = euros(v) + T.ht; affiche = v; return; }
      if (enCours) { enCours.stop(); }
      enCours = M.animate(affiche, v, {
        type: "spring", visualDuration: 0.3, bounce: 0,
        onUpdate: function (x) { affiche = x; sortie.textContent = euros(x) + T.ht; },
        onComplete: function () { affiche = v; sortie.textContent = euros(v) + T.ht; }
      });
    }
    function maj() {
      var formule = fFormule.value;
      lDossiers.textContent = formule === "continu" ? T.an : T.lot;
      var n = lireNombre(fDossiers);
      if (n !== null && isNaN(n)) { n = null; }
      var r = seuil(formule, n);
      detail.textContent = "";
      hypothese.hidden = true;
      if (r.devis) {
        sortie.textContent = "…";
        formuleTxt.textContent = T.devis;
        parDossier.textContent = "";
        return;
      }
      ecrireSeuil(r.seuil);
      var libelle = formule === "diagnostic" ? T.diag : formule === "offert" ? T.offert : T.palier(r.palier[1], r.palier[0]);
      formuleTxt.textContent = libelle + ". " + T.formule + euros(r.cout).replace(/ €$/, "") +
        (ANGLAIS ? " ÷ 0.8 = " : " ÷ 0,8 = ") + euros(r.seuil) + T.ht + ".";
      parDossier.textContent = r.parDossier ? euros(r.parDossier) + T.ht + " " + T.parDossier : "";
      var a = lireNombre(fAvoirs);
      if (a !== null && !isNaN(a)) {
        var com = a * TAUX, solde = a - com - r.cout;
        hypothese.hidden = false;
        detail.innerHTML = "";
        [[T.cout, euros(r.cout)], [T.commission, euros(com)], [T.solde, euros(solde) + (solde < 0 ? " (" + T.sous + ")" : "")]]
          .forEach(function (l) {
            var dt = doc.createElement("dt"), dd = doc.createElement("dd");
            dt.textContent = l[0]; dd.textContent = l[1];
            detail.appendChild(dt); detail.appendChild(dd);
          });
      }
    }
    [fFormule, fDossiers, fAvoirs].forEach(function (c) { c.addEventListener("input", maj); c.addEventListener("change", maj); });
    maj();
  }

  function demarrer() {
    entete();
    barreDeLecture();
    rapprochement();
    revelations();
    compteurs();
    filDesEtapes();
    ctaCollant();
    faq();
    calculateur();
  }
  if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", demarrer); } else { demarrer(); }
})();
