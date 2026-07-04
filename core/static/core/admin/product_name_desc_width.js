/**
 * Ширина textarea «Описание» = ширине поля «Наименование» (и следует за autosize имени).
 */
(function () {
  "use strict";

  function syncDescriptionWidthToName() {
    var nameEl = document.getElementById("id_name");
    var descEl = document.getElementById("id_description");
    if (!nameEl || !descEl) return;

    var w = nameEl.getBoundingClientRect().width;
    var fs = parseFloat(getComputedStyle(descEl).fontSize) || 14;
    var minW = fs * 20;

    descEl.style.boxSizing = "border-box";
    descEl.style.width = Math.max(w, minW) + "px";
    descEl.style.maxWidth = "100%";
  }

  function bind() {
    var nameEl = document.getElementById("id_name");
    if (nameEl && typeof ResizeObserver !== "undefined") {
      var ro = new ResizeObserver(syncDescriptionWidthToName);
      ro.observe(nameEl);
    }
    window.addEventListener("resize", syncDescriptionWidthToName);
  }

  function start() {
    bind();
    syncDescriptionWidthToName();
    requestAnimationFrame(function () {
      requestAnimationFrame(syncDescriptionWidthToName);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
