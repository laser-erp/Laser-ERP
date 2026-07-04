(function () {
  "use strict";

  function ensureHint(target, id) {
    var node = document.getElementById(id);
    if (node) {
      return node;
    }
    node = document.createElement("div");
    node.id = id;
    node.className = "help";
    node.style.marginTop = "6px";
    target.parentNode.appendChild(node);
    return node;
  }

  function setHint(node, text, isError) {
    node.textContent = text || "";
    node.style.color = isError ? "#b42318" : "#0f5132";
  }

  function init() {
    var body = document.body;
    if (!body || !body.classList.contains("app-core") || !body.classList.contains("model-organization")) {
      return;
    }
    var meta = document.getElementById("organization-bank-bik-lookup-meta");
    if (!meta) {
      return;
    }
    var lookupUrl = meta.getAttribute("data-lookup-url");
    if (!lookupUrl) {
      return;
    }

    var bikInput = document.getElementById("id_bank_bik");
    var bankNameInput = document.getElementById("id_bank_name");
    var corrInput = document.getElementById("id_bank_corr_account");
    if (!bikInput || !bankNameInput || !corrInput) {
      return;
    }

    var wrap = document.createElement("div");
    wrap.style.display = "inline-flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "8px";
    bikInput.parentNode.insertBefore(wrap, bikInput);
    wrap.appendChild(bikInput);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "button";
    btn.textContent = "Заполнить по БИК";
    btn.style.height = "30px";
    wrap.appendChild(btn);

    var hint = ensureHint(bikInput, "organization-bank-bik-hint");

    btn.addEventListener("click", function () {
      var bik = (bikInput.value || "").trim();
      if (!/^\d{9}$/.test(bik)) {
        setHint(hint, "БИК должен содержать 9 цифр.", true);
        return;
      }
      setHint(hint, "Ищем реквизиты банка...", false);
      btn.disabled = true;

      fetch(lookupUrl + "?bik=" + encodeURIComponent(bik), {
        method: "GET",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            throw new Error((result.data && result.data.error) || "Не удалось получить реквизиты.");
          }
          if (result.data.bank_name) {
            bankNameInput.value = result.data.bank_name;
          }
          if (result.data.bank_corr_account) {
            corrInput.value = result.data.bank_corr_account;
          }
          setHint(hint, "Реквизиты банка заполнены по БИК.", false);
        })
        .catch(function (err) {
          setHint(hint, err.message || "Ошибка поиска по БИК.", true);
        })
        .finally(function () {
          btn.disabled = false;
        });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
