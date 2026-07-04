(function () {
  "use strict";

  function initFilterToggle() {
    var btn = document.getElementById("techcard-filter-toggle");
    var panel = document.getElementById("changelist-filter");
    if (!btn || !panel) {
      return;
    }
    btn.addEventListener("click", function () {
      var open = panel.hasAttribute("hidden");
      if (open) {
        panel.removeAttribute("hidden");
        btn.setAttribute("aria-expanded", "true");
      } else {
        panel.setAttribute("hidden", "");
        btn.setAttribute("aria-expanded", "false");
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFilterToggle);
  } else {
    initFilterToggle();
  }
})();
