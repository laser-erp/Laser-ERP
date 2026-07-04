/**
 * Левая колонка карточки товара: аккордеон для верхних разделов (0–3) — контент под заголовком;
 * для остальных — переход к вкладке справа, где лежит раздел.
 */
(function () {
  "use strict";

  function closeAllAccordionPanels(nav) {
    nav.querySelectorAll(".product-sidebar-accordion-panel").forEach(function (p) {
      p.hidden = true;
    });
    nav.querySelectorAll('.product-sidebar-row[data-sidebar-mode="accordion"]').forEach(function (b) {
      b.classList.remove("is-active");
      b.setAttribute("aria-expanded", "false");
    });
  }

  function openAccordionPanel(nav, panel, btn) {
    closeAllAccordionPanels(nav);
    panel.hidden = false;
    btn.classList.add("is-active");
    btn.setAttribute("aria-expanded", "true");
  }

  function toggleAccordion(nav, panel, btn) {
    var wasOpen = !panel.hidden;
    if (wasOpen) {
      closeAllAccordionPanels(nav);
      return;
    }
    openAccordionPanel(nav, panel, btn);
  }

  function activateTabForSection(section) {
    if (!section) return;
    var tabPanel = section.closest(".product-extra-tab-panel");
    if (!tabPanel) return;
    var idx = tabPanel.getAttribute("data-tab-index");
    if (idx == null) return;
    var tabBtn = document.querySelector('#product-extra-tabs .product-extra-tab[data-tab-index="' + idx + '"]');
    if (tabBtn) {
      tabBtn.click();
    }
    requestAnimationFrame(function () {
      section.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  function init() {
    if (!document.body.classList.contains("model-product")) {
      return;
    }
    var nav = document.querySelector(".product-card-sidebar__nav");
    if (!nav) {
      return;
    }

    nav.querySelectorAll(".product-sidebar-accordion-item").forEach(function (wrap) {
      var btn = wrap.querySelector(".product-sidebar-row");
      var panel = wrap.querySelector(".product-sidebar-accordion-panel");
      if (!btn) return;

      var mode = btn.getAttribute("data-sidebar-mode") || "tab";
      if (mode === "accordion" && panel) {
        var sid = btn.getAttribute("data-product-section");
        var section = sid ? document.getElementById(sid) : null;
        if (section) {
          panel.appendChild(section);
        }
        btn.setAttribute("aria-expanded", panel.hidden ? "false" : "true");

        btn.addEventListener("click", function () {
          toggleAccordion(nav, panel, btn);
        });
      } else {
        btn.addEventListener("click", function () {
          var id = btn.getAttribute("data-product-section");
          if (!id) return;
          var el = document.getElementById(id);
          if (!el) return;
          closeAllAccordionPanels(nav);
          nav.querySelectorAll(".product-sidebar-row.is-active").forEach(function (x) {
            x.classList.remove("is-active");
          });
          btn.classList.add("is-active");
          activateTabForSection(el);
        });
      }
    });

    var topGrid = document.querySelector(".product-form-fieldsets-grid--top");
    if (topGrid && !topGrid.querySelector(".product-main-section")) {
      topGrid.classList.add("product-form-fieldsets-grid--empty");
    }
    var restGrid = document.querySelector(".product-form-fieldsets-grid--rest");
    if (restGrid && !restGrid.querySelector(".product-main-section")) {
      restGrid.classList.add("product-form-fieldsets-grid--empty");
    }

    var defaultOpen = nav.querySelector('.product-sidebar-row[data-default-open="true"]');
    if (defaultOpen && defaultOpen.getAttribute("data-sidebar-mode") === "accordion") {
      var wrap = defaultOpen.closest(".product-sidebar-accordion-item");
      var p = wrap && wrap.querySelector(".product-sidebar-accordion-panel");
      if (p && defaultOpen) {
        openAccordionPanel(nav, p, defaultOpen);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
