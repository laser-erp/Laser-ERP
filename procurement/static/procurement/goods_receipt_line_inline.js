/**
 * Приёмка: подстановка ед. изм. из справочника материала/товара в строке.
 */
(function () {
  "use strict";

  function parseMap() {
    var el = document.getElementById("goods-receipt-unit-map");
    if (!el || !el.textContent) {
      return { materials: {}, products: {} };
    }
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return { materials: {}, products: {} };
    }
  }

  function setUnitCell(unitCell, unit) {
    if (!unitCell) return;
    var text = String(unit || "").trim();
    unitCell.textContent = text || "—";
  }

  function fetchMaterialUnit(materialId, unitCell) {
    fetch("/admin/core/material/tc-meta/" + materialId + "/")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        setUnitCell(unitCell, data.unit);
      })
      .catch(function () {
        setUnitCell(unitCell, "");
      });
  }

  function updateRowUnit(tr) {
    var map = parseMap();
    var unitCell = tr.querySelector("td.field-unit_display p");
    if (!unitCell) return;
    var mat = tr.querySelector('select[name$="-material"]');
    var prod = tr.querySelector('select[name$="-product"]');
    var mid = mat && mat.value ? String(mat.value) : "";
    var pid = prod && prod.value ? String(prod.value) : "";
    if (mid) {
      if (Object.prototype.hasOwnProperty.call(map.materials || {}, mid)) {
        setUnitCell(unitCell, map.materials[mid]);
      } else {
        fetchMaterialUnit(mid, unitCell);
      }
      return;
    }
    if (pid && map.products && Object.prototype.hasOwnProperty.call(map.products, pid)) {
      setUnitCell(unitCell, map.products[pid]);
      return;
    }
    setUnitCell(unitCell, "");
  }

  function bindTable(table) {
    if (!table || table.getAttribute("data-gr-unit-bound") === "1") return;
    table.setAttribute("data-gr-unit-bound", "1");
    table.querySelectorAll("tbody tr.form-row").forEach(updateRowUnit);
  }

  function init() {
    document.querySelectorAll(".inline-group table").forEach(bindTable);
  }

  document.addEventListener("change", function (e) {
    if (!e.target || !e.target.matches('select[name$="-material"], select[name$="-product"]')) {
      return;
    }
    var tr = e.target.closest("tr.form-row");
    if (tr) updateRowUnit(tr);
  });

  document.addEventListener("formset:added", function (ev) {
    var tr =
      (ev.target && ev.target.closest && ev.target.closest("tr.form-row")) ||
      (ev.target && ev.target.querySelector && ev.target.querySelector("tr.form-row"));
    if (tr) updateRowUnit(tr);
    init();
  });

  var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
  if (jq) {
    jq(document).on(
      "select2:select select2:clear select2:unselect change",
      'select[name$="-material"], select[name$="-product"]',
      function () {
        var tr = this.closest("tr.form-row");
        if (tr) updateRowUnit(tr);
      }
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  window.setTimeout(init, 300);
})();
