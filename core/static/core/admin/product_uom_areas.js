/**
 * Предпросмотр пл. (мм², см², м²) и объёма (м³) в карточке товара до сохранения.
 * Итог пересчитывается на сервере в Product.save() → apply_derived_geometry().
 */
(function () {
  "use strict";

  function normUnit(raw) {
    var u = (raw || "").trim().toLowerCase().replace(/\s/g, "").replace(/\u00a0/g, "");
    if (!u) return "other";
    var piece = { шт: 1, штук: 1, штука: 1, pcs: 1, pc: 1, "шт.": 1, штуки: 1 };
    if (piece.hasOwnProperty(u)) return "piece";
    if (
      u === "м²" ||
      u === "m²" ||
      u === "м2" ||
      u === "m2" ||
      u === "кв.м" ||
      u === "квм" ||
      u === "sq.m" ||
      u === "sqm"
    )
      return "sqm";
    if (u.indexOf("кв") !== -1 && (u.indexOf("м") !== -1 || u.indexOf("m") !== -1)) return "sqm";
    if ((raw || "").indexOf("м²") !== -1 || (raw || "").toLowerCase().indexOf("m²") !== -1) return "sqm";
    if (u === "м" || u === "m" || u === "п.м" || u === "пм" || u === "пог.м" || u === "погм" || u === "л.м" || u === "lm")
      return "meter";
    return "other";
  }

  function parseNum(el) {
    if (!el || el.value === "" || el.value === null) return null;
    var n = parseFloat(String(el.value).replace(",", "."));
    return isFinite(n) ? n : null;
  }

  /** Габариты в мм в БД — целые (сервер округляет при сохранении). */
  function roundMm(n) {
    if (n === null || n === undefined) return null;
    return Math.round(n);
  }

  function round6(x) {
    return Math.round(x * 1e6) / 1e6;
  }

  function round2(x) {
    return Math.round(x * 100) / 100;
  }

  function round4(x) {
    return Math.round(x * 1e4) / 1e4;
  }

  function fmtVol(v) {
    if (v === null || v === undefined) return null;
    var s = String(round6(v));
    return s;
  }

  function update() {
    var unitEl = document.getElementById("id_unit");
    var lenEl = document.getElementById("id_sheet_length_mm");
    var widEl = document.getElementById("id_sheet_width_mm");
    var thickEl = document.getElementById("id_sheet_thickness_mm");
    var m2El = document.getElementById("id_area_m2_manual");
    var lenMEl = document.getElementById("id_length_m_manual");
    var preview = document.getElementById("product-uom-area-preview");

    var kind = normUnit(unitEl ? unitEl.value : "");
    var mm2 = null;
    var cm2 = null;
    var m2 = null;
    var vol = null;

    var lenMFromMm = null;
    if (kind === "piece") {
      var L = roundMm(parseNum(lenEl));
      var W = roundMm(parseNum(widEl));
      var T = roundMm(parseNum(thickEl));
      if (L !== null && L > 0) {
        lenMFromMm = round4(L / 1000);
      }
      if (L !== null && W !== null && L > 0 && W > 0) {
        mm2 = L * W;
        cm2 = round2(mm2 / 100);
        m2 = round2(mm2 / 1000000);
      }
      if (L !== null && W !== null && T !== null && L > 0 && W > 0 && T > 0) {
        vol = round6((L * W * T) / 1e9);
      }
    } else if (kind === "sqm") {
      var a = parseNum(m2El);
      var Ts = roundMm(parseNum(thickEl));
      if (a !== null && a > 0) {
        m2 = round2(a);
        cm2 = round2(m2 * 10000);
        mm2 = round2(m2 * 1e6);
      }
      if (a !== null && Ts !== null && a > 0 && Ts > 0) {
        vol = round6(a * (Ts / 1000));
      }
    } else if (kind === "meter") {
      var Lm = parseNum(lenMEl);
      var Wm = roundMm(parseNum(widEl));
      var Tm = roundMm(parseNum(thickEl));
      if (Lm !== null && Wm !== null && Tm !== null && Lm > 0 && Wm > 0 && Tm > 0) {
        vol = round6((Lm * 1000 * Wm * Tm) / 1e9);
      }
    }

    if (preview) {
      var parts = [];
      if (kind === "piece" && lenMFromMm !== null) {
        parts.push("Длина в м, предпросмотр: " + lenMFromMm + " (из длины в мм ÷ 1000, после «Сохранить» запишется в БД).");
      }
      if (mm2 !== null && cm2 !== null && m2 !== null) {
        parts.push(
          "Пл. (после «Сохранить» в БД): " +
            round2(mm2) +
            " мм²  ≈  " +
            cm2 +
            " см²  ≈  " +
            m2 +
            " м²"
        );
      } else if (kind === "piece") {
        parts.push("Ед. шт: укажите длину и ширину (мм) для пл.; добавьте толщину (мм) для объёма.");
      } else if (kind === "sqm") {
        parts.push("Ед. м²: укажите пл. в м²; для объёма — ещё толщину в мм.");
      } else if (kind === "meter") {
        parts.push("Ед. п.м / м: для объёма укажите длину в м, ширину и толщину сечения в мм. Пл. не считается.");
      }

      var vStr = fmtVol(vol);
      if (vStr !== null) {
        parts.push("Объём м³ (предпросмотр): " + vStr);
      } else if (kind === "piece" || kind === "sqm" || kind === "meter") {
        parts.push("Объём м³ заполнится автоматически, когда хватит размеров; иначе останется то, что в поле «Объём м³».");
      }

      if (parts.length) {
        preview.textContent = parts.join(" ");
        preview.removeAttribute("hidden");
      } else {
        preview.textContent = "";
        preview.setAttribute("hidden", "hidden");
      }
    }
  }

  function placePreviewUnderUom() {
    var fs = document.querySelector("fieldset.module.compact-uom");
    var prev = document.getElementById("product-uom-area-preview");
    if (fs && prev && fs.nextElementSibling !== prev) {
      fs.insertAdjacentElement("afterend", prev);
    }
  }

  function bind() {
    placePreviewUnderUom();
    var ids = [
      "id_unit",
      "id_sheet_length_mm",
      "id_sheet_width_mm",
      "id_sheet_thickness_mm",
      "id_area_m2_manual",
      "id_length_m_manual",
      "id_volume",
      "id_weight_kg",
    ];
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) {
        el.addEventListener("input", function () {
          update();
        });
        el.addEventListener("change", function () {
          update();
        });
      }
    });
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
