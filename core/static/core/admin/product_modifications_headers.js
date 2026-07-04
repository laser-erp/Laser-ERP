/**
 * Компактные заголовки таблицы модификаций в карточке товара.
 * Делаем текстом через JS (не через ::before), чтобы работало в любых темах.
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function getModsTable() {
    return document.querySelector(
      "fieldset.product-extra-inline--modifications .tabular table"
    );
  }

  function getDataRows(table) {
    if (!table) return [];
    var rows = table.querySelectorAll("tbody tr");
    return Array.prototype.filter.call(rows, function (row) {
      if (row.classList.contains("add-row")) return false;
      if (row.classList.contains("empty-form")) return false;
      if ((row.id || "").indexOf("__prefix__") !== -1) return false;
      return true;
    });
  }

  function removeColumnByIndex(table, index) {
    if (!table || index < 0) return;
    var rows = table.querySelectorAll("tr");
    rows.forEach(function (row) {
      var cells = row.children;
      if (cells && cells.length > index) {
        cells[index].remove();
      }
    });
  }

  function removeOriginalColumn(table) {
    if (!table) return;
    var originalHeader = table.querySelector("thead th.original");
    if (originalHeader && originalHeader.parentElement) {
      var headerCells = Array.prototype.slice.call(originalHeader.parentElement.children);
      var idx = headerCells.indexOf(originalHeader);
      removeColumnByIndex(table, idx);
      return;
    }

    // Fallback: если классов нет, убираем первый "пустой" столбец.
    var firstHeaderRow = table.querySelector("thead tr");
    if (!firstHeaderRow) return;
    var ths = Array.prototype.slice.call(firstHeaderRow.children);
    for (var i = 0; i < ths.length; i++) {
      var txt = (ths[i].textContent || "").trim();
      if (!txt) {
        removeColumnByIndex(table, i);
        return;
      }
    }
  }

  function applyCompactHeaders(table) {
    var root = table ? table.querySelector("thead") : null;
    if (!root) return;

    var byClass = {
      "column-name_display": "Название",
      "column-thickness_display": "📏 мм",
      "column-grade_display": "🏷 сорт",
      "column-sanding_display": "🧽 шл",
      "column-abrasive_display": "🔢 P",
      "column-planned_price": "💵 цена",
      "column-is_active": "🟢 on",
    };

    var headers = root.querySelectorAll("th");
    headers.forEach(function (th) {
      for (var cls in byClass) {
        if (th.classList.contains(cls)) {
          th.textContent = byClass[cls];
          th.title = byClass[cls];
          break;
        }
      }
    });
  }

  function readCellValue(row, fieldClass) {
    var cell = row.querySelector("td." + fieldClass);
    if (!cell) return "";
    var ctrl = cell.querySelector("select, input");
    if (!ctrl) return (cell.textContent || "").trim();
    if (ctrl.type === "checkbox") {
      return ctrl.checked ? "1" : "0";
    }
    if (ctrl.tagName === "SELECT") {
      var opt = ctrl.options[ctrl.selectedIndex];
      return ((opt && opt.text) || ctrl.value || "").trim();
    }
    return (ctrl.value || "").trim();
  }

  function buildFilters(table) {
    if (!table) return;
    var defs = [
      { key: "thickness", label: "мм", cls: "field-thickness_display" },
      { key: "grade", label: "сорт", cls: "field-grade_display" },
      { key: "sanding", label: "шл", cls: "field-sanding_display" },
      { key: "abrasive", label: "P", cls: "field-abrasive_display" },
    ];

    var rows = getDataRows(table);
    var selects = {};
    var tabular = table.closest(".tabular");
    if (!tabular) return;
    var host = tabular.parentElement.querySelector("[data-mods-filters]");
    var showInactiveToggle = host
      ? host.querySelector("[data-filter-show-inactive]")
      : null;

    if (!host) {
      host = document.createElement("div");
      host.className = "product-mods-filters";
      defs.forEach(function (d) {
        var wrap = document.createElement("label");
        wrap.className = "product-mods-filter";
        wrap.textContent = d.label + ": ";
        var select = document.createElement("select");
        select.setAttribute("data-filter-key", d.key);
        var allOption = document.createElement("option");
        allOption.value = "";
        allOption.textContent = "Все";
        select.appendChild(allOption);
        wrap.appendChild(select);
        host.appendChild(wrap);
      });
      tabular.parentNode.insertBefore(host, tabular);
    }

    defs.forEach(function (d) {
      var select = host.querySelector('select[data-filter-key="' + d.key + '"]');
      if (!select) return;
      select.innerHTML = "";
      var allOption = document.createElement("option");
      allOption.value = "";
      allOption.textContent = "Все";
      select.appendChild(allOption);

      var values = {};
      rows.forEach(function (row) {
        var v = readCellValue(row, d.cls);
        if (v) values[v] = true;
      });
      Object.keys(values)
        .sort()
        .forEach(function (v) {
          var o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          select.appendChild(o);
        });
      selects[d.key] = select;
    });

    function applyFilters() {
      var showInactive = !!(
        showInactiveToggle && showInactiveToggle.checked
      );
      rows.forEach(function (row) {
        var ok = true;

        var activeState = readCellValue(row, "field-is_active");
        var isInactive = activeState === "0";
        row.classList.toggle("product-mod-row-inactive", isInactive);
        if (isInactive && !showInactive) {
          ok = false;
        }

        defs.forEach(function (d) {
          var selected = selects[d.key].value;
          if (!selected) return;
          var current = readCellValue(row, d.cls);
          if (current !== selected) ok = false;
        });
        row.style.display = ok ? "" : "none";
      });
    }

    Object.keys(selects).forEach(function (k) {
      selects[k].addEventListener("change", applyFilters);
    });
    if (showInactiveToggle) {
      showInactiveToggle.addEventListener("change", applyFilters);
    }
    applyFilters();
  }

  ready(function () {
    var table = getModsTable();
    if (!table) return;
    removeOriginalColumn(table);
    applyCompactHeaders(table);
    buildFilters(table);
  });
})();

