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
          var machineRaw = row.hourly_rate;
          var machineN =
            machineRaw != null && String(machineRaw).trim() !== ""
              ? parseFloat(String(machineRaw).replace(",", "."))
              : null;
          var employeeRaw = row.employee_hourly_rate;
          var employeeN =
            employeeRaw != null && String(employeeRaw).trim() !== ""
              ? parseFloat(String(employeeRaw).replace(",", "."))
              : null;
          out[String(row.id)] = {
            machine: isFinite(machineN) ? machineN : null,
            employee: isFinite(employeeN) ? employeeN : null,
          };
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
    if (!tpId) return;
    var stages = stagesListForTechProcess(tpId);
    if (!stages.length) return;
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
          var $opt = jq("<option></option>").attr("value", String(s.id)).text(label);
          if (s.hourly_rate != null && String(s.hourly_rate).trim() !== "") {
            $opt.attr("data-machine-rate", String(s.hourly_rate));
          }
          if (s.employee_hourly_rate != null && String(s.employee_hourly_rate).trim() !== "") {
            $opt.attr("data-employee-rate", String(s.employee_hourly_rate));
          }
          $s.append($opt);
        });
        var keep =
          cur &&
          stages.some(function (x) {
            return String(x.id) === String(cur);
          });
        $s.val(keep ? cur : "");
        if ($s.data("select2")) {
          $s.trigger("change");
          $s.trigger("change.select2");
        } else {
          $s.trigger("change");
        }
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
      var row = ev.target && ev.target.closest && ev.target.closest("tr.form-row");
      if (row) ensureLaborRowMenu(row);
    });
  }

  function laborAdminUrls() {
    if (window._tcLaborStageAdminUrls) return window._tcLaborStageAdminUrls;
    var el = document.getElementById("tc-labor-stage-admin-urls");
    if (!el || !el.textContent) return null;
    try {
      window._tcLaborStageAdminUrls = JSON.parse(el.textContent);
      return window._tcLaborStageAdminUrls;
    } catch (e) {
      return null;
    }
  }

  function laborStageId(tr) {
    var sel = tr.querySelector("select[name$='-production_stage']");
    if (!sel) return "";
    var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    if (jq && jq.fn && jq.fn.select2 && jq(sel).data("select2")) {
      var v = jq(sel).val();
      if (v != null && String(v).trim() !== "") return String(v).trim();
    }
    return sel.value != null ? String(sel.value).trim() : "";
  }

  function laborActionHref(act, stageId) {
    var urls = laborAdminUrls();
    if (!urls) return "";
    if (act === "add-related") return urls.add || "";
    if (!stageId) return "";
    var tpl = urls.change;
    if (act === "delete-related") tpl = urls.delete;
    else if (act === "view-related") tpl = urls.view;
    else if (act === "change-related") tpl = urls.change;
    if (!tpl) return "";
    return tpl.replace("{id}", stageId);
  }

  function openLaborAdminPopup(href, popupId) {
    if (!href) return;
    var fake = document.createElement("a");
    fake.href = href;
    fake.id = popupId || "change_tc_labor_menu";
    if (typeof window.showRelatedObjectPopup === "function") {
      window.showRelatedObjectPopup(fake);
      return;
    }
    window.open(href, fake.id, "height=500,width=800,resizable=yes,scrollbars=yes");
  }

  function triggerLaborRelatedAction(tr, act) {
    if (!tr || !act) return;
    var stageId = laborStageId(tr);
    if (act === "add-related") {
      openLaborAdminPopup(laborActionHref("add-related", stageId), "add_tc_labor_menu");
      return;
    }
    if (!stageId) return;
    var href = laborActionHref(act, stageId);
    if (!href) return;
    if (act === "view-related") {
      window.open(href, "_blank", "noopener,noreferrer");
      return;
    }
    var pid = act === "delete-related" ? "delete_tc_labor_menu" : "change_tc_labor_menu";
    openLaborAdminPopup(href, pid);
  }

  function ensureLaborRowMenu(tr) {
    if (!tr || tr.classList.contains("empty-form")) return;
    var cell = tr.querySelector("td.tc-labor-row-menu");
    if (!cell || cell.querySelector(".tc-labor-row-menu-wrap")) return;
    var sample = document.querySelector(
      ".techcard-labor-inline-group tr.tc-labor-data-row:not(.empty-form) td.tc-labor-row-menu .tc-labor-row-menu-wrap"
    );
    if (sample) {
      cell.appendChild(sample.cloneNode(true));
      return;
    }
    cell.innerHTML =
      '<div class="tc-labor-row-menu-wrap">' +
      '<button type="button" class="tc-labor-row-kebab" aria-haspopup="true" aria-expanded="false" aria-label="Действия с этапом">' +
      '<span class="tc-labor-row-kebab-dot"></span><span class="tc-labor-row-kebab-dot"></span><span class="tc-labor-row-kebab-dot"></span>' +
      "</button>" +
      '<div class="tc-labor-row-menu-pop" role="menu" hidden>' +
      '<button type="button" role="menuitem" data-act="delete-related">Удалить</button>' +
      '<button type="button" role="menuitem" data-act="view-related">Редактировать</button>' +
      '<button type="button" role="menuitem" data-act="change-related">Изменить</button>' +
      '<button type="button" role="menuitem" data-act="add-related">Добавить этап</button>' +
      "</div></div>";
  }

  function ensureAllLaborRowMenus() {
    var table = document.querySelector("table.tc-labor-inline-table");
    if (!table) return;
    table.querySelectorAll("tbody tr.tc-labor-data-row:not(.empty-form)").forEach(ensureLaborRowMenu);
  }

  function bindLaborRowMenusOnce() {
    if (window._tcLaborMenusBound) return;
    window._tcLaborMenusBound = true;
    var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    if (!jq) {
      window.setTimeout(bindLaborRowMenusOnce, 100);
      return;
    }

    function closeAllLaborMenus() {
      jq(".techcard-labor-inline-group .tc-labor-row-menu-pop").each(function () {
        this.setAttribute("hidden", "hidden");
        this.classList.remove("tc-labor-row-menu-pop--flip");
        this.style.position = "";
        this.style.left = "";
        this.style.top = "";
        this.style.zIndex = "";
      });
      jq(".techcard-labor-inline-group .tc-labor-row-kebab").attr("aria-expanded", "false");
    }

    function placeLaborMenuPop($wrap, $pop) {
      var wrapEl = $wrap[0];
      var popEl = $pop[0];
      if (!wrapEl || !popEl) return;
      var br = wrapEl.getBoundingClientRect();
      $pop.removeClass("tc-labor-row-menu-pop--flip");
      popEl.style.position = "fixed";
      popEl.style.zIndex = "10050";
      popEl.style.left = Math.max(8, br.right - popEl.offsetWidth) + "px";
      var top = br.bottom + 4;
      if (top + popEl.offsetHeight > window.innerHeight - 8 && br.top > popEl.offsetHeight + 8) {
        top = br.top - popEl.offsetHeight - 4;
        $pop.addClass("tc-labor-row-menu-pop--flip");
      }
      popEl.style.top = top + "px";
    }

    jq(document).on("click.tcLaborMenu", ".techcard-labor-inline-group .tc-labor-row-kebab", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var $kebab = jq(this);
      var $wrap = $kebab.closest(".tc-labor-row-menu-wrap");
      var $pop = $wrap.find(".tc-labor-row-menu-pop");
      if (!$pop.length) return;
      var wasOpen = $pop.attr("hidden") == null;
      closeAllLaborMenus();
      if (!wasOpen) {
        $pop.removeAttr("hidden");
        $kebab.attr("aria-expanded", "true");
        window.setTimeout(function () {
          placeLaborMenuPop($wrap, $pop);
        }, 0);
      }
    });

    jq(document).on("click.tcLaborMenu", ".techcard-labor-inline-group .tc-labor-row-menu-pop button", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var tr = this.closest("tr.form-row");
      closeAllLaborMenus();
      triggerLaborRelatedAction(tr, this.getAttribute("data-act"));
    });

    jq(document).on("click.tcLaborMenuClose", function (e) {
      if (!jq(e.target).closest(".tc-labor-row-menu-wrap").length) {
        closeAllLaborMenus();
      }
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

  function rowEmployeeMinutes(tr) {
    return tr.querySelector('input[name$="-employee_minutes"]');
  }

  function rowEmployeeRateCell(tr) {
    var td = tr.querySelector("td.field-employee_hourly_rate_display");
    return td ? td.querySelector("p") : null;
  }

  function parseMoneyText(text) {
    var raw = String(text || "").replace(/\s+/g, "").replace(",", ".");
    var cleaned = raw.replace(/[^\d.-]/g, "");
    var n = parseFloat(cleaned);
    return isFinite(n) ? n : null;
  }

  function rowRateCell(tr) {
    var td = tr.querySelector("td.field-hourly_rate_display");
    return td ? td.querySelector("p") : null;
  }

  function rowPayCell(tr) {
    var td = tr.querySelector("td.field-labor_pay_display");
    return td ? td.querySelector("p") : null;
  }

  function rowEmployeePayCell(tr) {
    var td = tr.querySelector("td.field-employee_pay_display");
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

  function stageRates(rateByStage, sid, tr) {
    if (!sid || !rateByStage) {
      return { machine: null, employee: null };
    }
    var row = rateByStage[sid];
    var machine = null;
    var employee = null;
    if (row && typeof row === "object") {
      machine = row.machine;
      employee = row.employee;
    } else if (typeof row === "number" || row === null) {
      machine = row;
    }
    if ((employee == null || !isFinite(employee)) && tr) {
      var sel = rowStageSelect(tr);
      if (sel && sel.selectedOptions && sel.selectedOptions.length) {
        var optRate = sel.selectedOptions[0].getAttribute("data-employee-rate");
        if (optRate != null && String(optRate).trim() !== "") {
          var optN = parseFloat(String(optRate).replace(",", "."));
          if (isFinite(optN)) employee = optN;
        }
      }
      if (employee == null || !isFinite(employee)) {
        var rateCell = rowEmployeeRateCell(tr);
        var parsed = rateCell ? parseMoneyText(rateCell.textContent) : null;
        if (parsed != null) employee = parsed;
      }
    }
    return { machine: machine, employee: employee };
  }

  function updateRow(tr, rateByStage) {
    var sel = rowStageSelect(tr);
    var sid = sel && sel.value ? String(sel.value) : "";
    var rates = stageRates(rateByStage, sid, tr);
    var rate = rates.machine;
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
    var empMinutesEl = rowEmployeeMinutes(tr);
    var empMinutes = empMinutesEl ? parseFloat(String(empMinutesEl.value).replace(",", ".")) : 0;
    var empRate = rates.employee;
    var empPay = rowEmployeePayCell(tr);
    if (empPay) {
      if (isFinite(empMinutes) && empRate != null && isFinite(empRate) && empMinutes > 0) {
        empPay.textContent = formatMoney((empMinutes / 60) * empRate);
      } else if (isFinite(empMinutes) && empMinutes === 0) {
        empPay.textContent = formatMoney(0);
      } else {
        empPay.textContent = "—";
      }
    }
  }

  function sumTable(table) {
    var rateByStage = parseStageRates();
    var tbody = table.querySelector("tbody");
    if (!tbody) return;
    var rows = tbody.querySelectorAll("tr.form-row");
    var sumNh = 0;
    var sumMachinePay = 0;
    var sumEmployeeMinutes = 0;
    var sumEmployeePay = 0;
    var sumOv = 0;
    rows.forEach(function (tr) {
      if (tr.classList.contains("empty-form")) return;
      var del = tr.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) return;
      updateRow(tr, rateByStage);
      var sel = rowStageSelect(tr);
      var sid = sel && sel.value ? String(sel.value) : "";
      var rates = stageRates(rateByStage, sid, tr);
      var rate = rates.machine;
      var nhEl = rowNormHours(tr);
      var ovEl = rowOverhead(tr);
      var empMinutesEl = rowEmployeeMinutes(tr);
      var nhRaw = nhEl ? parseFloat(String(nhEl.value).replace(",", ".")) : 0;
      var nhHours = normHoursForPay(nhRaw);
      var ov = ovEl ? parseFloat(String(ovEl.value).replace(",", ".")) : 0;
      var empMinutes = empMinutesEl ? parseFloat(String(empMinutesEl.value).replace(",", ".")) : 0;
      var empRate = rates.employee;
      if (isFinite(nhRaw)) sumNh += nhRaw;
      if (isFinite(ov)) sumOv += ov;
      if (isFinite(empMinutes)) sumEmployeeMinutes += empMinutes;
      if (rate != null && isFinite(rate) && isFinite(nhHours)) sumMachinePay += nhHours * rate;
      if (isFinite(empMinutes) && empRate != null && isFinite(empRate)) {
        sumEmployeePay += (empMinutes / 60) * empRate;
      }
    });
    var foot = table.querySelector("tfoot.tc-labor-tfoot");
    if (!foot) return;
    var tnh = foot.querySelector(".tc-labor-total-norm-hours");
    var tmp = foot.querySelector(".tc-labor-total-machine-pay");
    var tem = foot.querySelector(".tc-labor-total-employee-minutes");
    var tep = foot.querySelector(".tc-labor-total-employee-pay");
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
    if (tmp) tmp.textContent = formatMoney(sumMachinePay);
    if (tem) tem.textContent = String(round2(sumEmployeeMinutes)) + " мин";
    if (tep) tep.textContent = formatMoney(sumEmployeePay);
    if (to) to.textContent = formatMoney(sumOv);
    updateUnitCostSummary(sumMachinePay + sumEmployeePay, sumOv);
  }

  function materialPriceMap() {
    var el = document.getElementById("techcard-material-avg-prices");
    if (!el || !el.textContent) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return {};
    }
  }

  function cutRateByStageId() {
    var el = document.getElementById("tech-process-stages-data");
    if (!el || !el.textContent) return {};
    try {
      var tpId = currentTechProcessId();
      var map = JSON.parse(el.textContent);
      var stages = map[String(tpId)] || [];
      var out = {};
      stages.forEach(function (s) {
        if (s.id == null) return;
        var raw = s.cut_rate_per_meter;
        if (raw != null && String(raw).trim() !== "") {
          var n = parseFloat(String(raw).replace(",", "."));
          if (isFinite(n)) out[String(s.id)] = n;
        }
      });
      return out;
    } catch (e) {
      return {};
    }
  }

  function eachItemBackendRow(fn) {
    document
      .querySelectorAll(".techcard-items-backend tbody tr.form-row")
      .forEach(function (tr) {
        if (tr.classList.contains("empty-form")) return;
        var del = tr.querySelector('input[name$="-DELETE"]');
        if (del && del.checked) return;
        fn(tr);
      });
  }

  function rowItemKindValue(tr) {
    var kindEl = tr.querySelector('select[name$="-item_kind"], input[name$="-item_kind"]');
    if (kindEl && kindEl.value != null && String(kindEl.value).trim() !== "") {
      return String(kindEl.value).trim();
    }
    return String(tr.getAttribute("data-item-kind") || "").trim();
  }

  function isMaterialLineKind(kind) {
    return kind === "raw" || kind === "material";
  }

  function rowMaterialId(tr) {
    var matEl = tr.querySelector('input[name$="-material"], select[name$="-material"]');
    var mid = matEl ? String(matEl.value || "").trim() : "";
    if (!mid) {
      mid = String(tr.getAttribute("data-material-id") || "").trim();
    }
    return mid;
  }

  function rowQuantityValue(tr) {
    var qtyEl = tr.querySelector('input[name$="-quantity"]');
    var qty = qtyEl ? parseFloat(String(qtyEl.value).replace(",", ".")) : NaN;
    if (!isFinite(qty) || qty <= 0) {
      var rid = tr.id;
      if (rid) {
        var cardQty = document.querySelector(
          '.tc-item-card[data-row-id="' + rid.replace(/"/g, '\\"') + '"] .tc-item-card-qty'
        );
        if (cardQty) {
          qty = parseFloat(String(cardQty.value).replace(",", "."));
        }
      }
    }
    return qty;
  }

  function serverCostBreakdown() {
    var el = document.getElementById("techcard-cost-breakdown");
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function sumMaterialsCost() {
    var priceMap = materialPriceMap();
    var total = 0;
    var lines = 0;
    var missingPrice = 0;
    eachItemBackendRow(function (tr) {
      var kind = rowItemKindValue(tr);
      if (kind === "component") return;
      if (kind && !isMaterialLineKind(kind)) return;
      var mid = rowMaterialId(tr);
      if (!mid) return;
      var qty = rowQuantityValue(tr);
      if (!isFinite(qty) || qty <= 0) return;
      var unitStr = priceMap[mid];
      var unit = unitStr != null ? parseFloat(String(unitStr).replace(",", ".")) : NaN;
      if (!isFinite(unit)) {
        missingPrice++;
        return;
      }
      total += unit * qty;
      lines++;
    });
    if (lines > 0) return round2(total);
    if (missingPrice > 0) return null;
    var sb = serverCostBreakdown();
    if (sb && sb.materials != null && String(sb.materials).trim() !== "") {
      var fallback = parseFloat(String(sb.materials).replace(",", "."));
      if (isFinite(fallback) && fallback > 0) return round2(fallback);
    }
    return null;
  }

  function sumCutCost() {
    var cutRates = cutRateByStageId();
    var total = 0;
    var lines = 0;
    eachItemBackendRow(function (tr) {
      var lenEl = tr.querySelector('input[name$="-cut_length_meters_per_unit"]');
      if (!lenEl) return;
      var len = parseFloat(String(lenEl.value).replace(",", "."));
      if (!isFinite(len) || len <= 0) return;
      var stageEl = tr.querySelector('select[name$="-production_stage"]');
      var sid = stageEl && stageEl.value ? String(stageEl.value) : "";
      var rate = sid ? cutRates[sid] : null;
      if (rate == null || !isFinite(rate)) return;
      total += len * rate;
      lines++;
    });
    return lines > 0 ? round2(total) : null;
  }

  function setCostCell(selector, value) {
    var block = document.getElementById("tc-unit-cost-summary");
    if (!block) return;
    var el = block.querySelector(selector);
    if (!el) return;
    el.textContent = value != null && isFinite(value) ? formatMoney(value) : "—";
  }

  function updateUnitCostSummary(laborPay, overheadPay) {
    var materials = sumMaterialsCost();
    var cut = sumCutCost();
    var labor = isFinite(laborPay) ? laborPay : 0;
    var overhead = isFinite(overheadPay) ? overheadPay : 0;
    var hasLabor = isFinite(laborPay);
    var hasOverhead = isFinite(overheadPay);
    setCostCell(".tc-unit-cost-materials", materials);
    setCostCell(".tc-unit-cost-labor", hasLabor ? labor : null);
    setCostCell(".tc-unit-cost-overhead", hasOverhead ? overhead : null);
    setCostCell(".tc-unit-cost-cut", cut);
    var parts = [];
    if (materials != null) parts.push(materials);
    if (hasLabor) parts.push(labor);
    if (hasOverhead) parts.push(overhead);
    if (cut != null) parts.push(cut);
    var total = parts.length ? round2(parts.reduce(function (a, b) { return a + b; }, 0)) : null;
    setCostCell(".tc-unit-cost-total", total);
  }

  function bindItemsCostRecalc() {
    if (document.body.getAttribute("data-tc-cost-items-bound") === "1") return;
    document.body.setAttribute("data-tc-cost-items-bound", "1");
    function go(e) {
      var t = e.target;
      if (!t) return;
      var n = t.name || "";
      var cls = t.classList || null;
      if (
        n.indexOf("-quantity") === -1 &&
        n.indexOf("-material") === -1 &&
        n.indexOf("-cut_length") === -1 &&
        n.indexOf("-production_stage") === -1 &&
        n.indexOf("-item_kind") === -1 &&
        !(cls && cls.contains("tc-item-card-qty"))
      ) {
        return;
      }
      var table = document.querySelector("table.tc-labor-inline-table");
      if (table) sumTable(table);
    }
    document.addEventListener("input", go);
    document.addEventListener("change", go);
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
    bindItemsCostRecalc();
    bindLaborRowMenusOnce();
    var table = document.querySelector("table.tc-labor-inline-table");
    if (table) {
      if (table.getAttribute("data-tc-labor-bound") !== "1") {
        table.setAttribute("data-tc-labor-bound", "1");
        bind(table);
      }
      refillLaborStageSelects();
      ensureAllLaborRowMenus();
    }
  }

  window.tcLaborInlineInit = init;

  bindLaborRowMenusOnce();

  window.addEventListener("tc-ms-tab-activate", function (ev) {
    if (ev && ev.detail && ev.detail.name === "money") {
      window.setTimeout(init, 50);
    }
  });
  window.addEventListener("tc:labor-inline-moved", function () {
    window.setTimeout(init, 0);
  });

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
