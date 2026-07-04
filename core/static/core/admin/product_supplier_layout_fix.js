/**
 * Строка «Поставщик» (.field-supplier): минимальный JS-фикс.
 * Левое выравнивание подписи решается в CSS; здесь только стабилизация wrapper и кнопки «+».
 */
(function () {
  "use strict";

  function apply() {
    var form = document.getElementById("product_form");
    if (!form) {
      return;
    }
    var row = form.querySelector(".form-row.field-supplier");
    if (!row) {
      return;
    }

    var wrap = row.querySelector(".related-widget-wrapper");
    if (wrap) {
      wrap.style.setProperty("display", "flex", "important");
      wrap.style.setProperty("flex-direction", "row", "important");
      wrap.style.setProperty("flex-wrap", "nowrap", "important");
      wrap.style.setProperty("align-items", "center", "important");
      wrap.style.setProperty("width", "100%", "important");
      wrap.style.setProperty("min-width", "0", "important");
    }

    var plus = row.querySelector(".product-supplier-plus-btn");
    if (plus) {
      plus.style.setProperty("position", "static", "important");
      plus.style.setProperty("flex", "0 0 auto", "important");
      plus.style.setProperty("transform", "none", "important");
      plus.style.setProperty("top", "auto", "important");
      plus.style.setProperty("right", "auto", "important");
    }
  }

  function init() {
    apply();
    var form = document.getElementById("product_form");
    if (form) {
      var mo = new MutationObserver(function () {
        apply();
      });
      mo.observe(form, { childList: true, subtree: true, attributes: true });
    }
    [0, 50, 150, 400, 1000, 2500].forEach(function (ms) {
      window.setTimeout(apply, ms);
    });
    window.addEventListener("load", apply);
    var $jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    if ($jq && $jq.fn && typeof $jq.fn.select2 === "function") {
      $jq(document).on("select2:open select2:close", function () {
        window.setTimeout(apply, 0);
      });
    }
  }

  window.productSupplierLayoutApply = apply;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
