/**
 * UX-сообщение для кнопки «Сохранить» в карточке контрагента.
 * Показывает статус до фактической отправки формы.
 */
(function () {
  "use strict";

  var SAVE_DELAY_MS = 1000;
  var FINAL_DELAY_MS = 220;

  function ensureMessageNode(form) {
    var node = document.getElementById("organization-save-status");
    if (node) {
      return node;
    }
    node = document.createElement("ul");
    node.id = "organization-save-status";
    node.className = "messagelist";
    node.innerHTML = '<li class="info">Сохранение контрагента....</li>';
    form.parentNode.insertBefore(node, form);
    return node;
  }

  function setMessage(node, text) {
    var li = node.querySelector("li");
    if (!li) {
      li = document.createElement("li");
      li.className = "info";
      node.appendChild(li);
    }
    li.textContent = text;
  }

  function init() {
    var body = document.body;
    if (!body || !body.classList.contains("app-core") || !body.classList.contains("model-organization")) {
      return;
    }
    var form = document.querySelector("#organization_form form, form#organization_form, #content-main form");
    if (!form) {
      return;
    }
    var saveBtn = form.querySelector('input[name="_save"]');
    if (!saveBtn) {
      return;
    }

    var inProgress = false;

    saveBtn.addEventListener("click", function (event) {
      if (inProgress || form.dataset.orgSaveBypass === "1") {
        return;
      }
      event.preventDefault();
      inProgress = true;
      var msgNode = ensureMessageNode(form);
      setMessage(msgNode, "Сохранение контрагента....");

      window.setTimeout(function () {
        setMessage(msgNode, "Контрагент сохранён.");
        window.setTimeout(function () {
          form.dataset.orgSaveBypass = "1";
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit(saveBtn);
          } else {
            var hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = "_save";
            hidden.value = "1";
            form.appendChild(hidden);
            form.submit();
          }
        }, FINAL_DELAY_MS);
      }, SAVE_DELAY_MS);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
