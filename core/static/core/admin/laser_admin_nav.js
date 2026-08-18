/**
 * Верхнее меню ERP: выпадающие склады на таче; фильтры списка на телефоне.
 */
(function () {
  "use strict";

  function closeDropdowns(except) {
    document.querySelectorAll(".laser-topnav-dropdown.is-open").forEach(function (el) {
      if (el !== except) {
        el.classList.remove("is-open");
      }
    });
  }

  function hasActiveFilters(filter) {
    if (!filter) {
      return false;
    }
    return Array.prototype.some.call(filter.querySelectorAll("li.selected"), function (li) {
      var first = li.parentElement && li.parentElement.querySelector("li");
      return first && li !== first;
    });
  }

  function markToggleState(open) {
    var btn = document.querySelector(".laser-changelist-filter-toggle");
    var filter = document.getElementById("changelist-filter");
    if (!btn) {
      return;
    }
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.textContent = "Фильтры";
    btn.classList.toggle("is-active", hasActiveFilters(filter));
  }

  function setFiltersOpen(open) {
    document.body.classList.toggle("laser-filters-open", open);
    markToggleState(open);
    var filter = document.getElementById("changelist-filter");
    if (filter) {
      filter.setAttribute("aria-hidden", open ? "false" : "true");
    }
  }

  function ensureBackdrop() {
    var el = document.querySelector(".laser-filter-backdrop");
    if (el) {
      return el;
    }
    el = document.createElement("button");
    el.type = "button";
    el.className = "laser-filter-backdrop";
    el.setAttribute("aria-label", "Закрыть фильтры");
    el.addEventListener("click", function () {
      setFiltersOpen(false);
    });
    document.body.appendChild(el);
    return el;
  }

  function ensureModalChrome(filter) {
    if (filter.querySelector(".laser-filter-modal-bar")) {
      return;
    }
    var bar = document.createElement("div");
    bar.className = "laser-filter-modal-bar";
    var title = document.createElement("div");
    title.className = "laser-filter-modal-title";
    title.textContent = "Фильтры";
    var close = document.createElement("button");
    close.type = "button";
    close.className = "laser-filter-modal-close";
    close.textContent = "Готово";
    bar.appendChild(title);
    bar.appendChild(close);
    filter.insertBefore(bar, filter.firstChild);
    close.addEventListener("click", function () {
      setFiltersOpen(false);
    });
  }

  function initFilters() {
    var filter = document.getElementById("changelist-filter");
    if (!filter) {
      return;
    }
    if (
      document.body.classList.contains("model-material") ||
      document.querySelector(
        "#techcard-filter-toggle, #material-filter-toggle, .ms-wh-changelist, a.btn-filter, .laser-changelist-filter-toggle"
      )
    ) {
      return;
    }
    ensureBackdrop();
    ensureModalChrome(filter);
    filter.setAttribute("role", "dialog");
    filter.setAttribute("aria-modal", "true");
    filter.setAttribute("aria-hidden", "true");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "laser-changelist-filter-toggle";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "changelist-filter");
    btn.textContent = "Фильтры";
    filter.parentNode.insertBefore(btn, filter);
    btn.addEventListener("click", function () {
      setFiltersOpen(!document.body.classList.contains("laser-filters-open"));
    });
    markToggleState(false);
  }

  function headerText(th) {
    var label = th.querySelector(".laser-th-label-text, .text");
    return ((label && label.textContent) || th.textContent || "").replace(/\s+/g, " ").trim();
  }

  function cellLooksEmpty(cell) {
    if (cell.querySelector("input, select, textarea, img, button, a, .select2, .related-widget-wrapper")) {
      return false;
    }
    var text = (cell.textContent || "").replace(/\s+/g, " ").trim();
    return !text || text === "—" || text === "-" || text === "None";
  }

  function labelsFromHead(table) {
    return Array.prototype.map.call(table.querySelectorAll("thead th"), headerText);
  }

  function decorateResultRow(tr, labels) {
    var titleDone = false;
    Array.prototype.forEach.call(tr.children, function (cell, index) {
      if (cell.classList.contains("action-checkbox")) {
        return;
      }
      if (cell.tagName === "TH" && !titleDone) {
        cell.classList.add("laser-card-title");
        titleDone = true;
        return;
      }
      var label = labels[index] || "";
      if (label) {
        cell.setAttribute("data-label", label);
      }
      if (cellLooksEmpty(cell)) {
        cell.classList.add("laser-card-empty");
      }
    });
  }

  function initResultCards() {
    if (
      document.body.classList.contains("model-material") ||
      document.body.classList.contains("model-materialgroup") ||
      document.body.classList.contains("model-productgroup") ||
      document.querySelector(".product-changelist-wrap--cards")
    ) {
      return;
    }
    var table = document.getElementById("result_list");
    if (!table || !table.tHead) {
      return;
    }
    table.classList.add("laser-result-cards");
    var labels = labelsFromHead(table);
    table.querySelectorAll("tbody tr").forEach(function (tr) {
      decorateResultRow(tr, labels);
    });
  }

  function decorateInlineRow(tr, labels) {
    Array.prototype.forEach.call(tr.children, function (cell, index) {
      if (cell.classList.contains("original") || cell.classList.contains("hidden")) {
        return;
      }
      var label = labels[index] || "";
      if (label) {
        cell.setAttribute("data-label", label);
      }
    });
  }

  function initInlineCards() {
    document.querySelectorAll(".tabular.inline-related table").forEach(function (table) {
      if (table.closest(".techcard-items-backend, .techcard-items-inline-group, .tech-process-stages-inline, #lines-group, #goodsreceiptline_set-group")) {
        return;
      }
      if (!table.tHead) {
        return;
      }
      table.classList.add("laser-inline-cards");
      var labels = labelsFromHead(table);
      table.querySelectorAll("tbody tr.form-row").forEach(function (tr) {
        decorateInlineRow(tr, labels);
      });
    });
    document.addEventListener("formset:added", function (event) {
      var row = event.target;
      if (!row || !row.closest) {
        return;
      }
      var table = row.closest("table.laser-inline-cards");
      if (!table) {
        return;
      }
      decorateInlineRow(row, labelsFromHead(table));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initFilters();
    initResultCards();
    initInlineCards();

    document.querySelectorAll(".laser-topnav-dropdown").forEach(function (wrap) {
      var trigger = wrap.querySelector(":scope > .laser-topnav-item, :scope > .laser-subnav-drop-trigger");
      if (!trigger) {
        return;
      }
      trigger.addEventListener("click", function (ev) {
        if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
          return;
        }
        if (!wrap.classList.contains("is-open")) {
          ev.preventDefault();
          closeDropdowns(wrap);
          wrap.classList.add("is-open");
        }
      });
    });

    document.addEventListener("click", function (ev) {
      if (!ev.target.closest(".laser-topnav-dropdown")) {
        closeDropdowns(null);
      }
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        closeDropdowns(null);
        setFiltersOpen(false);
      }
    });
  });
})();
