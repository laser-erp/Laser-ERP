/**
 * Переносит инлайн галереи в панель аккордеона «Изображения» (левая колонка).
 * Выполняется после product_card_sidebar.js (порядок defer в шаблоне).
 */
(function () {
  "use strict";

  function moveGalleryInline() {
    if (!document.body.classList.contains("model-product")) {
      return;
    }
    var panel = document.getElementById("product-sidebar-panel-3");
    var group = document.getElementById("gallery_images-group");
    if (!panel || !group) {
      return;
    }
    if (group.parentNode !== panel) {
      panel.appendChild(group);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", moveGalleryInline);
  } else {
    moveGalleryInline();
  }
})();
