/**
 * Живое заполнение «Наименование» по правилам Product._composed_goods_full_name()
 * (товар: первый материал, первая операция, длина×ширина [×толщина] мм).
 * Логика прилагательного — как в core.models.operation_type_name_to_result_adjective.
 */
(function () {
  "use strict";

  var EXACT_ADJ = {
    шлифование: "шлифованный",
    покраска: "окрашенный",
    лакировка: "лакированный",
    сверление: "сверлёный",
    резка: "резаный",
    раскрой: "раскроенный",
    фрезеровка: "фрезерованный",
    тиснение: "тиснёный",
    сушка: "высушенный",
    склейка: "склеенный",
  };

  function operationNameToAdjective(name) {
    var n = (name || "").trim();
    if (!n) return "";
    var low = n.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(EXACT_ADJ, low)) return EXACT_ADJ[low];
    if (low.length > 4 && low.slice(-2) === "ние") return low.slice(0, -2) + "ный";
    return n;
  }

  function loadOperationMap() {
    var el = document.getElementById("product-operation-types-data");
    if (!el || !el.textContent) return {};
    try {
      var rows = JSON.parse(el.textContent);
      var map = {};
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        map[String(r.id)] = {
          name: r.name || "",
          result_adjective: (r.result_adjective || "").trim(),
        };
      }
      return map;
    } catch (e) {
      return {};
    }
  }

  function isRowDeleted(control) {
    var tr = control.closest("tr");
    if (!tr) return false;
    var del = tr.querySelector('input[name$="-DELETE"]');
    return !!(del && del.checked);
  }

  function orderedSelects(fieldsetSelector, nameEndsWith) {
    var fs = document.querySelector(fieldsetSelector);
    if (!fs) return [];
    var sel = 'select[name$="-' + nameEndsWith + '"]';
    return Array.prototype.slice
      .call(fs.querySelectorAll(sel))
      .filter(function (el) {
        if (!el.name || el.name.indexOf("__prefix__") !== -1) return false;
        if (isRowDeleted(el)) return false;
        var m = el.name.match(/-(\d+)-/);
        el._ord = m ? parseInt(m[1], 10) : 999;
        return true;
      })
      .sort(function (a, b) {
        return a._ord - b._ord;
      });
  }

  function selectedOptionText(sel) {
    if (!sel || !sel.value) return "";
    var idx = sel.selectedIndex;
    if (idx < 0) return "";
    return String(sel.options[idx].text || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parseMm(el) {
    if (!el || el.value === "") return null;
    var n = parseFloat(String(el.value).replace(",", "."));
    if (!isFinite(n) || n <= 0) return null;
    return Math.round(n);
  }

  function composeName(opMap) {
    var kindEl = document.getElementById("id_product_kind");
    if (!kindEl || kindEl.value !== "goods") return null;

    var matSels = orderedSelects("fieldset.product-extra-inline--materials", "material");
    var mat = "";
    for (var i = 0; i < matSels.length; i++) {
      var mt = selectedOptionText(matSels[i]);
      if (mt) {
        mat = mt;
        break;
      }
    }

    var opSels = orderedSelects("fieldset.product-extra-inline--labor", "operation_type");
    var adj = "";
    for (var j = 0; j < opSels.length; j++) {
      var sel = opSels[j];
      var sid = sel.value;
      if (!sid) continue;
      var meta = opMap[sid] || {};
      var optText = selectedOptionText(sel);
      var oname = (meta.name || optText || "").trim();
      adj = (meta.result_adjective || "").trim();
      if (!adj) adj = operationNameToAdjective(oname);
      if (!adj) adj = oname;
      if (adj) break;
    }

    if (!mat || !adj) return null;

    var len = parseMm(document.getElementById("id_sheet_length_mm"));
    var wid = parseMm(document.getElementById("id_sheet_width_mm"));
    if (len === null || wid === null) return null;

    var ts = parseMm(document.getElementById("id_sheet_thickness_mm"));
    var parts = [mat, adj, len + "×" + wid];
    if (ts !== null) parts.push(String(ts));
    parts.push("мм");
    var s = parts.join(" ");
    return s.length > 255 ? s.slice(0, 255) : s;
  }

  var opMapCache = null;

  function refresh() {
    var nameEl = document.getElementById("id_name");
    if (!nameEl) return;
    if (opMapCache === null) opMapCache = loadOperationMap();
    var s = composeName(opMapCache);
    if (s) nameEl.value = s;
  }

  function bumpOpMap() {
    opMapCache = null;
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var form = document.getElementById("product_form");
    if (!form) return;

    refresh();

    form.addEventListener(
      "input",
      function (e) {
        var t = e.target;
        if (!t || !t.id) return;
        if (
          t.id === "id_sheet_length_mm" ||
          t.id === "id_sheet_width_mm" ||
          t.id === "id_sheet_thickness_mm"
        )
          refresh();
      },
      true
    );

    form.addEventListener(
      "change",
      function (e) {
        var t = e.target;
        if (!t) return;
        var n = t.name || "";
        if (t.id === "id_product_kind") {
          bumpOpMap();
          refresh();
          return;
        }
        if (n.slice(-8) === "-DELETE") {
          refresh();
          return;
        }
        if (n.indexOf("materials-") === 0 && n.indexOf("-material") !== -1) {
          refresh();
          return;
        }
        if (n.indexOf("labor_norms-") === 0 && n.indexOf("-operation_type") !== -1) {
          refresh();
          return;
        }
      },
      true
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
