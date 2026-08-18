/**
 * Запасной вариант, если нет CSS field-sizing: content — ширина в ch по значению/placeholder.
 * Плюс подписка на новые узлы (инлайны, Select2).
 */
(function () {
  "use strict";

  /** Минимальная ширина пустого поля в ch (ширина растёт по значению/placeholder) */
  var MIN_CH = 4;
  /** Верхний предел в ch для браузеров без field-sizing (не режем длинный текст; max-width: 100% в CSS) */
  var MAX_CH = 96;
  var SELECT_PAD_CH = 4;

  function fieldSizingSupported() {
    return typeof CSS !== "undefined" && CSS.supports && CSS.supports("field-sizing", "content");
  }

  function shouldSkipInput(el) {
    if (!el || el.nodeName !== "INPUT") return true;
    var t = el.type;
    if (
      t === "hidden" ||
      t === "checkbox" ||
      t === "radio" ||
      t === "file" ||
      t === "submit" ||
      t === "button" ||
      t === "reset" ||
      t === "image" ||
      t === "password"
    ) {
      return true;
    }
    if (el.name === "csrfmiddlewaretoken") return true;
    if (el.closest && el.closest(".material-cl-search")) return true;
    if (el.disabled) return true;
    return false;
  }

  function chFromText(s, minCh, maxCh) {
    var len = String(s || "").length;
    return Math.min(maxCh, Math.max(minCh, len + 1));
  }

  function autosizeInput(el) {
    if (shouldSkipInput(el)) return;
    var base = el.value || el.placeholder || "";
    var ch = chFromText(base, MIN_CH, MAX_CH);
    el.style.boxSizing = "content-box";
    el.style.width = ch + "ch";
    el.style.maxWidth = "100%";
  }

  function shouldSkipSelect(el) {
    if (!el || el.nodeName !== "SELECT" || el.multiple) return true;
    if (el.classList.contains("admin-autocomplete")) return true;
    if (el.classList.contains("select2-hidden-accessible")) return true;
    if (el.closest && el.closest(".related-widget-wrapper")) return true;
    return false;
  }

  function autosizeSelect(el) {
    if (shouldSkipSelect(el)) return;
    var opt = el.options[el.selectedIndex];
    var text = opt ? String(opt.text || opt.value || "") : "";
    var ch = Math.min(MAX_CH, Math.max(MIN_CH, text.length + SELECT_PAD_CH));
    el.style.boxSizing = "content-box";
    el.style.width = ch + "ch";
    el.style.maxWidth = "100%";
  }

  function autosizeTextarea(el) {
    if (!el || el.nodeName !== "TEXTAREA") return;
    el.style.boxSizing = "border-box";
    el.style.width = "100%";
    el.style.maxWidth = "100%";
    el.style.height = "auto";
    el.style.minHeight = "4.5em";
    el.style.overflowY = "hidden";
    el.style.height = el.scrollHeight + "px";
  }

  function scanRoot(root) {
    if (!root || !root.querySelectorAll) return;
    var i;
    var inputs = root.querySelectorAll(
      [
        "input.vTextField",
        "input.vIntegerField",
        "input.vBigIntegerField",
        "input.vForeignKeyRawIdAdminField",
        "input.vDateField",
        "input.vTimeField",
        "input.vDateTimeField",
        "input.vUUIDField",
        'input[type="text"]',
        'input[type="search"]',
        'input[type="number"]',
        'input[type="email"]',
        'input[type="url"]',
      ].join(", ")
    );
    for (i = 0; i < inputs.length; i++) {
      autosizeInput(inputs[i]);
    }
    var sels = root.querySelectorAll("select:not([multiple])");
    for (i = 0; i < sels.length; i++) {
      if (!shouldSkipSelect(sels[i])) autosizeSelect(sels[i]);
    }
    var tas = root.querySelectorAll("textarea");
    for (i = 0; i < tas.length; i++) {
      autosizeTextarea(tas[i]);
    }
  }

  var scheduled = false;
  function scheduleScan() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () {
      scheduled = false;
      var main = document.getElementById("content-main");
      if (main) scanRoot(main);
      var tb = document.getElementById("toolbar");
      if (tb) scanRoot(tb);
      var flt = document.getElementById("changelist-filter");
      if (flt) scanRoot(flt);
      var search = document.getElementById("changelist-search");
      if (search) scanRoot(search);
      var loginContent = document.querySelector("body.login #content-main");
      if (loginContent) scanRoot(loginContent);
    });
  }

  function bindInputs(root) {
    if (!root) return;
    root.addEventListener(
      "input",
      function (e) {
        var el = e.target;
        if (!el) return;
        if (el.nodeName === "INPUT" && !shouldSkipInput(el)) autosizeInput(el);
        else if (el.nodeName === "TEXTAREA") autosizeTextarea(el);
      },
      true
    );
    root.addEventListener(
      "change",
      function (e) {
        var el = e.target;
        if (!el) return;
        if (el.nodeName === "SELECT" && !el.multiple && !shouldSkipSelect(el)) autosizeSelect(el);
        else if (el.nodeName === "INPUT" && !shouldSkipInput(el)) autosizeInput(el);
      },
      true
    );
  }

  function init() {
    /* При поддержке field-sizing достаточно admin_autosize_fields.css (без inline width) */
    if (fieldSizingSupported()) {
      return;
    }

    scheduleScan();
    bindInputs(document);

    var main = document.getElementById("content-main");
    if (main) {
      var mo = new MutationObserver(function () {
        scheduleScan();
      });
      mo.observe(main, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
