/**
 * Русские подписи вместо англ. «Choose File» / «No file chosen» у input[type=file].
 * Нативный контрол скрыт CSS; если виджет без обёртки — добавляем её здесь.
 */
(function () {
  "use strict";

  var EMPTY = "Файл не выбран";
  var CHOOSE = "Выберите файл";
  var REPLACE = "Заменить";

  function isIntentionallyHidden(el) {
    if (!el || el.hidden) return true;
    if (el.classList.contains("d-none")) return true;
    var inline = (el.getAttribute("style") || "").replace(/\s/g, "").toLowerCase();
    if (inline.indexOf("display:none") !== -1) return true;
    return false;
  }

  function wrapInput(input) {
    if (!input || input.type !== "file") return;
    input.classList.add("file-upload-input", "laser-file-input-native");
    if (input.closest(".file-input-wrap")) return;
    if (isIntentionallyHidden(input)) return;

    var wrap = document.createElement("span");
    wrap.className = "file-input-wrap";
    var label = document.createElement("label");
    label.className = "file-upload-label";
    if (!input.id) {
      input.id = "laser-file-" + Math.random().toString(36).slice(2, 10);
    }
    label.htmlFor = input.id;
    label.textContent = input.getAttribute("data-has-file") ? REPLACE : CHOOSE;
    var status = document.createElement("span");
    status.className = "file-upload-status";
    status.setAttribute("data-empty-text", EMPTY);
    status.textContent = EMPTY;
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(label);
    wrap.appendChild(status);
    wrap.appendChild(input);
    function update() {
      status.textContent =
        input.files && input.files.length ? input.files[0].name : EMPTY;
    }
    input.addEventListener("change", update);
    update();
  }

  function scan(root) {
    (root || document).querySelectorAll('input[type="file"]').forEach(wrapInput);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      scan(document);
    });
  } else {
    scan(document);
  }
  document.addEventListener("formset:added", function (ev) {
    scan(ev.target || document);
  });
})();
