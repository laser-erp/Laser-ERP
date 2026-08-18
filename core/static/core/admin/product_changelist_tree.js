/**
 * Раскрытие / сворачивание веток дерева групп (стрелка слева от «Товары» / «Услуги»).
 */
(function () {
  "use strict";

  function bind() {
    document.querySelectorAll(".product-tree-toggle").forEach(function (btn) {
      if (btn.dataset.productTreeBound) return;
      btn.dataset.productTreeBound = "1";
      var panelId = btn.getAttribute("aria-controls");
      var panel = panelId ? document.getElementById(panelId) : null;
      if (!panel) return;

      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var open = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", open ? "false" : "true");
        panel.hidden = open;
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  function initGoodsSearchPlaceholder() {
    var search = document.querySelector(".product-changelist-wrap--cards input#searchbar");
    if (search && !search.getAttribute("placeholder")) {
      search.setAttribute("placeholder", "Поиск товара…");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGoodsSearchPlaceholder);
  } else {
    initGoodsSearchPlaceholder();
  }
})();
