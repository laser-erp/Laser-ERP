/**
 * Сортировка строк инлайна этапов техпроцесса: обновляет только поля order (1..n).
 */
(function () {
  "use strict";

  function getDataRows(tbody) {
    return Array.prototype.filter.call(
      tbody.querySelectorAll("tr.form-row"),
      function (tr) {
        return !tr.classList.contains("empty-form");
      }
    );
  }

  function renumberOrders(tbody) {
    var rows = getDataRows(tbody);
    for (var i = 0; i < rows.length; i++) {
      var inp = rows[i].querySelector('input[name$="-order"]');
      if (inp) {
        inp.value = String(i + 1);
      }
    }
  }

  function initTechProcessStagesInline() {
    var group = document.querySelector(".tech-process-stages-inline");
    if (!group) {
      return;
    }
    var tbody = group.querySelector("tbody");
    if (!tbody) {
      return;
    }

    renumberOrders(tbody);

    var dragRow = null;

    function onDragStart(e) {
      var handle = e.target.closest(".tp-drag-handle");
      if (!handle) {
        return;
      }
      dragRow = handle.closest("tr.form-row");
      if (!dragRow || dragRow.classList.contains("empty-form")) {
        e.preventDefault();
        return;
      }
      e.dataTransfer.effectAllowed = "move";
      try {
        e.dataTransfer.setData("text/plain", "tp-stage");
      } catch (err) {}
      dragRow.classList.add("tp-row-dragging");
    }

    function onDragEnd() {
      if (dragRow) {
        dragRow.classList.remove("tp-row-dragging");
      }
      dragRow = null;
    }

    function onDragOver(e) {
      var row = e.target.closest("tr.form-row");
      if (!row || row.classList.contains("empty-form") || row === dragRow) {
        return;
      }
      if (!dragRow) {
        return;
      }
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      var rect = row.getBoundingClientRect();
      var before = e.clientY < rect.top + rect.height / 2;
      tbody.insertBefore(
        dragRow,
        before ? row : row.nextSibling
      );
    }

    function onDrop(e) {
      e.preventDefault();
      renumberOrders(tbody);
    }

    group.addEventListener("dragstart", onDragStart);
    group.addEventListener("dragend", onDragEnd);
    group.addEventListener("dragover", onDragOver);
    group.addEventListener("drop", onDrop);

    group.querySelectorAll(".tp-drag-handle").forEach(function (h) {
      h.setAttribute("draggable", "true");
    });

    var observer = new MutationObserver(function () {
      group.querySelectorAll(".tp-drag-handle").forEach(function (h) {
        if (h.getAttribute("draggable") !== "true") {
          h.setAttribute("draggable", "true");
        }
      });
      renumberOrders(tbody);
    });
    observer.observe(tbody, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTechProcessStagesInline);
  } else {
    initTechProcessStagesInline();
  }
})();
