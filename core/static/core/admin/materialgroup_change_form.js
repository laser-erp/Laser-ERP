/**
 * Карточка группы: списки бренда/цвета/зерна только при включённом флаге.
 */
(function () {
  "use strict";

  var FLAG_TO_INLINE = {
    id_has_brand: "brand_choices-group",
    id_has_color: "color_choices-group",
    id_has_grit: "grit_choices-group",
    id_has_diameter: "diameter_choices-group",
    id_has_hole_count: "hole_choices-group",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function syncInlines() {
    Object.keys(FLAG_TO_INLINE).forEach(function (flagId) {
      var checkbox = byId(flagId);
      var box = byId(FLAG_TO_INLINE[flagId]);
      if (!checkbox || !box) {
        return;
      }
      box.hidden = !checkbox.checked;
    });
  }

  function init() {
    if (
      !document.body.classList.contains("model-materialgroup") ||
      (!document.body.classList.contains("change-form") &&
        !document.body.classList.contains("add-form"))
    ) {
      return;
    }
    Object.keys(FLAG_TO_INLINE).forEach(function (flagId) {
      var checkbox = byId(flagId);
      if (checkbox) {
        checkbox.addEventListener("change", syncInlines);
      }
    });
    syncInlines();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
