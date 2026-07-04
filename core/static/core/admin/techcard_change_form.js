/**
 * Техкарта: вкладки (Продукция / Материалы / …), перенос инлайнов в панели.
 */
(function () {
  "use strict";

  function moveLaborInlineRoot() {
    var root = document.getElementById("tc-ms-labor-inline-root");
    var panel = document.getElementById("tc-ms-panel-money");
    if (!root || !panel) return;
    while (root.firstChild) {
      panel.appendChild(root.firstChild);
    }
    root.remove();
  }

  function moveMaterialsInlineRoot() {
    var root = document.getElementById("tc-ms-items-inline-root");
    var panel = document.getElementById("tc-ms-panel-materials");
    if (!root || !panel) return;
    while (root.firstChild) {
      panel.appendChild(root.firstChild);
    }
    root.remove();
  }

  function bindTechProcessTabsVisibility() {
    var section = document.getElementById("tc-ms-tabbed-section");
    var tp = document.getElementById("id_tech_process");
    if (!tp) return;

    function wrapEl() {
      return document.querySelector(".field-tech_process .related-widget-wrapper");
    }

    function hasSelection() {
      var v = tp.value;
      return v != null && String(v).trim() !== "";
    }

    function sync() {
      var show = hasSelection();
      var wrap = wrapEl();
      if (section) {
        if (show) {
          section.removeAttribute("hidden");
        } else {
          section.setAttribute("hidden", "hidden");
        }
      }
      if (wrap) {
        wrap.classList.toggle("tc-tp-has-value", show);
      }
    }

    function syncSoon() {
      sync();
      window.setTimeout(sync, 0);
      window.setTimeout(sync, 50);
    }

    tp.addEventListener("change", syncSoon);
    document.addEventListener("change", function (e) {
      if (e.target && e.target.id === "id_tech_process") syncSoon();
    });

    var jq = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
    if (jq && jq.fn && jq.fn.select2) {
      jq(tp).on(
        "select2:select select2:clear select2:unselect select2:close change",
        syncSoon
      );
    }

    syncSoon();
    window.setTimeout(syncSoon, 150);
    window.setTimeout(syncSoon, 400);
  }

  function initTabs() {
    var section = document.getElementById("tc-ms-tabbed-section");
    if (!section) return;
    var tabs = section.querySelectorAll(".tc-ms-ptab");
    var panels = section.querySelectorAll(".tc-ms-ppanel");

    function activate(name) {
      tabs.forEach(function (t) {
        var on = t.getAttribute("data-tcms") === name;
        t.classList.toggle("active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
      });
      panels.forEach(function (p) {
        var on = p.getAttribute("data-tcms") === name;
        p.classList.toggle("active", on);
        if (on) {
          p.removeAttribute("hidden");
        } else {
          p.setAttribute("hidden", "hidden");
        }
      });
      if (window.dispatchEvent) {
        window.dispatchEvent(new CustomEvent("tc-ms-tab-activate", { detail: { name: name } }));
      }
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        activate(tab.getAttribute("data-tcms"));
      });
    });
    activate("product");
  }

  /**
   * Перед сохранением техкарты: подставить в скрытую таблицу инлайна значения из зеркал и data-*.
   * Иначе в POST не попадают product / quantity — строки «комплектующие» теряются или считаются пустыми.
   */
  function syncTechcardInlineBeforeSubmit() {
    document.querySelectorAll(".techcard-items-inline-group").forEach(function (group) {
      group.querySelectorAll("tbody tr.form-row").forEach(function (tr) {
        if (tr.classList.contains("empty-form") || tr.classList.contains("add-row")) {
          return;
        }
        var pid = (tr.getAttribute("data-product-id") || "").trim();
        var inpP = tr.querySelector('input[name$="-product"]');
        if (inpP && pid) {
          inpP.value = pid;
        }
        var ik = (tr.getAttribute("data-item-kind") || "").trim();
        var ikEl = tr.querySelector('select[name$="-item_kind"], input[name$="-item_kind"]');
        if (ikEl && ik) {
          ikEl.value = ik;
        }
      });
      group.querySelectorAll(".tc-item-card").forEach(function (card) {
        var rid = (card.getAttribute("data-row-id") || "").trim();
        if (!rid) {
          return;
        }
        var row = document.getElementById(rid);
        if (!row) {
          return;
        }
        var cq = card.querySelector(".tc-item-card-qty");
        var bq = row.querySelector('[name$="-quantity"]');
        if (cq && bq) {
          bq.value = cq.value;
        }
      });
    });
    document.querySelectorAll("#tc-ms-product-composition-tbody tr.tc-ms-product-comp-row").forEach(function (mrow) {
      var rid = (mrow.getAttribute("data-row-id") || "").trim();
      if (!rid) {
        return;
      }
      var backend = document.getElementById(rid);
      if (!backend) {
        return;
      }
      var mq = mrow.querySelector(".tc-item-card-qty");
      var bq = backend.querySelector('[name$="-quantity"]');
      if (mq && bq) {
        bq.value = mq.value;
      }
    });
  }

  /**
   * Поля инлайна «Материалы» лежат во вкладке с display:none — часть окружений не шлёт их в POST.
   * Перед отправкой формы показываем все панели вкладок (страница сразу уходит на редирект).
   */
  function bindSubmitUnhideTabPanels() {
    var form = document.querySelector("#content-main form[method='post']");
    var section = document.getElementById("tc-ms-tabbed-section");
    if (!form) {
      return;
    }
    form.addEventListener(
      "submit",
      function () {
        syncTechcardInlineBeforeSubmit();
        if (section) {
          section.removeAttribute("hidden");
          section.querySelectorAll(".tc-ms-ppanel").forEach(function (p) {
            p.removeAttribute("hidden");
            p.style.setProperty("display", "block", "important");
          });
        }
      },
      true
    );
  }

  /**
   * Таблица состава «Продукция»: перетаскивание правого края заголовков «Наименование» и «Норма»
   * меняет ширину столбцов (как ручки в шапке материалов). Ширина «Наименование» хранится в localStorage.
   */
  function bindProductCompositionColumnResize() {
    var wrap = document.querySelector("#tc-ms-panel-product .tc-ms-product-table-wrap");
    var table = wrap && wrap.querySelector(".tc-ms-product-composition-table");
    if (!table || (wrap.dataset && wrap.dataset.tcProdColResizeBound)) {
      return;
    }
    wrap.dataset.tcProdColResizeBound = "1";

    var colName = table.querySelector(".tc-ms-product-col-name-col");
    var colNorm = table.querySelector(".tc-ms-product-col-norm-col");
    var colAct = table.querySelector(".tc-ms-product-col-actions-col");
    var thName = table.querySelector(".tc-ms-product-th-name");
    var thNorm = table.querySelector(".tc-ms-product-th-norm");
    if (!colName || !colNorm || !colAct || !thName || !thNorm) {
      return;
    }

    var LS_NAME = "techcardProductCompNamePx";
    var MIN_NAME = 140;
    var MIN_NORM = 100;
    var ACTION_W = 44;

    function poolW() {
      var rect = table.getBoundingClientRect();
      var fudge = 6;
      return Math.max(MIN_NAME + MIN_NORM, Math.floor(rect.width - ACTION_W - fudge));
    }

    function getStoredName() {
      var v = parseInt(localStorage.getItem(LS_NAME), 10);
      return isFinite(v) && v >= MIN_NAME ? v : null;
    }

    function setStoredName(w) {
      try {
        localStorage.setItem(LS_NAME, String(Math.round(w)));
      } catch (e) {}
    }

    function apply() {
      var pool = poolW();
      var nameW = getStoredName();
      if (nameW == null) {
        nameW = Math.round(pool * 0.58);
      }
      nameW = Math.max(MIN_NAME, Math.min(nameW, pool - MIN_NORM));
      var normW = pool - nameW;
      colName.style.width = nameW + "px";
      colNorm.style.width = normW + "px";
      colAct.style.width = ACTION_W + "px";
    }

    function ensureResizers() {
      if (!thName.querySelector(".tc-ms-product-col-resizer")) {
        var sp1 = document.createElement("span");
        sp1.className = "tc-col-resizer tc-ms-product-col-resizer";
        sp1.setAttribute("role", "separator");
        sp1.setAttribute("aria-orientation", "vertical");
        sp1.setAttribute("data-tc-edge", "name-norm");
        sp1.title = "Ширина столбцов «Наименование» и «Норма»";
        thName.appendChild(sp1);
      }
      if (!thNorm.querySelector(".tc-ms-product-col-resizer")) {
        var sp2 = document.createElement("span");
        sp2.className = "tc-col-resizer tc-ms-product-col-resizer";
        sp2.setAttribute("role", "separator");
        sp2.setAttribute("aria-orientation", "vertical");
        sp2.setAttribute("data-tc-edge", "norm-actions");
        sp2.title = "Ширина столбца «Норма»";
        thNorm.appendChild(sp2);
      }
    }

    ensureResizers();
    apply();

    var drag = null;

    function startDrag(ev, edge) {
      ev.preventDefault();
      var clientX =
        ev.type.indexOf("touch") === 0 ? ev.touches[0].clientX : ev.clientX;
      drag = {
        edge: edge,
        startX: clientX,
        startName: colName.getBoundingClientRect().width,
        startNorm: colNorm.getBoundingClientRect().width,
      };
      document.body.style.cursor = "col-resize";
    }

    function moveDrag(ev) {
      if (!drag) {
        return;
      }
      var clientX =
        ev.type.indexOf("touch") === 0 ? ev.touches[0].clientX : ev.clientX;
      var dx = clientX - drag.startX;
      var pool = poolW();
      var nameW;
      if (drag.edge === "name-norm") {
        nameW = drag.startName + dx;
      } else {
        nameW = pool - (drag.startNorm + dx);
      }
      nameW = Math.max(MIN_NAME, Math.min(nameW, pool - MIN_NORM));
      colName.style.width = nameW + "px";
      colNorm.style.width = pool - nameW + "px";
    }

    function endDrag() {
      if (!drag) {
        return;
      }
      var pool = poolW();
      var nameW = colName.getBoundingClientRect().width;
      nameW = Math.max(MIN_NAME, Math.min(nameW, pool - MIN_NORM));
      setStoredName(nameW);
      apply();
      drag = null;
      document.body.style.cursor = "";
    }

    wrap.addEventListener("mousedown", function (e) {
      var t = e.target;
      if (!t || !t.closest) {
        return;
      }
      var r = t.closest(".tc-ms-product-col-resizer");
      if (!r || !table.contains(r)) {
        return;
      }
      startDrag(e, r.getAttribute("data-tc-edge"));
    });

    document.addEventListener("mousemove", function (e) {
      if (!drag) {
        return;
      }
      e.preventDefault();
      moveDrag(e);
    });
    document.addEventListener("mouseup", endDrag);

    wrap.addEventListener(
      "touchstart",
      function (e) {
        var t = e.target;
        if (!t || !t.closest) {
          return;
        }
        var r = t.closest(".tc-ms-product-col-resizer");
        if (!r || !table.contains(r)) {
          return;
        }
        startDrag(e, r.getAttribute("data-tc-edge"));
      },
      { passive: false }
    );
    document.addEventListener(
      "touchmove",
      function (e) {
        if (!drag) {
          return;
        }
        e.preventDefault();
        moveDrag(e);
      },
      { passive: false }
    );
    document.addEventListener("touchend", endDrag);
    document.addEventListener("touchcancel", endDrag);

    var resizeTimer;
    window.addEventListener("resize", function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(apply, 100);
    });

    window.addEventListener("tc-ms-tab-activate", function (ev) {
      if (ev && ev.detail && ev.detail.name === "product") {
        window.setTimeout(apply, 50);
      }
    });
  }

  function run() {
    moveLaborInlineRoot();
    moveMaterialsInlineRoot();
    bindTechProcessTabsVisibility();
    bindProductCompositionColumnResize();
    initTabs();
    bindSubmitUnhideTabPanels();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
