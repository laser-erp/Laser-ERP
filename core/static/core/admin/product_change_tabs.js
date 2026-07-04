/**
 * Вкладки под основной карточкой товара: модификации, упаковка, идентификация, …, штрихкоды.
 */
(function () {
  "use strict";

  var ALL_TABS = [
    { label: "Цены", selector: "fieldset.product-extra-fs--prices" },
    { label: "Модификации", selector: "fieldset.product-extra-inline--modifications" },
    { label: "Упаковка", selector: "fieldset.product-extra-fs--packaging" },
    { label: "Остатки и учёт", selector: "fieldset.product-extra-fs--stock" },
    { label: "Аналоги", selector: "fieldset.product-extra-inline--analog" },
    { label: "Штрихкоды", selector: "fieldset.product-extra-inline--barcode" },
  ];

  function findForm() {
    return document.getElementById("product_form");
  }

  function buildTabs(anchor, tabsDef) {
    var host = document.createElement("div");
    host.id = "product-extra-tabs";
    host.className = "product-extra-tabs product-form-tabs-host";

    var bar = document.createElement("div");
    bar.className = "product-extra-tabs-bar";
    bar.setAttribute("role", "tablist");

    var panelsWrap = document.createElement("div");
    panelsWrap.className = "product-extra-tabs-panels";

    var tabs = [];
    var panels = [];

    for (var i = 0; i < tabsDef.length; i++) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "product-extra-tab" + (i === 0 ? " active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", i === 0 ? "true" : "false");
      btn.setAttribute("data-tab-index", String(i));
      btn.textContent = tabsDef[i].label;
      bar.appendChild(btn);
      tabs.push(btn);

      var panel = document.createElement("div");
      panel.className = "product-extra-tab-panel" + (i === 0 ? " active" : "");
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("data-tab-index", String(i));
      panelsWrap.appendChild(panel);
      panels.push(panel);
    }

    host.appendChild(bar);
    host.appendChild(panelsWrap);
    var mount = document.getElementById("product-extra-tabs-mount");
    if (mount) {
      mount.appendChild(host);
    } else {
      anchor.insertAdjacentElement("afterend", host);
    }

    return { host: host, tabs: tabs, panels: panels };
  }

  function moveIntoPanels(panels, tabsDef) {
    var form = findForm();
    if (!form) return;

    for (var i = 0; i < tabsDef.length; i++) {
      var el = form.querySelector(tabsDef[i].selector);
      if (el) {
        var pack = el.closest(".product-main-section");
        panels[i].appendChild(pack || el);
      }
    }

    var help = document.querySelector(".product-barcode-help");
    if (help) {
      for (var j = 0; j < panels.length; j++) {
        if (panels[j].querySelector("fieldset.product-extra-inline--barcode")) {
          panels[j].insertBefore(help, panels[j].firstChild);
          break;
        }
      }
    }
  }

  function setActive(ui, index) {
    for (var i = 0; i < ui.tabs.length; i++) {
      var on = i === index;
      ui.tabs[i].classList.toggle("active", on);
      ui.tabs[i].setAttribute("aria-selected", on ? "true" : "false");
      ui.panels[i].classList.toggle("active", on);
    }
  }

  function firstPanelWithErrors(ui) {
    for (var i = 0; i < ui.panels.length; i++) {
      if (ui.panels[i].querySelector(".errorlist")) {
        return i;
      }
    }
    return 0;
  }

  function init() {
    if (!document.body.classList.contains("model-product")) return;
    var anchor = document.querySelector("form#product_form fieldset.module.product-tabs-anchor");
    if (!anchor) return;

    var form = findForm();
    if (!form) return;

    var tabsDef = ALL_TABS.filter(function (t) {
      return form.querySelector(t.selector);
    });
    if (tabsDef.length === 0) return;

    var ui = buildTabs(anchor, tabsDef);
    moveIntoPanels(ui.panels, tabsDef);

    var start = firstPanelWithErrors(ui);
    setActive(ui, start);

    ui.tabs.forEach(function (btn, idx) {
      btn.addEventListener("click", function () {
        setActive(ui, idx);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
