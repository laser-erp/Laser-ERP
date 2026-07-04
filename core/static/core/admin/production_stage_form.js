/**
 * Форма этапа: вкладки, M2M сотрудников/контрагентов (восстановление по транскрипту чата).
 * Сотрудники: список выбранных сверху, строка «Сотрудник»+«Мастер», поиск, панель справа,
 * «Добавить всех», чекбокс в строке при наведении, радио «мастер», блокировка при «любой сотрудник».
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var ctx = this,
        args = arguments;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  function getConfig() {
    return window.PRODUCTION_STAGE_FORM || null;
  }

  function parseJsonScript(id) {
    var el = document.getElementById(id);
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function fetchAutocomplete(url, params, term, cb) {
    var sep = url.indexOf("?") >= 0 ? "&" : "?";
    var u =
      url + sep + params + "&term=" + encodeURIComponent(term || "");
    fetch(u, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        cb(data.results || [], data.pagination || {});
      })
      .catch(function () {
        cb([], {});
      });
  }

  function optionInSelect(sel, value) {
    if (!sel) return null;
    var v = String(value);
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === v) return sel.options[i];
    }
    return null;
  }

  function moveOptionTo(fromSel, toSel, opt) {
    if (!opt || !toSel) return;
    if (opt.parentNode !== fromSel && opt.parentNode !== toSel) return;
    if (opt.parentNode === fromSel) fromSel.removeChild(opt);
    toSel.appendChild(opt);
    try {
      fromSel.dispatchEvent(new Event("change", { bubbles: true }));
      toSel.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) {}
  }

  function moveAllFromTo(fromSel, toSel) {
    while (fromSel.options.length) {
      moveOptionTo(fromSel, toSel, fromSel.options[0]);
    }
  }

  function removeExecutorVerboseLabels(fieldRow) {
    var labels = fieldRow.querySelectorAll("label");
    for (var i = 0; i < labels.length; i++) {
      var el = labels[i];
      if (el.closest(".ps-m2m-custom")) continue;
      var t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (t === "Исполнители (сотрудники):" || t === "Исполнители (сотрудники)") {
        el.remove();
        break;
      }
    }
  }

  function setupM2M(fieldRow, basename, acParams, options) {
    options = options || {};
    var isCp = !!options.isCounterparty;
    var serviceChoices = options.serviceChoices || [];
    var servicesInitial = options.servicesInitial || {};

    var fromId = "id_" + basename + "_from";
    var toId = "id_" + basename + "_to";
    var multiId = "id_" + basename;
    var fromSel = document.getElementById(fromId);
    var toSel = document.getElementById(toId);
    var multiSel = document.getElementById(multiId);
    /* Django 6+: filter_horizontal — один <select multiple>, без _from/_to */
    var useMulti =
      multiSel &&
      multiSel.multiple &&
      fieldRow.contains(multiSel) &&
      (!fromSel || !toSel || !fieldRow.contains(fromSel));
    if (!useMulti) {
      if (!fromSel || !toSel || !fieldRow.contains(fromSel)) return;
    }

    var cfg = getConfig();
    if (!cfg || !cfg.autocompleteUrl) return;

    function dispatchSelChange(sel) {
      if (!sel) return;
      try {
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e) {}
    }

    function mSelectedIds() {
      var ids = {};
      if (useMulti) {
        for (var i = 0; i < multiSel.options.length; i++) {
          var ox = multiSel.options[i];
          if (ox.selected) ids[ox.value] = true;
        }
      } else {
        for (var j = 0; j < toSel.options.length; j++) {
          ids[toSel.options[j].value] = true;
        }
      }
      return ids;
    }

    function mAvailableCount() {
      if (useMulti) {
        var n = 0;
        for (var i = 0; i < multiSel.options.length; i++) {
          if (!multiSel.options[i].selected) n++;
        }
        return n;
      }
      return fromSel.options.length;
    }

    function mSelectedCount() {
      if (useMulti) {
        var n = 0;
        for (var i = 0; i < multiSel.options.length; i++) {
          if (multiSel.options[i].selected) n++;
        }
        return n;
      }
      return toSel.options.length;
    }

    function mSelectById(id, text) {
      id = String(id);
      if (useMulti) {
        var o = optionInSelect(multiSel, id);
        if (o) {
          o.selected = true;
        } else {
          multiSel.appendChild(new Option(text || id, id, true, true));
        }
        dispatchSelChange(multiSel);
      } else {
        var o2 = optionInSelect(fromSel, id);
        if (o2) {
          moveOptionTo(fromSel, toSel, o2);
        } else {
          toSel.appendChild(new Option(text || id, id, true, true));
          dispatchSelChange(toSel);
        }
      }
    }

    function mDeselectById(id) {
      id = String(id);
      if (useMulti) {
        var o = optionInSelect(multiSel, id);
        if (o) o.selected = false;
        dispatchSelChange(multiSel);
      } else {
        var o2 = optionInSelect(toSel, id);
        if (o2) moveOptionTo(toSel, fromSel, o2);
      }
    }

    function mClearSelected() {
      if (useMulti) {
        for (var i = 0; i < multiSel.options.length; i++) {
          multiSel.options[i].selected = false;
        }
        dispatchSelChange(multiSel);
      } else {
        while (toSel.options.length) {
          moveOptionTo(toSel, fromSel, toSel.options[0]);
        }
      }
    }

    function mAddAllAvailable() {
      if (useMulti) {
        for (var i = 0; i < multiSel.options.length; i++) {
          multiSel.options[i].selected = true;
        }
        dispatchSelChange(multiSel);
      } else {
        moveAllFromTo(fromSel, toSel);
      }
    }

    function mCollectOptionsMap() {
      var map = {};
      if (useMulti) {
        for (var i = 0; i < multiSel.options.length; i++) {
          var o = multiSel.options[i];
          map[o.value] = o.text || o.value;
        }
      } else {
        function add(sel) {
          for (var k = 0; k < sel.options.length; k++) {
            var ox = sel.options[k];
            map[ox.value] = ox.text || ox.value;
          }
        }
        add(fromSel);
        add(toSel);
      }
      return map;
    }

    function mSideApply(checkboxes) {
      if (useMulti) {
        for (var i = 0; i < multiSel.options.length; i++) {
          multiSel.options[i].selected = false;
        }
        for (var c = 0; c < checkboxes.length; c++) {
          if (!checkboxes[c].checked) continue;
          var oid = String(checkboxes[c].value);
          var ox = optionInSelect(multiSel, oid);
          if (ox) ox.selected = true;
          else multiSel.appendChild(new Option(oid, oid, true, true));
        }
        dispatchSelChange(multiSel);
      } else {
        moveAllFromTo(fromSel, toSel);
        moveAllFromTo(toSel, fromSel);
        for (var d = 0; d < checkboxes.length; d++) {
          if (!checkboxes[d].checked) continue;
          var oid2 = String(checkboxes[d].value);
          var o = optionInSelect(fromSel, oid2);
          if (o) moveOptionTo(fromSel, toSel, o);
        }
      }
    }

    var wrapper =
      fieldRow.querySelector(".related-widget-wrapper") || fieldRow;

    var custom = document.createElement("div");
    custom.className = "ps-m2m-custom" + (isCp ? " ps-m2m-counterparty" : " ps-m2m-employees");

    if (isCp) {
      custom.innerHTML =
        '<div class="ps-m2m-layout">' +
        '<div class="ps-m2m-main">' +
        '<div class="ps-m2m-title">Контрагенты (подрядчики этапа)</div>' +
        '<div class="ps-search-row executors-custom-row">' +
        '<div class="ps-ac-wrap ps-executors-search-wrap">' +
        '<input type="search" class="ps-m2m-search" placeholder="Поиск…" autocomplete="off" />' +
        '<ul class="ps-ac-results executors-custom-dropdown" hidden></ul>' +
        "</div>" +
        '<button type="button" class="ps-btn ps-add-from-results">Добавить из поиска</button>' +
        '<button type="button" class="ps-btn ps-add-all-from">Добавить всех</button>' +
        '<button type="button" class="ps-btn ps-clear-chosen">Очистить список</button>' +
        "</div>" +
        '<div class="ps-chosen-list">' +
        '<div class="ps-chosen-list-header">Выбрано</div>' +
        '<div class="ps-chosen-items"></div>' +
        "</div>" +
        "</div>" +
        '<aside class="ps-m2m-aside">' +
        "<strong>Сводка</strong><br />" +
        '<span class="ps-aside-count">0</span> записей' +
        "</aside>" +
        "</div>";
    } else {
      removeExecutorVerboseLabels(fieldRow);
      custom.innerHTML =
        '<div class="ps-m2m-layout">' +
        '<div class="ps-m2m-main">' +
        '<div class="ps-m2m-title">Исполнители (сотрудники)</div>' +
        '<div class="ps-chosen-list executors-chosen-list">' +
        '<div class="ps-chosen-list-header">Выбранные исполнители</div>' +
        '<div class="ps-chosen-items"></div>' +
        "</div>" +
        '<div class="ps-second-row executors-second-row">' +
        '<label class="ps-sync-row"><input type="checkbox" class="ps-employee-all-cb" /> <span class="executors-employee-label-text">Сотрудник</span></label>' +
        '<span class="ps-master-hint executors-master-label-right">Мастер</span>' +
        "</div>" +
        '<div class="ps-search-row executors-custom-row">' +
        '<div class="ps-ac-wrap ps-executors-search-wrap">' +
        '<input type="search" class="ps-m2m-search" placeholder="Сотрудник" autocomplete="off" />' +
        '<ul class="ps-ac-results executors-custom-dropdown" hidden></ul>' +
        "</div>" +
        '<button type="button" class="ps-btn ps-open-side">Выбрать сотрудника</button>' +
        '<button type="button" class="ps-btn ps-add-all-from">Добавить всех</button>' +
        '<button type="button" class="ps-btn ps-clear-chosen">Очистить список</button>' +
        "</div>" +
        "</div>" +
        '<aside class="ps-m2m-aside">' +
        "<strong>Сводка</strong><br />" +
        '<span class="ps-aside-count">0</span> исполнителей' +
        "</aside>" +
        "</div>";
    }

    wrapper.appendChild(custom);

    var searchInput = custom.querySelector(".ps-m2m-search");
    var acList = custom.querySelector(".ps-ac-results");
    var chosenBox = custom.querySelector(".ps-chosen-items");
    var asideCount = custom.querySelector(".ps-aside-count");
    var btnAddAllFrom = custom.querySelector(".ps-add-all-from");
    var btnClear = custom.querySelector(".ps-clear-chosen");
    var btnAddFromResults = custom.querySelector(".ps-add-from-results");
    var btnOpenSide = custom.querySelector(".ps-open-side");
    var employeeAllCb = custom.querySelector(".ps-employee-all-cb");

    var lastResults = [];
    var acIndex = -1;

    var anyEmployeeInput = document.querySelector(
      'input[name*="any_employee_can_execute"]'
    );

    function updateAnyEmployeeLock() {
      if (isCp) return;
      var on = anyEmployeeInput && anyEmployeeInput.checked;
      custom.classList.toggle("ps-m2m-locked", !!on);
      custom.querySelectorAll("input, button, select").forEach(function (el) {
        if (el.classList && el.classList.contains("ps-employee-all-cb")) {
          el.disabled = !!on;
        } else if (el !== anyEmployeeInput) {
          el.disabled = !!on;
        }
      });
    }

    if (anyEmployeeInput) {
      anyEmployeeInput.addEventListener("change", updateAnyEmployeeLock);
      updateAnyEmployeeLock();
    }

    function syncEmployeeTopCheckbox() {
      if (!employeeAllCb || isCp) return;
      var allPicked =
        mAvailableCount() === 0 && mSelectedCount() > 0;
      employeeAllCb.checked = allPicked;
    }

    function buildServiceSelect(orgId) {
      var sel = document.createElement("select");
      sel.name = "counterparty_service_" + orgId;
      sel.id = "id_counterparty_service_" + orgId;
      sel.className = "ps-cp-service";
      var empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "— услуга —";
      sel.appendChild(empty);
      var initial = servicesInitial[String(orgId)] || servicesInitial[orgId];
      for (var i = 0; i < serviceChoices.length; i++) {
        var pair = serviceChoices[i];
        var pk = pair[0];
        var name = pair[1];
        var o = document.createElement("option");
        o.value = String(pk);
        o.textContent = name;
        if (initial && String(pk) === String(initial)) o.selected = true;
        sel.appendChild(o);
      }
      return sel;
    }

    var masterSelect = document.getElementById("id_master");

    function renderChosen() {
      chosenBox.innerHTML = "";
      var n = mSelectedCount();
      asideCount.textContent = String(n);

      if (n === 0) {
        var empty = document.createElement("div");
        empty.className = "ps-chosen-empty";
        empty.textContent = isCp
          ? "Контрагенты не выбраны. Введите имя в поиске или нажмите «Добавить всех»."
          : "Сотрудники не выбраны. Поиск, панель «Выбрать сотрудника» или «Добавить всех».";
        chosenBox.appendChild(empty);
        syncEmployeeTopCheckbox();
        return;
      }

      function renderOneOpt(opt, idx) {
          var row = document.createElement("div");
          row.className = "ps-chosen-item executors-chosen-item";
          row.dataset.value = opt.value;

          var numWrap = document.createElement("span");
          numWrap.className = "ps-chosen-num-wrap executors-chosen-num-wrap";
          var num = document.createElement("span");
          num.className = "ps-chosen-num executors-chosen-num";
          num.textContent = idx + 1 + ".";
          var rowCb = document.createElement("input");
          rowCb.type = "checkbox";
          rowCb.className = "ps-chosen-cb executors-chosen-cb";
          rowCb.checked = true;
          rowCb.title = "Исполнитель";
          rowCb.addEventListener("change", function () {
            if (!rowCb.checked) {
              mDeselectById(opt.value);
              renderChosen();
            }
          });
          numWrap.appendChild(num);
          numWrap.appendChild(rowCb);
          row.appendChild(numWrap);

          var lab = document.createElement("span");
          lab.className = "ps-chosen-label";
          lab.textContent = opt.text || opt.label || opt.value;
          row.appendChild(lab);

          if (!isCp && masterSelect) {
            var mw = document.createElement("span");
            mw.className = "ps-chosen-master-wrap";
            var mr = document.createElement("input");
            mr.type = "radio";
            mr.name = "ps_stage_master_radio";
            mr.className = "ps-master-radio";
            mr.checked =
              String(masterSelect.value || "") === String(opt.value);
            mr.addEventListener("change", function () {
              if (mr.checked) {
                masterSelect.value = String(opt.value);
                try {
                  masterSelect.dispatchEvent(
                    new Event("change", { bubbles: true })
                  );
                } catch (e) {}
                renderChosen();
              }
            });
            mw.appendChild(mr);
            row.appendChild(mw);
          }

          if (isCp) {
            row.appendChild(buildServiceSelect(opt.value));
          }

          var rm = document.createElement("button");
          rm.type = "button";
          rm.className = "ps-chosen-remove executors-chosen-remove";
          rm.setAttribute("aria-label", "Удалить");
          rm.innerHTML = "&times;";
          rm.addEventListener("click", function () {
            mDeselectById(opt.value);
            renderChosen();
          });
          row.appendChild(rm);

          chosenBox.appendChild(row);
      }

      if (useMulti) {
        var idx = 0;
        for (var mi = 0; mi < multiSel.options.length; mi++) {
          var mo = multiSel.options[mi];
          if (!mo.selected) continue;
          renderOneOpt(mo, idx);
          idx++;
        }
      } else {
        for (var i = 0; i < toSel.options.length; i++) {
          renderOneOpt(toSel.options[i], i);
        }
      }
      syncEmployeeTopCheckbox();
    }

    function hideAc() {
      acList.hidden = true;
      acList.innerHTML = "";
      acIndex = -1;
    }

    function showAc(items) {
      acList.innerHTML = "";
      if (!items.length) {
        var li = document.createElement("li");
        li.className = "ps-ac-empty";
        li.textContent = "Ничего не найдено";
        acList.appendChild(li);
        acList.hidden = false;
        return;
      }
      items.forEach(function (item) {
        var li = document.createElement("li");
        li.textContent = item.text || item.id;
        li.dataset.id = String(item.id);
        li.addEventListener("mousedown", function (e) {
          e.preventDefault();
        });
        li.addEventListener("click", function () {
          addById(String(item.id), item.text || String(item.id));
          hideAc();
          searchInput.value = "";
        });
        acList.appendChild(li);
      });
      acList.hidden = false;
    }

    function addById(id, text) {
      var selected = mSelectedIds();
      if (selected[id]) return;
      mSelectById(id, text);
      renderChosen();
    }

    var runSearch = debounce(function () {
      var q = (searchInput.value || "").trim();
      if (q.length < 1) {
        hideAc();
        return;
      }
      fetchAutocomplete(cfg.autocompleteUrl, acParams, q, function (results) {
        lastResults = results;
        var selected = mSelectedIds();
        var filtered = results.filter(function (r) {
          return !selected[String(r.id)];
        });
        showAc(filtered);
      });
    }, 200);

    searchInput.addEventListener("input", runSearch);
    searchInput.addEventListener("focus", function () {
      if (searchInput.value.trim()) runSearch();
    });

    searchInput.addEventListener("keydown", function (e) {
      if (acList.hidden) return;
      var lis = acList.querySelectorAll("li:not(.ps-ac-empty)");
      if (e.key === "ArrowDown") {
        e.preventDefault();
        acIndex = Math.min(acIndex + 1, lis.length - 1);
        highlightAc(lis);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        acIndex = Math.max(acIndex - 1, 0);
        highlightAc(lis);
      } else if (e.key === "Enter") {
        if (acIndex >= 0 && lis[acIndex]) {
          e.preventDefault();
          lis[acIndex].click();
        }
      } else if (e.key === "Escape") {
        hideAc();
      }
    });

    function highlightAc(lis) {
      for (var i = 0; i < lis.length; i++) {
        lis[i].classList.toggle("ps-ac-active", i === acIndex);
      }
    }

    document.addEventListener("click", function (e) {
      if (!custom.contains(e.target)) hideAc();
    });

    if (btnAddAllFrom) {
      btnAddAllFrom.addEventListener("click", function () {
        mAddAllAvailable();
        renderChosen();
      });
    }

    if (btnAddFromResults) {
      btnAddFromResults.addEventListener("click", function () {
        var selected = mSelectedIds();
        lastResults.forEach(function (r) {
          var id = String(r.id);
          if (!selected[id]) addById(id, r.text || id);
          selected[id] = true;
        });
      });
    }

    if (btnClear) {
      btnClear.addEventListener("click", function () {
        mClearSelected();
        renderChosen();
      });
    }

    if (employeeAllCb && !isCp) {
      employeeAllCb.addEventListener("change", function () {
        if (anyEmployeeInput && anyEmployeeInput.checked) return;
        if (employeeAllCb.checked) {
          mAddAllAvailable();
          renderChosen();
        }
      });
    }

    function openSidePanel() {
      if (anyEmployeeInput && anyEmployeeInput.checked) return;
      var map = mCollectOptionsMap();
      var overlay = document.createElement("div");
      overlay.className = "ps-side-overlay";
      var panel = document.createElement("div");
      panel.className = "ps-side-panel";
      panel.setAttribute("role", "dialog");
      panel.innerHTML =
        '<div class="ps-side-head"><strong>Сотрудники</strong>' +
        '<button type="button" class="ps-side-close" aria-label="Закрыть">&times;</button></div>' +
        '<div class="ps-side-body"></div>' +
        '<div class="ps-side-foot">' +
        '<button type="button" class="ps-btn ps-side-cancel">Отмена</button>' +
        '<button type="button" class="ps-btn ps-side-apply">Применить</button>' +
        "</div>";

      var body = panel.querySelector(".ps-side-body");
      var selected = mSelectedIds();
      Object.keys(map).forEach(function (id) {
        var lab = document.createElement("label");
        lab.className = "ps-side-line";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = id;
        cb.checked = !!selected[id];
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(" " + map[id]));
        body.appendChild(lab);
      });

      function close() {
        overlay.remove();
      }

      panel.querySelector(".ps-side-close").addEventListener("click", close);
      panel.querySelector(".ps-side-cancel").addEventListener("click", close);
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) close();
      });

      panel.querySelector(".ps-side-apply").addEventListener("click", function () {
        var checks = body.querySelectorAll('input[type="checkbox"]');
        mSideApply(checks);
        renderChosen();
        close();
      });

      overlay.appendChild(panel);
      document.body.appendChild(overlay);
    }

    if (btnOpenSide) {
      btnOpenSide.addEventListener("click", openSidePanel);
    }

    if (masterSelect && !isCp) {
      masterSelect.addEventListener("change", function () {
        renderChosen();
      });
    }

    renderChosen();
  }

  ready(function () {
    var fs = document.querySelector("fieldset.executors-tabs");
    if (!fs) return;

    var cfg = getConfig();
    if (!cfg) return;

    var rowAe = fs.querySelector(".form-row.field-any_employee_can_execute");
    var rowMaster = fs.querySelector(".form-row.field-master");
    var rowEx = fs.querySelector(".form-row.field-executors");
    var rowCp = fs.querySelector(".form-row.field-counterparty_executors");
    if (!rowEx || !rowCp) return;

    var serviceChoices = parseJsonScript("ps-service-choices") || [];
    var servicesInitial = parseJsonScript("ps-services-initial") || {};

    var tabs = document.createElement("div");
    tabs.className = "ps-exec-tabs-bar";
    tabs.innerHTML =
      '<button type="button" class="ps-tab active" data-tab="emp">Сотрудники</button>' +
      '<button type="button" class="ps-tab" data-tab="cp">Контрагенты</button>' +
      '<div class="ps-tab-side"><span class="ps-cp-hint"></span></div>';

    var insertBefore = rowAe || rowEx;
    fs.insertBefore(tabs, insertBefore);

    function countCp() {
      var toLegacy = rowCp.querySelector('select[id$="_to"]');
      if (toLegacy) return toLegacy.options.length;
      var m = rowCp.querySelector("select#id_counterparty_executors");
      if (m && m.multiple) {
        var n = 0;
        for (var i = 0; i < m.options.length; i++) {
          if (m.options[i].selected) n++;
        }
        return n;
      }
      return 0;
    }

    function updateSideHint() {
      var hint = tabs.querySelector(".ps-cp-hint");
      if (hint) hint.textContent = "Контрагентов: " + countCp();
    }

    function setTab(which) {
      var emp = which === "emp";
      [rowAe, rowMaster, rowEx].forEach(function (r) {
        if (r) r.style.display = emp ? "" : "none";
      });
      rowCp.style.display = emp ? "none" : "";
      tabs.querySelectorAll(".ps-tab").forEach(function (b) {
        var isEmp = b.getAttribute("data-tab") === "emp";
        b.classList.toggle("active", emp ? isEmp : !isEmp);
      });
      updateSideHint();
    }

    tabs.addEventListener("click", function (e) {
      var t = e.target.closest(".ps-tab");
      if (!t) return;
      setTab(t.getAttribute("data-tab") === "cp" ? "cp" : "emp");
    });

    if (rowAe && rowMaster && rowAe.parentNode) {
      var wrap = document.createElement("div");
      wrap.className = "ps-executors-first-row";
      rowAe.parentNode.insertBefore(wrap, rowAe);
      wrap.appendChild(rowAe);
      wrap.appendChild(rowMaster);
    }

    if (rowMaster) {
      var mlab = rowMaster.querySelector("label");
      if (mlab && !mlab.querySelector(".ps-master-help")) {
        var mh = document.createElement("span");
        mh.className = "help-icon-tooltip ps-master-help";
        mh.setAttribute(
          "title",
          "В приложении Laser ERP мастер этапа видит все задания по этапу и всех, кто может их выполнить. Может распределять свободные задания между исполнителями этапа и отмечать, кто выполнил задание."
        );
        mh.setAttribute("aria-label", "Подсказка: роль мастера этапа");
        mh.textContent = "?";
        mlab.appendChild(mh);
      }
    }

    setTab("emp");

    setupM2M(rowEx, "executors", cfg.employeeParams, {
      isCounterparty: false,
    });
    setupM2M(rowCp, "counterparty_executors", cfg.counterpartyParams, {
      isCounterparty: true,
      serviceChoices: serviceChoices,
      servicesInitial: servicesInitial,
    });

    var toCp =
      rowCp.querySelector('select[id$="_to"]') ||
      rowCp.querySelector("#id_counterparty_executors");
    if (toCp) {
      toCp.addEventListener("change", updateSideHint);
    }
    updateSideHint();
  });
})();
