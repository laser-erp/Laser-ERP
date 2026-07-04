/**
 * Техкарта — вкладка «Деньги»: ставка нормо-часа из карты этапа (JSON tech-process-stages-data),
 * пересчёт оплаты труда по строке и строка «Итого».
 */
(function () {
  "use strict";

  var laborFormsetAddedBound = false;

  function parseStageRates() {
    var el = document.getElementById("tech-process-stages-data");
    if (!el || !el.textContent) return {};
    try {
      var raw = JSON.parse(el.textContent);
      var out = {};
      Object.keys(raw).forEach(function (tpId) {
        (raw[tpId] || []).forEach(function (row) {
          if (row.id == null) return;
          var v = row.hourly_rate;
          var n =
            v != null && String(v).trim() !== ""
              ? parseFloat(String(v).replace(",", "."))
              : null;
          out[String(row.id)] = isFinite(n) ? n : null;
        });
      });
      return out;
    } catch (e) {
      return {};
    }
  }

  /** Этапы выбранного техпроцесса (как в json_script tech-process-stages-data). */
  function stagesListForTechProcess(tpId) {
    var el = document.getElementById("tech-process-stages-data");
    if (!el || !el.textContent || !tpId) return [];
    try {
      var map = JSON.parse(el.textContent);
      return map[String(tpId)] || [];
    } catch (e) {
      return [];
    }
  }

  function currentTechProcessId() {
    var tp = document.getElementById("id_tech_process");
    if (!tp || tp.value == null) return "";
    return String(tp.value).trim();
  }

  function refillLaborStageSelects() {
    var table = document.querySelector("table.tc-labor-inline-table");
    if (!table) return;
    var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    if (!jq) return;
    var tpId = currentTechProcessId();
    var stages = stagesListForTechProcess(tpId);
    jq(table)
      .find("tbody tr.form-row:not(.empty-form) select[name$='-production_stage']")
      .each(function () {
        var sel = this;
        var cur = sel.value;
        var $s = jq(sel);
        $s.empty();
        $s.append(jq("<option></option>").attr("value", "").text("---------"));
        stages.forEach(function (s) {
          if (s.id == null) return;
          var label = s.name != null ? String(s.name) : String(s.id);
          $s.append(jq("<option></option>").attr("value", String(s.id)).text(label));
        });
        var keep =
          cur &&
          stages.some(function (x) {
            return String(x.id) === String(cur);
          });
        $s.val(keep ? cur : "");
        $s.trigger("change");
      });
    sumTable(table);
  }

  function bindTechProcessToLaborStages() {
    var tp = document.getElementById("id_tech_process");
    if (!tp || tp.getAttribute("data-tc-labor-tp-bound") === "1") return;
    tp.setAttribute("data-tc-labor-tp-bound", "1");
    var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    function go() {
      window.setTimeout(refillLaborStageSelects, 0);
    }
    tp.addEventListener("change", go);
    document.addEventListener("change", function (e) {
      if (e.target && e.target.id === "id_tech_process") go();
    });
    if (jq && jq.fn && jq.fn.select2) {
      jq(tp).on("select2:select select2:clear select2:unselect change", go);
    }
  }

  function bindLaborFormsetAdded() {
    if (laborFormsetAddedBound) return;
    laborFormsetAddedBound = true;
    document.addEventListener("formset:added", function (ev) {
      var t = ev.target && ev.target.closest && ev.target.closest("table.tc-labor-inline-table");
      if (!t) return;
      refillLaborStageSelects();
    });
  }

  function round2(x) {
    return Math.round(x * 100) / 100;
  }

  function round6(x) {
    return Math.round(x * 1e6) / 1e6;
  }

  function isMinutesUnit() {
    var el = document.getElementById("id_labor_norm_input_unit");
    return el && el.value === "minutes";
  }

  function normHoursForPay(nhRaw) {
    if (!isFinite(nhRaw)) return NaN;
    return isMinutesUnit() ? nhRaw / 60 : nhRaw;
  }

  function convertNormInputsOnUnitChange(prevUnit, nextUnit) {
    var fromM = prevUnit === "minutes";
    var toM = nextUnit === "minutes";
    if (fromM === toM) return;
    document.querySelectorAll('input[name$="-norm_hours"]').forEach(function (el) {
      var tr = el.closest("tr.form-row");
      if (!tr || tr.classList.contains("empty-form")) return;
      var v = parseFloat(String(el.value).replace(",", "."));
      if (!isFinite(v)) return;
      if (fromM && !toM) el.value = String(round6(v / 60));
      else if (!fromM && toM) el.value = String(round6(v * 60));
    });
  }

  function bindLaborNormUnitSwitch() {
    var unitEl = document.getElementById("id_labor_norm_input_unit");
    if (!unitEl || unitEl.getAttribute("data-tc-labor-unit-bound") === "1") return;
    unitEl.setAttribute("data-tc-labor-unit-bound", "1");
    var prev = unitEl.value;
    unitEl.addEventListener("change", function () {
      var next = unitEl.value;
      convertNormInputsOnUnitChange(prev, next);
      prev = next;
      var table = document.querySelector("table.tc-labor-inline-table");
      if (table) sumTable(table);
    });
  }

  function rowStageSelect(tr) {
    return tr.querySelector('select[name$="-production_stage"]');
  }

  function rowNormHours(tr) {
    return tr.querySelector('input[name$="-norm_hours"]');
  }

  function rowOverhead(tr) {
    return tr.querySelector('input[name$="-overhead_per_unit"]');
  }

  function rowRateCell(tr) {
    var td = tr.querySelector("td.field-hourly_rate_display");
    return td ? td.querySelector("p") : null;
  }

  function rowPayCell(tr) {
    var td = tr.querySelector("td.field-labor_pay_display");
    return td ? td.querySelector("p") : null;
  }

  function formatMoney(n) {
    if (!isFinite(n)) return "—";
    return round2(n).toFixed(2) + " \u20BD";
  }

  function formatRate(r) {
    if (r == null || !isFinite(r)) return "—";
    return round2(r).toFixed(2);
  }

  function updateRow(tr, rateByStage) {
    var sel = rowStageSelect(tr);
    var sid = sel && sel.value ? String(sel.value) : "";
    var rate = sid && rateByStage ? rateByStage[sid] : null;
    var rp = rowRateCell(tr);
    if (rp) rp.textContent = formatRate(rate);
    var nhEl = rowNormHours(tr);
    var nhRaw = nhEl ? parseFloat(String(nhEl.value).replace(",", ".")) : NaN;
    var nhHours = normHoursForPay(nhRaw);
    var pay = rowPayCell(tr);
    if (pay) {
      if (rate != null && isFinite(rate) && isFinite(nhHours)) {
        pay.textContent = formatMoney(nhHours * rate);
      } else {
        pay.textContent = "—";
      }
    }
  }

  function sumTable(table) {
    var rateByStage = parseStageRates();
    var tbody = table.querySelector("tbody");
    if (!tbody) return;
    var rows = tbody.querySelectorAll("tr.form-row");
    var sumNh = 0;
    var sumPay = 0;
    var sumOv = 0;
    rows.forEach(function (tr) {
      if (tr.classList.contains("empty-form")) return;
      var del = tr.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) return;
      updateRow(tr, rateByStage);
      var sel = rowStageSelect(tr);
      var sid = sel && sel.value ? String(sel.value) : "";
      var rate = sid ? rateByStage[sid] : null;
      var nhEl = rowNormHours(tr);
      var ovEl = rowOverhead(tr);
      var nhRaw = nhEl ? parseFloat(String(nhEl.value).replace(",", ".")) : 0;
      var nhHours = normHoursForPay(nhRaw);
      var ov = ovEl ? parseFloat(String(ovEl.value).replace(",", ".")) : 0;
      if (isFinite(nhRaw)) sumNh += nhRaw;
      if (isFinite(ov)) sumOv += ov;
      if (rate != null && isFinite(rate) && isFinite(nhHours)) sumPay += nhHours * rate;
    });
    var foot = table.querySelector("tfoot.tc-labor-tfoot");
    if (!foot) return;
    var tnh = foot.querySelector(".tc-labor-total-norm-hours");
    var tp = foot.querySelector(".tc-labor-total-labor-pay");
    var to = foot.querySelector(".tc-labor-total-overhead");
    if (tnh) {
      if (isFinite(sumNh)) {
        tnh.textContent = isMinutesUnit()
          ? String(round2(sumNh)) + " мин"
          : String(round2(sumNh));
      } else {
        tnh.textContent = "—";
      }
    }
    if (tp) tp.textContent = formatMoney(sumPay);
    if (to) to.textContent = formatMoney(sumOv);
  }

  function bind(table) {
    var tbody = table.querySelector("tbody");
    if (tbody) {
      tbody.addEventListener("input", function () {
        sumTable(table);
      });
      tbody.addEventListener("change", function () {
        sumTable(table);
      });
    }
    var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    if (jq) {
      jq(document).on(
        "select2:select select2:clear change",
        "select[name$='-production_stage']",
        function () {
          var t = document.querySelector("table.tc-labor-inline-table");
          if (t) sumTable(t);
        }
      );
    }
    sumTable(table);
  }

  function init() {
    bindTechProcessToLaborStages();
    bindLaborFormsetAdded();
    bindLaborNormUnitSwitch();
    var table = document.querySelector("table.tc-labor-inline-table");
    if (table) {
      if (table.getAttribute("data-tc-labor-bound") !== "1") {
        table.setAttribute("data-tc-labor-bound", "1");
        bind(table);
      }
      refillLaborStageSelects();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      init();
      window.setTimeout(init, 300);
    });
  } else {
    init();
    window.setTimeout(init, 300);
  }
})();
