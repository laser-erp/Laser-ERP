/**
 * Регулировка ширины левого блока карточки товара (перетаскивание правой границы).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "product_card_sidebar_width_px";
  var MIN_W = 200;
  var MAX_W = 720;
  var DEFAULT_REM = 22;

  function getLayout() {
    return document.querySelector("form#product_form .product-card-layout");
  }

  function parsePx(s) {
    var n = parseInt(s, 10);
    return isFinite(n) ? n : null;
  }

  function clamp(w) {
    var max = Math.min(MAX_W, Math.floor(window.innerWidth * 0.55));
    if (max < MIN_W) max = MIN_W;
    return Math.max(MIN_W, Math.min(max, w));
  }

  function applyWidth(layout, px) {
    if (!layout) return;
    var w = clamp(px);
    layout.style.setProperty("--product-sidebar-width", w + "px");
    try {
      localStorage.setItem(STORAGE_KEY, String(w));
    } catch (e) {
      /* ignore */
    }
  }

  function loadSaved(layout) {
    var remPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    var def = Math.round(DEFAULT_REM * remPx);
    var saved = null;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      /* ignore */
    }
    var px = parsePx(saved);
    if (px == null) px = def;
    applyWidth(layout, px);
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var layout = getLayout();
    if (!layout) return;
    var resizer = layout.querySelector(".product-card-resizer");
    if (!resizer) return;

    loadSaved(layout);

    var dragging = false;
    var startX = 0;
    var startW = 0;

    function onMove(e) {
      if (!dragging) return;
      var dx = e.clientX - startX;
      applyWidth(layout, startW + dx);
      e.preventDefault();
    }

    function onUp() {
      if (!dragging) return;
      dragging = false;
      resizer.classList.remove("is-dragging");
      document.body.classList.remove("product-card-resize-active");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove, { passive: false });
      document.removeEventListener("touchend", onUp);
    }

    resizer.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return;
      var sidebar = layout.querySelector(".product-card-sidebar");
      if (!sidebar) return;
      dragging = true;
      startX = e.clientX;
      startW = sidebar.getBoundingClientRect().width;
      resizer.classList.add("is-dragging");
      document.body.classList.add("product-card-resize-active");
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      e.preventDefault();
    });

    resizer.addEventListener("touchstart", function (e) {
      if (!e.touches || e.touches.length !== 1) return;
      var sidebar = layout.querySelector(".product-card-sidebar");
      if (!sidebar) return;
      dragging = true;
      startX = e.touches[0].clientX;
      startW = sidebar.getBoundingClientRect().width;
      resizer.classList.add("is-dragging");
      document.body.classList.add("product-card-resize-active");
      document.addEventListener("touchmove", onMove, { passive: false });
      document.addEventListener("touchend", onUp);
      e.preventDefault();
    });

    resizer.addEventListener("keydown", function (e) {
      var sidebar = layout.querySelector(".product-card-sidebar");
      if (!sidebar) return;
      var w = sidebar.getBoundingClientRect().width;
      if (e.key === "ArrowLeft") {
        applyWidth(layout, w - 12);
        e.preventDefault();
      } else if (e.key === "ArrowRight") {
        applyWidth(layout, w + 12);
        e.preventDefault();
      } else if (e.key === "Home") {
        applyWidth(layout, MIN_W);
        e.preventDefault();
      } else if (e.key === "End") {
        applyWidth(layout, Math.min(MAX_W, Math.floor(window.innerWidth * 0.55)));
        e.preventDefault();
      }
    });

    window.addEventListener(
      "resize",
      function () {
        var sidebar = layout.querySelector(".product-card-sidebar");
        if (!sidebar) return;
        applyWidth(layout, sidebar.getBoundingClientRect().width);
      },
      { passive: true }
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
