/**
 * Предпросмотр площади листа в карточке материала (Д×Ш мм → м² / см² / мм²).
 * Итог на сервере: Material.save() → apply_sheet_geometry().
 */
(function () {
  "use strict";

  function parseNum(el) {
    if (!el || el.value === "" || el.value === null) return null;
    var n = parseFloat(String(el.value).replace(",", "."));
    return isFinite(n) ? n : null;
  }

  function roundMm(n) {
    if (n === null || n === undefined) return null;
    return Math.round(n);
  }

  function round2(x) {
    return Math.round(x * 100) / 100;
  }

  function round6(x) {
    return Math.round(x * 1e6) / 1e6;
  }

  function update() {
    var lenEl = document.getElementById("id_sheet_length_mm");
    var widEl = document.getElementById("id_sheet_width_mm");
    var preview = document.getElementById("material-sheet-area-preview");
    var areaEl = document.getElementById("id_area_m2");
    var cmEl = document.getElementById("id_sheet_area_cm2");
    var mmEl = document.getElementById("id_sheet_area_mm2");
    if (!preview) return;

    var L = roundMm(parseNum(lenEl));
    var W = roundMm(parseNum(widEl));
    if (L !== null && W !== null && L > 0 && W > 0) {
      var mm2 = L * W;
      var cm2 = round2(mm2 / 100);
      var m2 = round6(mm2 / 1000000);
      preview.textContent =
        String(m2).replace(".", ",") +
        " м² · " +
        String(cm2).replace(".", ",") +
        " см² · " +
        String(mm2) +
        " мм²";
      if (areaEl) areaEl.value = String(m2);
      if (cmEl) cmEl.value = String(cm2);
      if (mmEl) mmEl.value = String(mm2);
    } else {
      preview.textContent = "Задайте длину и ширину листа";
    }
  }

  function bind() {
    ["id_sheet_length_mm", "id_sheet_width_mm"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || el.getAttribute("data-mat-sheet-bound") === "1") return;
      el.setAttribute("data-mat-sheet-bound", "1");
      el.addEventListener("input", update);
      el.addEventListener("change", update);
    });
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
