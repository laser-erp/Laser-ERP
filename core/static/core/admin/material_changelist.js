/**
 * Список материалов: модалка фильтров, несколько значений сразу.
 */
(function () {
  "use strict";

  var KEEP_PARAMS = ["q", "o", "_popup", "_to_field", "product_kind", "wh"];

  function byId(id) {
    return document.getElementById(id);
  }

  function modalEls() {
    return {
      toggle: byId("material-filter-toggle"),
      modal: byId("material-filter-modal"),
      backdrop: byId("material-filter-backdrop"),
      closeBtn: byId("material-filter-close"),
      applyBtn: byId("material-filter-apply"),
      badge: document.querySelector("#material-filter-toggle .material-cl-filter-badge"),
    };
  }

  function selectedCount() {
    var modal = byId("material-filter-modal");
    if (!modal) {
      return 0;
    }
    return modal.querySelectorAll(".material-filter-chip input:checked").length;
  }

  function syncChipState() {
    document.querySelectorAll(".material-filter-chip").forEach(function (chip) {
      var input = chip.querySelector("input");
      chip.classList.toggle("is-selected", !!(input && input.checked));
    });
  }

  function syncBadge() {
    var els = modalEls();
    var count = selectedCount();
    if (els.toggle) {
      els.toggle.classList.toggle("is-active", count > 0);
    }
    if (!els.badge) {
      return;
    }
    if (count > 0) {
      els.badge.hidden = false;
      els.badge.textContent = String(count);
    } else {
      els.badge.hidden = true;
      els.badge.textContent = "0";
    }
  }

  function setOpen(open) {
    var els = modalEls();
    document.body.classList.toggle("material-filters-open", open);
    if (els.toggle) {
      els.toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    if (els.modal) {
      els.modal.hidden = !open;
    }
    if (els.backdrop) {
      els.backdrop.hidden = !open;
    }
  }

  function applyFilters() {
    var params = new URLSearchParams();
    var current = new URLSearchParams(window.location.search);
    KEEP_PARAMS.forEach(function (key) {
      if (current.has(key) && current.get(key)) {
        params.set(key, current.get(key));
      }
    });
    document.querySelectorAll(".material-filter-facet[data-filter-param]").forEach(function (facet) {
      var name = facet.getAttribute("data-filter-param");
      if (!name) {
        return;
      }
      var values = [];
      facet.querySelectorAll("input:checked").forEach(function (input) {
        var value = String(input.value || "").trim();
        if (value) {
          values.push(value);
        }
      });
      if (values.length) {
        params.set(name, values.join(","));
      }
    });
    var qs = params.toString();
    window.location.search = qs;
  }

  function init() {
    var search = document.querySelector(".material-cl-search input#searchbar");
    if (search) {
      search.setAttribute(
        "placeholder",
        document.body.classList.contains("model-product") ? "Поиск товара…" : "Поиск материала…"
      );
    }
    var els = modalEls();
    if (!els.toggle || !els.modal) {
      return;
    }
    syncChipState();
    syncBadge();
    els.toggle.addEventListener("click", function () {
      setOpen(els.modal.hidden);
    });
    if (els.backdrop) {
      els.backdrop.addEventListener("click", function () {
        setOpen(false);
      });
    }
    if (els.closeBtn) {
      els.closeBtn.addEventListener("click", function () {
        setOpen(false);
      });
    }
    if (els.applyBtn) {
      els.applyBtn.addEventListener("click", applyFilters);
    }
    els.modal.addEventListener("change", function (event) {
      var target = event.target;
      if (!target || target.type !== "checkbox") {
        return;
      }
      var chip = target.closest(".material-filter-chip");
      if (chip) {
        chip.classList.toggle("is-selected", target.checked);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && document.body.classList.contains("material-filters-open")) {
        setOpen(false);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
