/**
 * Приёмка: ед. изм. из справочника; упаковки × содержимое и сумма → кол-во и цена за ед.
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

  function parseNum(el) {
    if (!el) return null;
    var raw = String(el.value || "").trim().replace(/\s/g, "").replace(",", ".");
    if (!raw) return null;
    var n = parseFloat(raw);
    return isFinite(n) ? n : null;
  }

  function formatQty(n) {
    if (n === null || n === undefined || !isFinite(n)) return "";
    var s = String(Math.round(n * 10000) / 10000);
    return s.replace(".", ",");
  }

  function formatMoney(n, digits) {
    if (n === null || n === undefined || !isFinite(n)) return "";
    var d = digits || 2;
    var f = Math.pow(10, d);
    var s = (Math.round(n * f) / f).toFixed(d);
    return s.replace(".", ",");
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
    var unitCell = tr.querySelector("td.field-unit_display p, td.field-unit_display .readonly, td.field-unit_display");
    if (!unitCell) return;
    var textTarget = unitCell.querySelector("p, .readonly") || unitCell;
    var mat = tr.querySelector('select[name$="-material"]');
    var prod = tr.querySelector('select[name$="-product"]');
    var mid = mat && mat.value ? String(mat.value) : "";
    var pid = prod && prod.value ? String(prod.value) : "";
    if (mid) {
      if (Object.prototype.hasOwnProperty.call(map.materials || {}, mid)) {
        setUnitCell(textTarget, map.materials[mid]);
      } else {
        fetchMaterialUnit(mid, textTarget);
      }
      return;
    }
    if (pid && map.products && Object.prototype.hasOwnProperty.call(map.products, pid)) {
      setUnitCell(textTarget, map.products[pid]);
      return;
    }
    setUnitCell(textTarget, "");
  }

  function field(tr, suffix) {
    return tr.querySelector('input[name$="-' + suffix + '"]');
  }

  function receiptLineRows() {
    var group =
      document.getElementById("lines-group") ||
      document.getElementById("goodsreceiptline_set-group");
    if (!group) return [];
    return group.querySelectorAll("tbody tr.form-row");
  }

  function recalcReceiptTotal() {
    var total = 0;
    receiptLineRows()
      .forEach(function (tr) {
        if (tr.classList.contains("empty-form")) return;
        var del = tr.querySelector('input[name$="-DELETE"]');
        if (del && del.checked) return;
        var qty = parseNum(field(tr, "quantity"));
        var price = parseNum(field(tr, "unit_price"));
        var amount = parseNum(field(tr, "amount"));
        if (qty !== null && price !== null) {
          total += qty * price;
        } else if (amount !== null) {
          total += amount;
        }
      });
    var totalEl = document.getElementById("id_total_amount");
    if (totalEl) {
      totalEl.value = formatMoney(total, 2);
    }
    var totalReadonly = document.querySelector(".field-total_amount .readonly");
    if (totalReadonly) {
      totalReadonly.textContent = formatMoney(total, 2);
    }
  }

  function recalcRow(tr, source) {
    var packEl = field(tr, "pack_count");
    var inPackEl = field(tr, "qty_in_pack");
    var qtyEl = field(tr, "quantity");
    var priceEl = field(tr, "unit_price");
    var amountEl = field(tr, "amount");
    if (!qtyEl || !priceEl || !amountEl) return;

    var pack = parseNum(packEl);
    var inPack = parseNum(inPackEl);
    if (inPack !== null && source !== "quantity") {
      if (pack === null) pack = 1;
      qtyEl.value = formatQty(pack * inPack);
    }

    var qty = parseNum(qtyEl);
    var price = parseNum(priceEl);
    var amount = parseNum(amountEl);
    var last = tr.getAttribute("data-gr-last") || "";

    if (source === "amount" || (last === "amount" && source !== "unit_price")) {
      if (qty !== null && qty !== 0 && amount !== null) {
        priceEl.value = formatMoney(amount / qty, 4);
      }
      recalcReceiptTotal();
      return;
    }
    if (source === "unit_price" || last === "unit_price") {
      if (qty !== null && price !== null) {
        amountEl.value = formatMoney(qty * price, 2);
      }
      recalcReceiptTotal();
      return;
    }
    if (qty !== null && amount !== null && (price === null || source === "pack_count" || source === "qty_in_pack" || source === "quantity")) {
      if (price === null || source === "pack_count" || source === "qty_in_pack") {
        priceEl.value = formatMoney(amount / qty, 4);
        recalcReceiptTotal();
        return;
      }
    }
    if (qty !== null && price !== null) {
      amountEl.value = formatMoney(qty * price, 2);
    }
    recalcReceiptTotal();
  }

  function bindRow(tr) {
    if (!tr || tr.getAttribute("data-gr-calc-bound") === "1") return;
    tr.setAttribute("data-gr-calc-bound", "1");
    [
      ["pack_count", "pack_count"],
      ["qty_in_pack", "qty_in_pack"],
      ["quantity", "quantity"],
      ["unit_price", "unit_price"],
      ["amount", "amount"],
    ].forEach(function (pair) {
      var el = field(tr, pair[0]);
      if (!el) return;
      el.addEventListener("input", function () {
        tr.setAttribute("data-gr-last", pair[1]);
        recalcRow(tr, pair[1]);
      });
      el.addEventListener("change", function () {
        tr.setAttribute("data-gr-last", pair[1]);
        recalcRow(tr, pair[1]);
      });
    });
  }

  function bindTable(table) {
    if (!table) return;
    table.querySelectorAll("tbody tr.form-row").forEach(function (tr) {
      updateRowUnit(tr);
      bindRow(tr);
    });
  }

  function init() {
    document.querySelectorAll(".inline-group table").forEach(bindTable);
    recalcReceiptTotal();
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
    if (tr) {
      updateRowUnit(tr);
      bindRow(tr);
    }
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

  document.addEventListener("fanera-nest:lines-filled", function () {
    receiptLineRows().forEach(function (tr) {
      updateRowUnit(tr);
      bindRow(tr);
      recalcRow(tr, "amount");
    });
    recalcReceiptTotal();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  window.setTimeout(init, 300);
})();
