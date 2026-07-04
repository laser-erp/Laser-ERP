/**
 * Карточка Product: при виде «Материал» — блок группы = складские MaterialGroup;
 * при «Товар» — ProductGroup; при «Услуга» оба поля скрыты.
 */
(function () {
  "use strict";

  var KIND_GOODS = "goods";
  var KIND_SERVICE = "service";
  var KIND_MATERIAL = "material";

  function rowForField(name) {
    return document.querySelector(
      "#product_form .form-row.field-" + name + ", form#product_form .form-row.field-" + name
    );
  }

  function sync() {
    var sel = document.getElementById("id_product_kind");
    var heading = document.getElementById("product-group-block-heading");
    var rowPg = rowForField("product_group");
    var rowMg = rowForField("material_group");
    if (!sel) return;

    var k = sel.value || KIND_GOODS;

    if (rowPg) {
      rowPg.style.display = k === KIND_GOODS ? "" : "none";
    }
    if (rowMg) {
      rowMg.style.display = k === KIND_MATERIAL ? "" : "none";
    }

    if (heading) {
      if (k === KIND_GOODS) {
        heading.textContent = "Группа товаров";
        heading.style.display = "";
      } else if (k === KIND_MATERIAL) {
        heading.textContent = "Группа материалов";
        heading.style.display = "";
      } else {
        heading.textContent = "";
        heading.style.display = "none";
      }
    }
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var form = document.getElementById("product_form");
    if (!form) return;

    sync();
    form.addEventListener("change", function (e) {
      if (e.target && e.target.id === "id_product_kind") {
        sync();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
