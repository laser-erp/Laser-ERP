/**
 * Производственное задание: вкладки, перенос поля «Название» и инлайнов в панели.
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

  function moveEl(selector, target) {
    var el = document.querySelector(selector);
    var t = document.querySelector(target);
    if (el && t) {
      t.appendChild(el);
    }
  }

  function setupTabs(root) {
    var tabs = root.querySelectorAll(".pa-view-tab");
    var panels = root.querySelectorAll(".pa-tab-panel");
    function show(name) {
      tabs.forEach(function (btn) {
        var on = btn.getAttribute("data-pa-tab") === name;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      });
      panels.forEach(function (p) {
        var on = p.getAttribute("data-pa-panel") === name;
        if (on) {
          p.removeAttribute("hidden");
        } else {
          p.setAttribute("hidden", "hidden");
        }
      });
    }
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        show(btn.getAttribute("data-pa-tab"));
      });
    });
  }

  ready(function () {
    if (!document.body.classList.contains("production-assignment-doc")) {
      return;
    }

    moveEl(".form-row.field-name", "#pa-name-slot");
    moveEl(".form-row.field-reserve_materials", "#pa-reserve-slot");
    moveEl(".form-row.field-expectation", "#pa-expectation-field-wrap");

    var form = document.querySelector("body.production-assignment-doc form");
    var submitSlot = document.querySelector("#pa-submit-slot");
    if (form && submitSlot) {
      var submitRows = form.querySelectorAll(".submit-row");
      if (submitRows.length > 0) {
        submitSlot.appendChild(submitRows[0]);
      }
    }

    var shell = document.querySelector(".pa-doc-shell");
    if (shell) {
      setupTabs(shell);
    }

    moveEl("#productionassignmentitem_set-group", "#pa-inline-items-slot");
    moveEl("#deviations-group", "#pa-inline-items-slot");
  });
})();
