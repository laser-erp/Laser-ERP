/**
 * Подсказки у «?»: показ по наведению (и фокусу), панель с закруглением; для ячеек таблицы — fixed у кнопки.
 */
(function () {
  "use strict";

  var OPEN_CLASS = "laser-help-panel--floating";
  var HIDE_DELAY_MS = 320;

  var hideTimer = null;

  function clearHideTimer() {
    if (hideTimer !== null) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function closePanel(panel) {
    if (!panel) return;
    panel.hidden = true;
    panel.classList.remove(OPEN_CLASS);
    panel.style.left = "";
    panel.style.top = "";
    panel.style.zIndex = "";
  }

  function closeAllPanels() {
    clearHideTimer();
    document.querySelectorAll(".laser-help-panel").forEach(closePanel);
    document.querySelectorAll(".laser-help-trigger").forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
    });
  }

  function positionFloating(panel, anchor) {
    panel.classList.add(OPEN_CLASS);
    var rect = anchor.getBoundingClientRect();
    var margin = 8;
    var top = rect.bottom + margin;
    var left = rect.left;
    panel.hidden = false;
    var pw = panel.offsetWidth || 200;
    var ph = panel.offsetHeight || 60;
    if (left + pw > window.innerWidth - 10) {
      left = Math.max(10, window.innerWidth - pw - 10);
    }
    if (top + ph > window.innerHeight - 10) {
      top = Math.max(10, rect.top - ph - margin);
    }
    panel.style.left = left + "px";
    panel.style.top = top + "px";
    panel.style.zIndex = "20000";
  }

  /** Табличные инлайны: overflow у .laser-tabular-inline-wrapper — только там fixed. */
  function useFloatingPanel(anchor) {
    if (anchor.classList.contains("laser-help-trigger--tabular-cell")) return true;
    if (anchor.closest(".laser-tabular-inline-wrapper")) return true;
    return false;
  }

  function showForAnchor(anchor, panel) {
    clearHideTimer();
    document.querySelectorAll(".laser-help-panel").forEach(function (p) {
      if (p !== panel) closePanel(p);
    });
    document.querySelectorAll(".laser-help-trigger").forEach(function (b) {
      b.setAttribute("aria-expanded", b === anchor ? "true" : "false");
    });

    panel.hidden = false;

    if (useFloatingPanel(anchor)) {
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          positionFloating(panel, anchor);
        });
      });
    } else {
      panel.classList.remove(OPEN_CLASS);
      panel.style.left = "";
      panel.style.top = "";
      panel.style.zIndex = "";
    }
  }

  function scheduleHide() {
    clearHideTimer();
    hideTimer = setTimeout(function () {
      closeAllPanels();
    }, HIDE_DELAY_MS);
  }

  function bindPanelOnce(panel) {
    if (panel.dataset.laserHelpPanelBound) return;
    panel.dataset.laserHelpPanelBound = "1";
    panel.addEventListener("mouseenter", clearHideTimer);
    panel.addEventListener("mouseleave", scheduleHide);
  }

  function bindTrigger(btn) {
    if (btn.dataset.laserHelpTriggerBound) return;
    btn.dataset.laserHelpTriggerBound = "1";
    var panelId = btn.getAttribute("aria-controls") || btn.getAttribute("data-laser-help-panel-id");
    if (!panelId) return;
    var panel = document.getElementById(panelId);
    if (!panel) return;

    bindPanelOnce(panel);

    btn.addEventListener("mouseenter", function () {
      showForAnchor(btn, panel);
    });
    btn.addEventListener("mouseleave", scheduleHide);
    btn.addEventListener("focus", function () {
      showForAnchor(btn, panel);
    });
    btn.addEventListener("blur", scheduleHide);
  }

  function scan(root) {
    if (!root) return;
    root.querySelectorAll(".laser-help-trigger").forEach(bindTrigger);
  }

  function init() {
    scan(document.body);
    var cm = document.getElementById("content-main");
    if (cm && typeof MutationObserver !== "undefined") {
      var t = null;
      var obs = new MutationObserver(function () {
        if (t) clearTimeout(t);
        t = setTimeout(function () {
          scan(cm);
        }, 80);
      });
      obs.observe(cm, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAllPanels();
  });

  window.addEventListener("resize", function () {
    closeAllPanels();
  });

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".laser-help-trigger") && !e.target.closest(".laser-help-panel")) {
      closeAllPanels();
    }
  });
})();
