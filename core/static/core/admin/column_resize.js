/**
 * Ресайз колонок в таблицах changelist Django Admin.
 * Ширины сохраняются в localStorage отдельно для каждого URL списка.
 */
(function () {
  "use strict";

  /* Ресайз колонок на узком экране не нужен */
  if (window.matchMedia && !window.matchMedia("(min-width: 641px)").matches) {
    return;
  }

  var STORAGE_PREFIX = "laser-admin-col-widths:";
  var MIN_WIDTH = 72;
  var HANDLE_WIDTH = 8;

  function storageKey() {
    return STORAGE_PREFIX + window.location.pathname;
  }

  function readSavedWidths() {
    try {
      var raw = window.localStorage.getItem(storageKey());
      if (!raw) {
        return null;
      }
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : null;
    } catch (_err) {
      return null;
    }
  }

  function saveWidths(widths) {
    try {
      window.localStorage.setItem(storageKey(), JSON.stringify(widths));
    } catch (_err) {
      // localStorage может быть недоступен (private mode / policy).
    }
  }

  function isResizableHeader(th) {
    if (!th || th.classList.contains("action-checkbox-column")) {
      return false;
    }
    if (th.classList.contains("sorted")) {
      return true;
    }
    return !!th.querySelector("a, span");
  }

  function collectHeaders(table) {
    var thead = table.querySelector("thead");
    if (!thead) {
      return [];
    }
    var headers = Array.prototype.slice.call(thead.querySelectorAll("th"));
    return headers.filter(isResizableHeader);
  }

  function applyWidths(headers, widths) {
    if (!widths || !widths.length) {
      return;
    }
    headers.forEach(function (th, idx) {
      var w = Number(widths[idx]);
      if (!Number.isFinite(w) || w < MIN_WIDTH) {
        return;
      }
      th.style.width = w + "px";
      th.style.minWidth = w + "px";
      th.style.maxWidth = "none";
    });
  }

  function currentWidths(headers) {
    return headers.map(function (th) {
      return Math.round(th.getBoundingClientRect().width);
    });
  }

  function ensureStyleTag() {
    if (document.getElementById("laser-column-resize-style")) {
      return;
    }
    var style = document.createElement("style");
    style.id = "laser-column-resize-style";
    style.textContent = [
      "#result_list { table-layout: fixed; }",
      "#result_list thead th { position: relative; }",
      /* Чекбокс действий не сжимается и не прячется под «Наименование» */
      "#result_list thead th.action-checkbox-column,",
      "#result_list tbody td.action-checkbox {",
      "  width: 2.75rem !important;",
      "  min-width: 2.75rem !important;",
      "  max-width: 2.75rem !important;",
      "  box-sizing: border-box;",
      "  overflow: visible;",
      "  position: relative;",
      "  z-index: 2;",
      "  padding-left: 0.5rem;",
      "  padding-right: 0.25rem;",
      "  text-align: center;",
      "  vertical-align: middle;",
      "}",
      "#result_list tbody td.action-checkbox input,",
      "#result_list thead th.action-checkbox-column input {",
      "  position: relative;",
      "  z-index: 3;",
      "  margin: 0;",
      "}",
      /* Длинное наименование обрезается внутри своей ячейки, не наезжает на чекбокс */
      "#result_list tbody th,",
      "#result_list tbody td:not(.action-checkbox) {",
      "  overflow: hidden;",
      "  text-overflow: ellipsis;",
      "}",
      ".laser-col-resize-handle {",
      "  position: absolute;",
      "  top: 0;",
      "  right: -" + Math.floor(HANDLE_WIDTH / 2) + "px;",
      "  width: " + HANDLE_WIDTH + "px;",
      "  height: 100%;",
      "  cursor: col-resize;",
      "  user-select: none;",
      "  z-index: 3;",
      "}",
      ".laser-col-resize-handle:hover, .laser-col-resize-handle.is-active {",
      "  background: rgba(37, 99, 235, 0.16);",
      "}",
    ].join("\n");
    document.head.appendChild(style);
  }

  function pinActionCheckboxColumn(table) {
    var th = table.querySelector("thead th.action-checkbox-column");
    if (!th) {
      return;
    }
    th.style.width = "2.75rem";
    th.style.minWidth = "2.75rem";
    th.style.maxWidth = "2.75rem";
  }

  function attachHandle(table, headers, th) {
    var handle = document.createElement("span");
    handle.className = "laser-col-resize-handle";
    handle.setAttribute("aria-hidden", "true");
    th.appendChild(handle);

    handle.addEventListener("mousedown", function (event) {
      event.preventDefault();
      event.stopPropagation();

      var startX = event.clientX;
      var startWidth = th.getBoundingClientRect().width;
      handle.classList.add("is-active");
      document.body.style.cursor = "col-resize";

      function onMove(moveEvent) {
        var delta = moveEvent.clientX - startX;
        var nextWidth = Math.max(MIN_WIDTH, Math.round(startWidth + delta));
        th.style.width = nextWidth + "px";
        th.style.minWidth = nextWidth + "px";
        th.style.maxWidth = "none";
      }

      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        handle.classList.remove("is-active");
        document.body.style.cursor = "";
        saveWidths(currentWidths(headers));
      }

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  function init() {
    if (!document.body.classList.contains("change-list")) {
      return;
    }
    var table = document.getElementById("result_list");
    if (!table) {
      return;
    }

    ensureStyleTag();
    pinActionCheckboxColumn(table);
    var headers = collectHeaders(table);
    if (!headers.length) {
      return;
    }

    table.style.tableLayout = "fixed";
    applyWidths(headers, readSavedWidths());
    pinActionCheckboxColumn(table);
    headers.forEach(function (th) {
      attachHandle(table, headers, th);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
