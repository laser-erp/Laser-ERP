/**
 * Черновики страниц «Добавить» в Django admin: localStorage + автосохранение.
 * Для любой модели с URL …/add/ (товары, услуги, заказы, склады и т.д.).
 */
(function () {
  "use strict";

  var PREFIX = "laser_admin_draft:";
  var DEBOUNCE_MS = 450;

  function isAdminAddPage() {
    var path = window.location.pathname.replace(/\/+$/, "") || "";
    return /\/add$/.test(path);
  }

  function getMainForm() {
    var main = document.querySelector("#content-main");
    if (!main) return null;
    var forms = main.querySelectorAll("form");
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      if (f.method && f.method.toLowerCase() === "post" && f.querySelector('[name="csrfmiddlewaretoken"]')) {
        return f;
      }
    }
    return forms[0] || null;
  }

  function draftKey() {
    return PREFIX + window.location.pathname + window.location.search;
  }

  function escCss(s) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
      return CSS.escape(s);
    }
    return String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function collectDraft(form) {
    var data = {};
    var els = form.elements;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!el.name || el.disabled) continue;
      if (el.name === "csrfmiddlewaretoken") continue;
      var type = (el.type || "").toLowerCase();
      if (type === "file" || type === "submit" || type === "button" || type === "image") continue;
      if (type === "hidden" && el.name.indexOf("__prefix__") !== -1) continue;
      if (type === "password") continue;

      if (type === "checkbox") {
        data["cb:" + el.name] = { k: "cb", n: el.name, c: el.checked, v: el.value };
        continue;
      }
      if (type === "radio") {
        if (el.checked) {
          data["rb:" + el.name] = { k: "rb", n: el.name, v: el.value };
        }
        continue;
      }
      if (el.tagName === "SELECT" && el.multiple) {
        var arr = [];
        for (var j = 0; j < el.options.length; j++) {
          if (el.options[j].selected) arr.push(el.options[j].value);
        }
        data["sm:" + el.name] = { k: "sm", n: el.name, v: arr };
        continue;
      }
      data["s:" + el.name] = { k: "s", n: el.name, v: el.value };
    }
    return data;
  }

  function draftHasContent(fields) {
    if (!fields || typeof fields !== "object") return false;
    var keys = Object.keys(fields);
    if (!keys.length) return false;
    for (var i = 0; i < keys.length; i++) {
      var item = fields[keys[i]];
      if (!item || !item.k) continue;
      if (item.k === "cb" && item.c) return true;
      if (item.k === "rb" && item.v && String(item.v).trim() !== "") return true;
      if (item.k === "sm" && item.v && item.v.length) return true;
      if (item.k === "s" && item.v != null && String(item.v).trim() !== "") return true;
    }
    return false;
  }

  function hasChangedFromInitial(current, initial) {
    try {
      return JSON.stringify(current || {}) !== JSON.stringify(initial || {});
    } catch (e) {
      return true;
    }
  }

  function saveDraft(form, initialData) {
    try {
      var data = collectDraft(form);
      if (!hasChangedFromInitial(data, initialData) || !draftHasContent(data)) {
        localStorage.removeItem(draftKey());
        return;
      }
      localStorage.setItem(
        draftKey(),
        JSON.stringify({ v: 1, savedAt: Date.now(), fields: data })
      );
    } catch (e) {}
  }

  function clearDraft() {
    try {
      localStorage.removeItem(draftKey());
    } catch (e) {}
  }

  function setInputValue(el, val) {
    if (!el) return;
    el.value = val;
    try {
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (e) {}
  }

  function restoreDraft(form, rawString) {
    var parsed;
    try {
      parsed = JSON.parse(rawString);
    } catch (e) {
      return;
    }
    if (!parsed || !parsed.fields) return;
    var fields = parsed.fields;

    Object.keys(fields).forEach(function (key) {
      var item = fields[key];
      if (!item || !item.k) return;

      if (item.k === "rb") {
        var rlist = form.querySelectorAll('input[type="radio"][name="' + escCss(item.n) + '"]');
        for (var r = 0; r < rlist.length; r++) {
          rlist[r].checked = rlist[r].value === item.v;
        }
        return;
      }

      if (item.k === "cb") {
        var cx = form.elements[item.n];
        if (cx && cx.length !== undefined && !cx.tagName) {
          for (var c = 0; c < cx.length; c++) {
            if (cx[c].type === "checkbox" && cx[c].value === item.v) {
              cx[c].checked = item.c;
              break;
            }
          }
          if (cx.length === 1 && cx[0].type === "checkbox") {
            cx[0].checked = item.c;
          }
        } else if (cx && cx.type === "checkbox") {
          cx.checked = item.c;
        }
        return;
      }

      if (item.k === "sm") {
        var sel = form.elements[item.n];
        if (!sel || sel.tagName !== "SELECT") return;
        var vals = item.v || [];
        for (var o = 0; o < sel.options.length; o++) {
          sel.options[o].selected = vals.indexOf(sel.options[o].value) !== -1;
        }
        try {
          sel.dispatchEvent(new Event("change", { bubbles: true }));
        } catch (e2) {}
        return;
      }

      if (item.k === "s") {
        var el = form.elements[item.n];
        if (!el) return;
        if (el.length && !el.tagName) {
          var first = el[0];
          if (first && first.type === "radio") {
            for (var ri = 0; ri < el.length; ri++) {
              el[ri].checked = el[ri].value === item.v;
            }
            return;
          }
          setInputValue(first, item.v);
          return;
        }
        if (el.tagName === "SELECT" || el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
          setInputValue(el, item.v);
        }
      }
    });
  }

  function getDraftDialogText(savedAtTs) {
    var defaultTitle = "Несохранённый черновик";
    var savedAtText = "";
    if (savedAtTs) {
      try {
        savedAtText =
          " Дата черновика: " +
          new Date(savedAtTs).toLocaleString("ru-RU", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
          }) +
          ".";
      } catch (e) {}
    }
    var defaultMessage =
      "У вас есть несохранённый черновик. Продолжить заполнение?" + savedAtText;

    var h1 = document.querySelector("#content h1, #content-main h1");
    if (!h1) {
      return { title: defaultTitle, message: defaultMessage };
    }

    var raw = String(h1.textContent || "").replace(/\s+/g, " ").trim();
    if (!raw) {
      return { title: defaultTitle, message: defaultMessage };
    }

    var section = raw
      .replace(/^Добавить\s+/i, "")
      .replace(/^Изменить\s+/i, "")
      .replace(/^Create\s+/i, "")
      .replace(/^Change\s+/i, "")
      .trim();

    if (!section) {
      return { title: defaultTitle, message: defaultMessage };
    }

    return {
      title: defaultTitle,
      message:
        'У вас есть несохранённый черновик в разделе «' +
        section +
        "». Продолжить заполнение?" +
        savedAtText,
    };
  }

  function showModal(savedAtTs, onContinue, onNew, onDelete) {
    var text = getDraftDialogText(savedAtTs);
    var overlay = document.createElement("div");
    overlay.className = "laser-draft-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "laser-draft-title");
    overlay.innerHTML =
      '<div class="laser-draft-modal">' +
      '<h2 id="laser-draft-title">' + text.title + "</h2>" +
      "<p>" + text.message + "</p>" +
      '<div class="laser-draft-actions">' +
      '<button type="button" class="laser-draft-primary" data-act="yes">Продолжить</button>' +
      '<button type="button" data-act="new">Новый</button>' +
      '<button type="button" data-act="delete">Удалить черновик</button>' +
      "</div></div>";

    overlay.querySelector('[data-act="yes"]').addEventListener("click", function () {
      onContinue();
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    });
    overlay.querySelector('[data-act="new"]').addEventListener("click", function () {
      onNew();
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    });
    overlay.querySelector('[data-act="delete"]').addEventListener("click", function () {
      onDelete();
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    });

    document.body.appendChild(overlay);
  }

  function init() {
    if (!isAdminAddPage()) return;
    var form = getMainForm();
    if (!form) return;
    var initialData = collectDraft(form);

    var key = draftKey();
    var raw = null;
    try {
      raw = localStorage.getItem(key);
    } catch (e) {
      return;
    }

    var parsed = null;
    if (raw) {
      try {
        parsed = JSON.parse(raw);
      } catch (e2) {
        try {
          localStorage.removeItem(key);
        } catch (e3) {}
      }
    }

    var debounceTimer = null;
    function scheduleSave() {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        saveDraft(form, initialData);
      }, DEBOUNCE_MS);
    }

    function flushSave() {
      if (debounceTimer) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      saveDraft(form, initialData);
    }

    var started = false;
    function bindAutosave() {
      if (started) return;
      started = true;
      form.addEventListener("input", scheduleSave, true);
      form.addEventListener("change", scheduleSave, true);
      form.addEventListener("submit", function () {
        clearDraft();
      });
      window.addEventListener("beforeunload", flushSave);
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") flushSave();
      });
    }

    if (parsed && parsed.fields && draftHasContent(parsed.fields)) {
      showModal(
        parsed.savedAt,
        function () {
          restoreDraft(form, raw);
          bindAutosave();
          scheduleSave();
        },
        function () {
          clearDraft();
          window.location.reload();
        },
        function () {
          clearDraft();
          bindAutosave();
        }
      );
    } else {
      bindAutosave();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
