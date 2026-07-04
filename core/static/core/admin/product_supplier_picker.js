/**
 * Поле «Контрагент» (id_supplier): кнопка «+» — создание записи в справочнике контрагентов.
 */
(function () {
  "use strict";

  function getAddUrl() {
    if (window.PRODUCT_SUPPLIER_NEW_ORG_URL) {
      return String(window.PRODUCT_SUPPLIER_NEW_ORG_URL);
    }
    return "/admin/core/organization/add/";
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var sel = document.getElementById("id_supplier");
    if (!sel || !sel.classList.contains("admin-autocomplete")) return;

    var wrap = sel.closest(".related-widget-wrapper");
    if (!wrap) return;

    if (wrap.querySelector(".product-supplier-plus-btn")) return;

    var plus = document.createElement("a");
    plus.href = getAddUrl();
    plus.className = "product-supplier-plus-btn";
    plus.setAttribute("role", "button");
    plus.setAttribute("aria-label", "Создать нового контрагента");
    plus.setAttribute("title", "Создать нового контрагента");
    plus.target = "_blank";
    plus.rel = "noopener noreferrer";
    plus.appendChild(document.createTextNode("+"));
    wrap.appendChild(plus);
    if (typeof window.productSupplierLayoutApply === "function") {
      window.productSupplierLayoutApply();
    }
  }

  function tryInit() {
    init();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      tryInit();
      window.setTimeout(tryInit, 300);
      window.setTimeout(tryInit, 800);
    });
  } else {
    tryInit();
    window.setTimeout(tryInit, 300);
    window.setTimeout(tryInit, 800);
  }
})();
