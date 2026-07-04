/**
 * Блок «Цены»: вкладки «Цены» / «Стоимость», расчёт закупочной по материалам и плановой с наценкой.
 */
(function () {
  "use strict";

  function round2(n) {
    return Math.round(n * 100) / 100;
  }

  function parseDecimal(s) {
    if (s == null || s === "") return null;
    var t = String(s).trim().replace(/\s/g, "").replace(",", ".");
    if (t === "") return null;
    var x = parseFloat(t);
    return isFinite(x) ? x : null;
  }

  function getMaterialPriceMap() {
    var el = document.getElementById("product-material-avg-prices");
    if (!el || !el.textContent) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return {};
    }
  }

  function materialsFieldset(form) {
    return form.querySelector("fieldset.product-extra-inline--materials");
  }

  function sumMaterialsPurchase(form, priceMap) {
    var fs = materialsFieldset(form);
    if (!fs) {
      return { total: null, lines: 0, skippedNoPrice: 0, skippedEmpty: 0 };
    }
    var rows = fs.querySelectorAll("tbody tr.form-row");
    var total = 0;
    var lines = 0;
    var skippedNoPrice = 0;
    var skippedEmpty = 0;
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      if (tr.classList.contains("empty-form")) continue;
      var del = tr.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) continue;
      var matEl = tr.querySelector('select[name$="-material"], input[name$="-material"]');
      if (!matEl) continue;
      var mid = String(matEl.value || "").trim();
      if (!mid) {
        skippedEmpty++;
        continue;
      }
      var qtyEl = tr.querySelector('input[name$="-quantity_per_unit"]');
      var qty = qtyEl ? parseDecimal(qtyEl.value) : null;
      if (qty == null || qty <= 0) {
        skippedEmpty++;
        continue;
      }
      var unitStr = priceMap[mid];
      var unit = unitStr != null ? parseDecimal(unitStr) : null;
      if (unit == null) {
        skippedNoPrice++;
        continue;
      }
      total += unit * qty;
      lines++;
    }
    if (lines === 0) {
      return { total: null, lines: 0, skippedNoPrice: skippedNoPrice, skippedEmpty: skippedEmpty };
    }
    return {
      total: round2(total),
      lines: lines,
      skippedNoPrice: skippedNoPrice,
      skippedEmpty: skippedEmpty,
    };
  }

  function formatMoney(n) {
    if (n == null || !isFinite(n)) return "—";
    return round2(n).toFixed(2);
  }

  function getPlannedCostBreakdown() {
    var el = document.getElementById("product-planned-cost-breakdown");
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var fieldset = document.querySelector("fieldset.product-prices-tabs-host");
    if (!fieldset || fieldset.getAttribute("data-product-prices-tabs") === "1") return;
    fieldset.setAttribute("data-product-prices-tabs", "1");

    var form = document.getElementById("product_form");
    if (!form) return;

    var h2 = fieldset.querySelector("h2.fieldset-heading, h2");
    if (!h2) return;

    var bar = document.createElement("div");
    bar.className = "product-prices-subtabs-bar";
    bar.setAttribute("role", "tablist");

    var btn0 = document.createElement("button");
    btn0.type = "button";
    btn0.className = "product-prices-subtab active";
    btn0.setAttribute("role", "tab");
    btn0.setAttribute("aria-selected", "true");
    btn0.setAttribute("data-subtab", "0");
    btn0.textContent = "Цены";

    var btn1 = document.createElement("button");
    btn1.type = "button";
    btn1.className = "product-prices-subtab";
    btn1.setAttribute("role", "tab");
    btn1.setAttribute("aria-selected", "false");
    btn1.setAttribute("data-subtab", "1");
    btn1.textContent = "Стоимость";

    bar.appendChild(btn0);
    bar.appendChild(btn1);

    var panelsWrap = document.createElement("div");
    panelsWrap.className = "product-prices-subpanels";

    var panel0 = document.createElement("div");
    panel0.className = "product-prices-subpanel active";
    panel0.setAttribute("data-subtab-panel", "0");
    panel0.setAttribute("role", "tabpanel");

    var panel1 = document.createElement("div");
    panel1.className = "product-prices-subpanel";
    panel1.setAttribute("data-subtab-panel", "1");
    panel1.setAttribute("role", "tabpanel");

    panelsWrap.appendChild(panel0);
    panelsWrap.appendChild(panel1);

    h2.insertAdjacentElement("afterend", bar);
    bar.insertAdjacentElement("afterend", panelsWrap);

    var rowPurchase = fieldset.querySelector(".form-row.field-purchase_price");
    var rowPlanned = fieldset.querySelector(".form-row.field-planned_price");
    var rowMin = fieldset.querySelector(".form-row.field-min_price");
    var rowMarkup = fieldset.querySelector(".form-row.field-planned_markup_percent");

    if (rowPurchase) panel0.appendChild(rowPurchase);
    if (rowPlanned) panel0.appendChild(rowPlanned);
    if (rowMin) panel0.appendChild(rowMin);

    var calcPurchaseRow = document.createElement("div");
    calcPurchaseRow.className = "form-row product-prices-calc-row field-product_calc_purchase";
    calcPurchaseRow.innerHTML =
      '<div class="product-prices-calc-inner">' +
      '<span class="product-prices-calc-label">Расчётная закупочная, ₽</span>' +
      '<span id="product-calc-purchase-value" class="product-prices-calc-value">—</span>' +
      "</div>" +
      '<p id="product-calc-purchase-hint" class="product-prices-calc-hint" hidden></p>';

    var calcPlannedRow = document.createElement("div");
    calcPlannedRow.className = "form-row product-prices-calc-row field-product_calc_planned";
    calcPlannedRow.innerHTML =
      '<div class="product-prices-calc-inner">' +
      '<span class="product-prices-calc-label">Расчётная плановая, ₽</span>' +
      '<span id="product-calc-planned-value" class="product-prices-calc-value">—</span>' +
      "</div>" +
      '<p class="product-prices-calc-formula help">Закупочная × (1 + наценка&nbsp;% / 100)</p>';

    var plannedCostRow = document.createElement("div");
    plannedCostRow.className = "form-row product-prices-calc-row field-product_planned_total_cost";
    plannedCostRow.innerHTML =
      '<div class="product-prices-calc-inner">' +
      '<span class="product-prices-calc-label">Себестоимость изделия, ₽</span>' +
      '<span id="product-planned-total-cost-value" class="product-prices-calc-value">—</span>' +
      "</div>" +
      '<p id="product-planned-total-cost-hint" class="product-prices-calc-hint help">' +
      "Материалы + оплата труда + затраты на производство + рез (из техкарты)." +
      "</p>";

    var applyRow = document.createElement("div");
    applyRow.className = "form-row product-prices-apply-row";
    applyRow.innerHTML =
      '<div class="product-prices-apply-btns">' +
      '<button type="button" class="button product-prices-apply-btn" id="product-apply-calc-purchase">Подставить в «Закупочная цена»</button>' +
      '<button type="button" class="button product-prices-apply-btn" id="product-apply-calc-planned">Подставить в «Плановая цена продажи»</button>' +
      "</div>";

    if (rowMarkup) panel1.appendChild(rowMarkup);
    panel1.appendChild(calcPurchaseRow);
    panel1.appendChild(calcPlannedRow);
    panel1.appendChild(plannedCostRow);
    panel1.appendChild(applyRow);

    var elPurchaseVal = document.getElementById("product-calc-purchase-value");
    var elPlannedVal = document.getElementById("product-calc-planned-value");
    var elPlannedTotalCost = document.getElementById("product-planned-total-cost-value");
    var elHint = document.getElementById("product-calc-purchase-hint");
    var inpMarkup = document.getElementById("id_planned_markup_percent");
    var inpPurchase = document.getElementById("id_purchase_price");
    var inpPlanned = document.getElementById("id_planned_price");

    function setSubtab(idx) {
      var on0 = idx === 0;
      btn0.classList.toggle("active", on0);
      btn1.classList.toggle("active", !on0);
      btn0.setAttribute("aria-selected", on0 ? "true" : "false");
      btn1.setAttribute("aria-selected", !on0 ? "true" : "false");
      panel0.classList.toggle("active", on0);
      panel1.classList.toggle("active", !on0);
    }

    btn0.addEventListener("click", function () {
      setSubtab(0);
    });
    btn1.addEventListener("click", function () {
      setSubtab(1);
    });

    function recalc() {
      var priceMap = getMaterialPriceMap();
      var r = sumMaterialsPurchase(form, priceMap);
      if (elPurchaseVal) {
        elPurchaseVal.textContent = r.total != null ? formatMoney(r.total) : "—";
      }
      if (elHint) {
        if (r.skippedNoPrice > 0) {
          var nSkip = r.skippedNoPrice;
          var head =
            nSkip === 1
              ? "В одной строке состава нет средней цены материала"
              : "В " + nSkip + " строках состава нет средней цены материала";
          elHint.textContent =
            head +
            ". Цена для расчёта подтягивается из приёмки (поступления материала с ценой за единицу). " +
            "Оформите поступление или выберите материал, по которому уже есть приёмки.";
          elHint.hidden = false;
        } else {
          elHint.hidden = true;
          elHint.textContent = "";
        }
      }
      var planned = null;
      if (r.total != null && inpMarkup) {
        var m = parseDecimal(inpMarkup.value);
        if (m != null && isFinite(m)) {
          planned = round2(r.total * (1 + m / 100));
        }
      }
      if (elPlannedVal) {
        elPlannedVal.textContent = planned != null ? formatMoney(planned) : "—";
      }
      var breakdown = getPlannedCostBreakdown();
      if (elPlannedTotalCost) {
        if (breakdown && breakdown.total != null) {
          var totalN = parseDecimal(breakdown.total);
          elPlannedTotalCost.textContent = totalN != null ? formatMoney(totalN) : "—";
        } else if (r.total != null && breakdown) {
          var labor = parseDecimal(breakdown.labor) || 0;
          var overhead = parseDecimal(breakdown.overhead) || 0;
          var cut = parseDecimal(breakdown.cut) || 0;
          elPlannedTotalCost.textContent = formatMoney(round2(r.total + labor + overhead + cut));
        } else {
          elPlannedTotalCost.textContent = r.total != null ? formatMoney(r.total) : "—";
        }
      }
      return { purchase: r.total, planned: planned };
    }

    function applyPurchase() {
      var x = recalc().purchase;
      if (inpPurchase && x != null) {
        inpPurchase.value = String(round2(x));
        inpPurchase.dispatchEvent(new Event("input", { bubbles: true }));
        inpPurchase.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function applyPlanned() {
      var x = recalc().planned;
      if (inpPlanned && x != null) {
        inpPlanned.value = String(round2(x));
        inpPlanned.dispatchEvent(new Event("input", { bubbles: true }));
        inpPlanned.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    var b1 = document.getElementById("product-apply-calc-purchase");
    var b2 = document.getElementById("product-apply-calc-planned");
    if (b1) b1.addEventListener("click", applyPurchase);
    if (b2) b2.addEventListener("click", applyPlanned);

    setSubtab(0);

    if (inpMarkup) {
      inpMarkup.addEventListener("input", recalc);
      inpMarkup.addEventListener("change", recalc);
    }

    form.addEventListener("input", function (ev) {
      var t = ev.target;
      if (!t || !t.name) return;
      if (t.name.indexOf("quantity_per_unit") !== -1 || t.name.indexOf("-material") !== -1) {
        recalc();
      }
    });
    form.addEventListener("change", function (ev) {
      var t = ev.target;
      if (!t || !t.name) return;
      if (
        t.name.indexOf("quantity_per_unit") !== -1 ||
        t.name.indexOf("-material") !== -1 ||
        (t.name.indexOf("-DELETE") !== -1 && t.type === "checkbox")
      ) {
        recalc();
      }
    });

    var mf = materialsFieldset(form);
    if (mf) {
      var tbody = mf.querySelector("tbody");
      if (tbody && typeof MutationObserver !== "undefined") {
        var mo = new MutationObserver(function () {
          recalc();
        });
        mo.observe(tbody, { childList: true, subtree: true });
      }
    }

    recalc();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
