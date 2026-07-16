(function () {
  "use strict";

  function closeAll(except) {
    document.querySelectorAll(".laser-topnav-dropdown.is-open").forEach(function (el) {
      if (el !== except) {
        el.classList.remove("is-open");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".laser-topnav-dropdown").forEach(function (wrap) {
      var trigger = wrap.querySelector(":scope > .laser-topnav-item");
      if (!trigger) {
        return;
      }
      trigger.addEventListener("click", function (ev) {
        /* На узких/тач-экранах клик открывает меню, повторный клик по ссылке — переход */
        if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
          return;
        }
        if (!wrap.classList.contains("is-open")) {
          ev.preventDefault();
          closeAll(wrap);
          wrap.classList.add("is-open");
        }
      });
    });

    document.addEventListener("click", function (ev) {
      if (!ev.target.closest(".laser-topnav-dropdown")) {
        closeAll(null);
      }
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        closeAll(null);
      }
    });
  });
})();
