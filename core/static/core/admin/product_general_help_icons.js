/**
 * Блок «Общие данные»: подсказка в title у кнопки «?» (при наведении), текст из панели подсказки.
 */
(function () {
  "use strict";

  function stripTags(html) {
    var d = document.createElement("div");
    d.innerHTML = html;
    return (d.textContent || d.innerText || "").replace(/\s+/g, " ").trim();
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var fs = document.querySelector("fieldset.product-fs-general");
    if (!fs) return;

    var triggers = fs.querySelectorAll(".laser-help-trigger");
    triggers.forEach(function (btn) {
      var panel = btn.getAttribute("aria-controls");
      if (!panel) return;
      var inner = document.getElementById(panel);
      if (!inner) return;
      var wrap = inner.querySelector(".laser-help-panel-inner");
      if (!wrap) return;
      var text = stripTags(wrap.innerHTML);
      if (!text) return;
      btn.setAttribute("title", text);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
