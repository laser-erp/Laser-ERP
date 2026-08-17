/**
 * Калькулятор приёмки комплекта с листа 1525×1525 (фанера-piter).
 * Конфиг: JSON в #fanera-nest-kits-data
 * Заполнение строк: window.faneraNestReceiptFillLines(lines, meta)
 */
(function () {
  "use strict";

  var panelState = typeof WeakMap !== "undefined" ? new WeakMap() : null;
  var panelStateFallback = [];

  function parseConfig() {
    var el = document.getElementById("fanera-nest-kits-data");
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function fmtMoney(n, digits) {
    var d = digits == null ? 2 : digits;
    return Number(n).toFixed(d).replace(".", ",");
  }

  function fmtQty(n) {
    var v = Math.round(Number(n) * 10000) / 10000;
    return String(v).replace(".", ",");
  }

  function calcLines(config, thickness, sourceSheets, blanks900) {
    var kit = (config.kits || []).find(function (k) {
      return String(k.thickness_mm) === String(thickness);
    });
    if (!kit) return null;

    var sheets = parseInt(sourceSheets, 10) || 0;
    if (blanks900 && parseInt(blanks900, 10) > 0) {
      sheets = Math.ceil(parseInt(blanks900, 10) / 3);
    }
    if (sheets <= 0) return null;

    var lines = (kit.pieces || []).map(function (p) {
      var qty = Number(p.qty_per_sheet) * sheets;
      var price = Number(p.unit_price);
      var amount = Math.round(qty * price * 100) / 100;
      return {
        material_id: p.material_id,
        material_name: p.material_name,
        unit: p.unit,
        quantity: qty,
        unit_price: price,
        amount: amount,
      };
    });
    var total = lines.reduce(function (s, l) {
      return s + l.amount;
    }, 0);
    return {
      lines: lines,
      meta: {
        thickness_mm: kit.thickness_mm,
        thickness_label: kit.label,
        source_sheets: sheets,
        sheet_total: Number(kit.sheet_total),
        receipt_total: Math.round(total * 100) / 100,
        shop_total: Math.round(Number(kit.sheet_total) * sheets * 100) / 100,
        blanks_900x600: sheets * 3,
      },
    };
  }

  function renderPreview(container, result) {
    if (!container || !result) return;
    var html =
      '<table class="fanera-nest-preview-table"><thead><tr>' +
      "<th>Материал</th><th>Кол-во</th><th>Цена</th><th>Сумма</th>" +
      "</tr></thead><tbody>";
    result.lines.forEach(function (line) {
      html +=
        "<tr><td>" +
        line.material_name +
        "</td><td>" +
        fmtQty(line.quantity) +
        " " +
        (line.unit || "") +
        "</td><td>" +
        fmtMoney(line.unit_price, 2) +
        "</td><td><strong>" +
        fmtMoney(line.amount, 2) +
        " ₽</strong></td></tr>";
    });
    html +=
      "</tbody></table>" +
      '<p class="fanera-nest-preview-meta">' +
      "Листов 1525×1525: <strong>" +
      result.meta.source_sheets +
      "</strong> × " +
      fmtMoney(result.meta.sheet_total, 0) +
      " ₽ = <strong>" +
      fmtMoney(result.meta.shop_total, 2) +
      " ₽</strong> по чеку. " +
      "Заготовок 900×600: <strong>" +
      result.meta.blanks_900x600 +
      "</strong>.</p>";
    container.innerHTML = html;
  }

  function getState(root) {
    if (panelState) {
      if (!panelState.has(root)) panelState.set(root, {});
      return panelState.get(root);
    }
    for (var i = 0; i < panelStateFallback.length; i++) {
      if (panelStateFallback[i].root === root) return panelStateFallback[i];
    }
    var st = { root: root };
    panelStateFallback.push(st);
    return st;
  }

  function canFillLines() {
    return typeof window.faneraNestReceiptFillLines === "function";
  }

  function syncFillButton(root, lastResult) {
    var btnFill = root.querySelector(".fanera-nest-btn-fill");
    if (!btnFill) return;
    btnFill.disabled = !(lastResult && canFillLines());
  }

  function ensurePanelReady(root, config) {
    var state = getState(root);
    if (state.ready) return state;

    var thicknessSel = root.querySelector(".fanera-nest-thickness");
    var sheetsInp = root.querySelector(".fanera-nest-sheets");
    var blanksInp = root.querySelector(".fanera-nest-blanks");
    var preview = root.querySelector(".fanera-nest-preview");

    if (thicknessSel && config.kits && config.kits.length && !thicknessSel.options.length) {
      thicknessSel.innerHTML = config.kits
        .map(function (k) {
          return (
            '<option value="' +
            k.thickness_mm +
            '">' +
            k.label +
            " (лист " +
            k.sheet_price +
            " + " +
            k.cut_price +
            " ₽)</option>"
          );
        })
        .join("");
    }

    function runCalc() {
      if (!config) return null;
      var modeSheets = root.querySelector('input[name="fanera_nest_mode"]:checked');
      var useBlanks = modeSheets && modeSheets.value === "blanks";
      var result = calcLines(
        config,
        thicknessSel && thicknessSel.value,
        useBlanks ? null : sheetsInp && sheetsInp.value,
        useBlanks ? blanksInp && blanksInp.value : null
      );
      state.lastResult = result;
      if (!preview) {
        syncFillButton(root, result);
        return result;
      }
      if (!result) {
        preview.innerHTML =
          '<p class="fanera-nest-preview-empty">Укажите число листов или заготовок 900×600.</p>';
        syncFillButton(root, null);
        return null;
      }
      renderPreview(preview, result);
      syncFillButton(root, result);
      return result;
    }

    state.runCalc = runCalc;
    [sheetsInp, blanksInp, thicknessSel].forEach(function (el) {
      if (!el || el.getAttribute("data-fanera-bound") === "1") return;
      el.setAttribute("data-fanera-bound", "1");
      el.addEventListener("change", runCalc);
      el.addEventListener("input", runCalc);
    });
    root.querySelectorAll('input[name="fanera_nest_mode"]').forEach(function (el) {
      if (el.getAttribute("data-fanera-bound") === "1") return;
      el.setAttribute("data-fanera-bound", "1");
      el.addEventListener("change", function () {
        var blanks =
          root.querySelector('input[name="fanera_nest_mode"]:checked').value === "blanks";
        if (sheetsInp) sheetsInp.disabled = blanks;
        if (blanksInp) blanksInp.disabled = !blanks;
        runCalc();
      });
    });

    state.ready = true;
    runCalc();
    return state;
  }

  function panelFromTarget(target) {
    if (!target || !target.closest) return null;
    return target.closest("[data-fanera-nest-calc]");
  }

  function onCalcClick(ev) {
    var root = panelFromTarget(ev.target);
    if (!root) return;
    var config = parseConfig();
    if (!config) return;
    var state = ensurePanelReady(root, config);
    if (state.runCalc) state.runCalc();
  }

  function onFillClick(ev) {
    var root = panelFromTarget(ev.target);
    if (!root) return;
    var config = parseConfig();
    if (!config || !canFillLines()) return;
    var state = ensurePanelReady(root, config);
    var result = state.lastResult || (state.runCalc ? state.runCalc() : null);
    if (!result) return;
    window.faneraNestReceiptFillLines(result.lines, result.meta);
  }

  function initPanels() {
    var config = parseConfig();
    document.querySelectorAll("[data-fanera-nest-calc]").forEach(function (root) {
      if (!config) {
        var preview = root.querySelector(".fanera-nest-preview");
        if (preview) {
          preview.innerHTML =
            '<p class="fanera-nest-preview-empty">Калькулятор недоступен: нет данных каталога фанеры.</p>';
        }
        syncFillButton(root, null);
        return;
      }
      ensurePanelReady(root, config);
    });
  }

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    if (t.closest(".fanera-nest-btn-calc")) {
      ev.preventDefault();
      onCalcClick(ev);
      return;
    }
    if (t.closest(".fanera-nest-btn-fill")) {
      ev.preventDefault();
      onFillClick(ev);
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPanels);
  } else {
    initPanels();
  }

  window.FaneraNestReceiptCalc = { calcLines: calcLines, fmtMoney: fmtMoney, fmtQty: fmtQty };
})();
