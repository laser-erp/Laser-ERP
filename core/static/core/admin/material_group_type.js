/**
 * Карточка материала: выпадающие списки типа, единицы, сорта, бренда и цвета по группе.
 */
(function () {
  "use strict";

  var lastMeta = {
    types: [],
    has_grade: false,
    grades: [],
    has_sheet_size: true,
    units: [],
    has_brand: false,
    brands: [],
    has_color: false,
    colors: [],
    has_grit: false,
    grits: [],
    has_diameter: false,
    diameters: [],
    has_hole_count: false,
    holes: [],
  };
  var lastAutoName = "";

  function metaRoot() {
    return document.getElementById("material-group-meta");
  }

  function groupInput() {
    return document.getElementById("id_group");
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function fillSelect(el, values) {
    if (!el) return;
    var current = String(el.value || "").trim();
    var seen = {};
    var items = [];
    function add(value) {
      var key = String(value || "");
      if (seen[key]) return;
      seen[key] = true;
      items.push(key);
    }
    add("");
    (values || []).forEach(add);
    if (current) add(current);
    el.innerHTML = "";
    items.forEach(function (value) {
      var opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value || "—";
      if (value === current) opt.selected = true;
      el.appendChild(opt);
    });
  }

  function setRowVisible(fieldId, visible, hiddenClass, visibleClass) {
    var el = byId(fieldId);
    if (!el) return;
    var wrap = el.closest(".form-row");
    if (!wrap) return;
    wrap.hidden = !visible;
    if (hiddenClass) wrap.classList.toggle(hiddenClass, !visible);
    if (visibleClass) wrap.classList.toggle(visibleClass, Boolean(visible));
  }

  function setTypeVisible(visible) {
    setRowVisible("id_material_type", visible, "is-type-hidden", "is-type-visible");
  }

  function setGradeVisible(visible) {
    setRowVisible("id_grade", visible, "is-grade-hidden", "is-grade-visible");
  }

  function setBrandVisible(visible) {
    setRowVisible("id_brand", visible, "is-brand-hidden", "is-brand-visible");
  }

  function setColorVisible(visible) {
    setRowVisible("id_color", visible, "is-color-hidden", "is-color-visible");
  }

  function setGritVisible(visible) {
    setRowVisible("id_grit", visible, "is-grit-hidden");
  }

  function setDiameterVisible(visible) {
    setRowVisible("id_diameter_mm", visible, "is-diameter-hidden");
  }

  function setHolesVisible(visible) {
    setRowVisible("id_hole_count", visible, "is-holes-hidden");
  }

  function sheetRows() {
    var lengthEl = byId("id_sheet_length_mm");
    var preview = byId("material-sheet-area-preview");
    var rows = [];
    if (lengthEl) {
      var dimRow = lengthEl.closest(".form-row");
      if (dimRow) rows.push(dimRow);
    }
    if (preview) {
      var prevRow = preview.closest(".form-row");
      if (prevRow && rows.indexOf(prevRow) === -1) rows.push(prevRow);
    }
    return rows;
  }

  function setSheetVisible(visible) {
    sheetRows().forEach(function (row) {
      row.hidden = !visible;
      row.classList.toggle("is-sheet-hidden", !visible);
    });
  }

  function currentType() {
    var el = byId("id_material_type");
    return el ? String(el.value || "").trim() : "";
  }

  function isStainType(value) {
    return String(value || "")
      .toLowerCase()
      .replace("ё", "е")
      .indexOf("морилк") >= 0;
  }

  function isBeltType(value) {
    return String(value || "")
      .toLowerCase()
      .replace("ё", "е")
      .indexOf("лент") >= 0;
  }

  function looksLikeStainName(value) {
    return /^Морилка водная .+ «.+»$/.test(String(value || "").trim());
  }

  function looksLikeAbrasiveName(value) {
    var s = String(value || "").trim();
    return /^Круг шлифовальный .+ \d+мм .+ отв\. \(P\d+\)$/i.test(s)
      || /^Лента шлифовальная .+ \(P\d+\)$/i.test(s);
  }

  function fieldValue(id) {
    var el = byId(id);
    return el ? String(el.value || "").trim() : "";
  }

  function syncName() {
    var nameEl = byId("id_name");
    if (!nameEl) return;
    var type = currentType();
    var brand = fieldValue("id_brand");
    var color = fieldValue("id_color");
    var grit = fieldValue("id_grit");
    var diameter = fieldValue("id_diameter_mm");
    var holes = fieldValue("id_hole_count");
    var auto = "";
    if (isStainType(type) && brand && color) {
      auto = "Морилка водная " + brand + " «" + color + "»";
    } else if (lastMeta.has_grit && isBeltType(type) && brand && grit) {
      auto = "Лента шлифовальная " + brand + " (" + grit + ")";
    } else if (lastMeta.has_grit && brand && grit && diameter && holes && !isStainType(type)) {
      auto = "Круг шлифовальный " + brand + " " + diameter + "мм " + holes + " отв. (" + grit + ")";
    }
    if (!auto) return;
    var current = String(nameEl.value || "").trim();
    var sameIgnoreCase = current.toLowerCase().replace("ё", "е") === auto.toLowerCase().replace("ё", "е");
    if (sameIgnoreCase) {
      lastAutoName = current;
      return;
    }
    if (!current || current === lastAutoName || looksLikeStainName(current) || looksLikeAbrasiveName(current)) {
      nameEl.value = auto;
      lastAutoName = auto;
    }
  }

  function syncSpecVisibility() {
    var type = currentType();
    var belt = isBeltType(type);
    setBrandVisible(Boolean(lastMeta.has_brand));
    setColorVisible(Boolean(lastMeta.has_color) && isStainType(type));
    setGritVisible(Boolean(lastMeta.has_grit));
    setDiameterVisible(Boolean(lastMeta.has_diameter) && !belt);
    setHolesVisible(Boolean(lastMeta.has_hole_count) && !belt);
  }

  function emptyMeta() {
    return {
      types: [],
      has_grade: false,
      grades: [],
      has_sheet_size: true,
      units: [],
      has_brand: false,
      brands: [],
      has_color: false,
      colors: [],
      has_grit: false,
      grits: [],
      has_diameter: false,
      diameters: [],
      has_hole_count: false,
      holes: [],
    };
  }

  function applyMeta(data) {
    var payload = data || emptyMeta();
    lastMeta = payload;
    fillSelect(byId("id_material_type"), payload.types || []);
    fillSelect(byId("id_unit"), payload.units || []);
    fillSelect(byId("id_grade"), payload.grades || []);
    fillSelect(byId("id_brand"), payload.brands || []);
    fillSelect(byId("id_color"), payload.colors || []);
    fillSelect(byId("id_grit"), payload.grits || []);
    fillSelect(byId("id_diameter_mm"), payload.diameters || []);
    fillSelect(byId("id_hole_count"), payload.holes || []);
    setTypeVisible((payload.types || []).length > 0);
    setGradeVisible(Boolean(payload.has_grade));
    setSheetVisible(payload.has_sheet_size !== false);
    syncSpecVisibility();
    syncName();
    ["id_material_type", "id_brand", "id_color", "id_grit", "id_diameter_mm", "id_hole_count"].forEach(function (id) {
      syncEditEnabled(byId(id));
    });
  }

  function loadMeta(groupId) {
    var root = metaRoot();
    if (!root) return;
    var base = root.getAttribute("data-url") || "";
    if (!base) return;
    var url = base + (base.indexOf("?") >= 0 ? "&" : "?") + "group_id=" + encodeURIComponent(groupId || "");
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (resp) {
        if (!resp.ok) throw new Error("meta " + resp.status);
        return resp.json();
      })
      .then(applyMeta)
      .catch(function () {
        applyMeta(emptyMeta());
      });
  }

  function currentGroupId() {
    var el = groupInput();
    return el ? String(el.value || "").trim() : "";
  }

  function bindGroup() {
    var el = groupInput();
    if (!el || el.getAttribute("data-mat-group-meta-bound") === "1") return;
    el.setAttribute("data-mat-group-meta-bound", "1");
    el.addEventListener("change", function () {
      loadMeta(currentGroupId());
    });
    if (window.django && django.jQuery) {
      django.jQuery(el).on("select2:select select2:clear select2:unselect", function () {
        loadMeta(currentGroupId());
      });
    }
  }

  function bindNameSources() {
    ["id_material_type", "id_brand", "id_color", "id_grit", "id_diameter_mm", "id_hole_count"].forEach(function (id) {
      var el = byId(id);
      if (!el || el.getAttribute("data-mat-name-bound") === "1") return;
      el.setAttribute("data-mat-name-bound", "1");
      el.addEventListener("change", function () {
        syncSpecVisibility();
        syncName();
      });
    });
  }

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function addUrl() {
    var root = metaRoot();
    return root ? root.getAttribute("data-add-url") || "" : "";
  }

  function iconUrl(kind) {
    var root = metaRoot();
    if (!root) return "";
    return root.getAttribute(kind === "add" ? "data-icon-add" : "data-icon-change") || "";
  }

  var CHOICE_FIELDS = {
    type: { selectId: "id_material_type", listKey: "types", addTitle: "Добавить тип", editTitle: "Изменить тип" },
    brand: { selectId: "id_brand", listKey: "brands", addTitle: "Добавить бренд", editTitle: "Изменить бренд" },
    color: { selectId: "id_color", listKey: "colors", addTitle: "Добавить цвет", editTitle: "Изменить цвет" },
    grit: { selectId: "id_grit", listKey: "grits", addTitle: "Добавить зерно", editTitle: "Изменить зерно" },
    diameter: { selectId: "id_diameter_mm", listKey: "diameters", addTitle: "Добавить диаметр", editTitle: "Изменить диаметр" },
    holes: { selectId: "id_hole_count", listKey: "holes", addTitle: "Добавить отверстия", editTitle: "Изменить отверстия" },
  };

  function iconButton(kind, title) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = kind === "add" ? "material-choice-add" : "material-choice-edit";
    btn.setAttribute("title", title);
    btn.setAttribute("aria-label", title);
    var src = iconUrl(kind);
    if (src) {
      var img = document.createElement("img");
      img.src = src;
      img.alt = "";
      img.width = 12;
      img.height = 12;
      btn.appendChild(img);
    } else {
      btn.textContent = kind === "add" ? "+" : "✎";
    }
    return btn;
  }

  function syncEditEnabled(select) {
    if (!select) return;
    var box = select.closest(".material-choice-with-add");
    if (!box) return;
    var btn = box.querySelector(".material-choice-edit");
    if (!btn) return;
    btn.disabled = !String(select.value || "").trim();
  }

  function ensureChoiceToolbar(kind) {
    var spec = CHOICE_FIELDS[kind];
    if (!spec) return;
    var el = byId(spec.selectId);
    if (!el) return;
    if (el.parentElement && el.parentElement.classList.contains("material-choice-with-add")) {
      syncEditEnabled(el);
      return;
    }
    var box = document.createElement("div");
    box.className = "material-choice-with-add";
    el.parentNode.insertBefore(box, el);
    box.appendChild(el);
    var actions = document.createElement("div");
    actions.className = "material-choice-actions";
    var editBtn = iconButton("change", spec.editTitle);
    var addBtn = iconButton("add", spec.addTitle);
    actions.appendChild(editBtn);
    actions.appendChild(addBtn);
    box.appendChild(actions);
    addBtn.addEventListener("click", function () {
      startChoiceEdit(kind, "add");
    });
    editBtn.addEventListener("click", function () {
      startChoiceEdit(kind, "rename");
    });
    el.addEventListener("change", function () {
      syncEditEnabled(el);
    });
    syncEditEnabled(el);
  }

  function startChoiceEdit(kind, action) {
    var spec = CHOICE_FIELDS[kind];
    var select = spec ? byId(spec.selectId) : null;
    if (!select) return;
    if (!currentGroupId()) {
      window.alert("Сначала выберите группу.");
      return;
    }
    var current = String(select.value || "").trim();
    if (action === "rename" && !current) {
      window.alert("Сначала выберите значение в списке.");
      return;
    }
    var box = select.closest(".material-choice-with-add");
    if (!box) return;
    if (box.querySelector(".material-choice-add-input")) {
      box.querySelector(".material-choice-add-input").focus();
      return;
    }
    var actions = box.querySelector(".material-choice-actions");
    var input = document.createElement("input");
    input.type = "text";
    input.className = "material-choice-add-input";
    input.maxLength = 100;
    input.placeholder = action === "rename" ? spec.editTitle : spec.addTitle;
    input.setAttribute("aria-label", input.placeholder);
    if (action === "rename") input.value = current;
    if (actions) actions.hidden = true;
    box.appendChild(input);
    input.focus();
    input.select();

    function cancel() {
      if (input.parentNode) input.parentNode.removeChild(input);
      if (actions) actions.hidden = false;
    }

    function commit() {
      var name = String(input.value || "").trim();
      if (!name || (action === "rename" && name === current)) {
        cancel();
        return;
      }
      saveChoice(kind, name, select, action === "rename" ? current : "");
      cancel();
    }

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      } else if (e.key === "Escape") {
        e.preventDefault();
        cancel();
      }
    });
    input.addEventListener("blur", function () {
      window.setTimeout(function () {
        if (document.activeElement !== input && input.parentNode) commit();
      }, 120);
    });
  }

  function applyChoicePayload(data, kind, select, fallbackName) {
    if (data && data.types) lastMeta.types = data.types;
    if (data && data.brands) lastMeta.brands = data.brands;
    if (data && data.colors) lastMeta.colors = data.colors;
    if (data && data.grits) lastMeta.grits = data.grits;
    if (data && data.diameters) lastMeta.diameters = data.diameters;
    if (data && data.holes) lastMeta.holes = data.holes;
    lastMeta.has_brand = Boolean(data && data.has_brand);
    lastMeta.has_color = Boolean(data && data.has_color);
    lastMeta.has_grit = Boolean(data && data.has_grit);
    lastMeta.has_diameter = Boolean(data && data.has_diameter);
    lastMeta.has_hole_count = Boolean(data && data.has_hole_count);
    var spec = CHOICE_FIELDS[kind];
    var list = spec && lastMeta[spec.listKey] ? lastMeta[spec.listKey] : [];
    var canonical = data && data.name ? String(data.name) : fallbackName;
    fillSelect(select, list);
    if (canonical) select.value = canonical;
    setTypeVisible((lastMeta.types || []).length > 0);
    syncSpecVisibility();
    syncEditEnabled(select);
    select.dispatchEvent(new Event("change"));
  }

  function saveChoice(kind, name, select, oldName) {
    var spec = CHOICE_FIELDS[kind];
    var listKey = spec ? spec.listKey : "brands";
    var current = lastMeta[listKey] ? lastMeta[listKey].slice() : [];
    if (oldName) {
      current = current.map(function (item) {
        return item === oldName ? name : item;
      });
    } else if (
      !current.some(function (item) {
        return String(item).toLowerCase() === name.toLowerCase();
      })
    ) {
      current.push(name);
    }
    lastMeta[listKey] = current;
    fillSelect(select, current);
    select.value = name;
    syncEditEnabled(select);
    select.dispatchEvent(new Event("change"));

    var url = addUrl();
    if (!url) return;
    var body = new URLSearchParams();
    body.set("group_id", currentGroupId());
    body.set("kind", kind);
    body.set("name", name);
    body.set("action", oldName ? "rename" : "add");
    if (oldName) body.set("old_name", oldName);
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: body,
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("choice " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        applyChoicePayload(data, kind, select, name);
      })
      .catch(function () {});
  }

  function bindChoiceAdd() {
    ensureChoiceToolbar("type");
    ensureChoiceToolbar("brand");
    ensureChoiceToolbar("color");
    ensureChoiceToolbar("grit");
    ensureChoiceToolbar("diameter");
    ensureChoiceToolbar("holes");
  }

  function bind() {
    var nameEl = byId("id_name");
    if (nameEl && (looksLikeStainName(nameEl.value) || looksLikeAbrasiveName(nameEl.value))) {
      lastAutoName = String(nameEl.value || "").trim();
    }
    bindGroup();
    bindNameSources();
    bindChoiceAdd();
    loadMeta(currentGroupId());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
