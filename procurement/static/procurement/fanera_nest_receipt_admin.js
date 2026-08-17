/**
 * Заполнение строк приёмки в Django admin из калькулятора раскроя.
 */
(function () {
  "use strict";

  var LINE_PREFIX = "lines";

  function fmt(n, digits) {
    return Number(n).toFixed(digits).replace(".", ",");
  }

  function jq() {
    return window.django && window.django.jQuery ? window.django.jQuery : null;
  }

  function inlineGroup() {
    return (
      document.getElementById(LINE_PREFIX + "-group") ||
      document.getElementById("goodsreceiptline_set-group") ||
      document.querySelector(".inline-group[id*='lines']")
    );
  }

  function materialSelect(tr) {
    return tr.querySelector('select[name$="-material"]');
  }

  function selectValue(select) {
    if (!select) return "";
    var $ = jq();
    if ($) {
      var v = $(select).val();
      return v == null ? "" : String(v);
    }
    return select.value || "";
  }

  function rowIsEmpty(tr) {
    var mat = materialSelect(tr);
    return mat && !selectValue(mat);
  }

  function updateElementIndex(el, prefix, ndx) {
    var idRegex = new RegExp("(" + prefix + "-(\\d+|__prefix__))");
    var replacement = prefix + "-" + ndx;
    if (el.htmlFor) el.htmlFor = el.htmlFor.replace(idRegex, replacement);
    if (el.id) el.id = el.id.replace(idRegex, replacement);
    if (el.name) el.name = el.name.replace(idRegex, replacement);
  }

  function cloneInlineRow(group) {
    var $ = jq();
    if (!$) return null;
    var prefix = LINE_PREFIX;
    var totalForms = $("#id_" + prefix + "-TOTAL_FORMS");
    var template = $("#" + prefix + "-empty");
    if (!totalForms.length || !template.length) return null;

    var nextIndex = parseInt(totalForms.val(), 10);
    var row = template.clone(true);
    row.removeClass("empty-form").addClass("dynamic-" + prefix + " form-row");
    row.attr("id", prefix + "-" + nextIndex);
    row.find("*").addBack().each(function () {
      updateElementIndex(this, prefix, nextIndex);
    });
    row.insertBefore(template);
    totalForms.val(nextIndex + 1);

    if (typeof row.find(".admin-autocomplete").djangoAdminSelect2 === "function") {
      row.find(".admin-autocomplete").djangoAdminSelect2();
    }

    var rowEl = row.get(0);
    if (rowEl) {
      rowEl.dispatchEvent(
        new CustomEvent("formset:added", {
          bubbles: true,
          detail: { formsetName: prefix },
        })
      );
    }
    return rowEl;
  }

  function addInlineRow(group) {
    var addLink = group.querySelector(".add-row a");
    if (addLink) {
      addLink.click();
      var rows = group.querySelectorAll("tbody tr.form-row:not(.empty-form)");
      return rows[rows.length - 1] || null;
    }
    return cloneInlineRow(group);
  }

  function pickRow(group) {
    var rows = group.querySelectorAll("tbody tr.form-row:not(.empty-form)");
    for (var i = 0; i < rows.length; i++) {
      if (rowIsEmpty(rows[i])) return rows[i];
    }
    return addInlineRow(group);
  }

  function setMaterial(select, id, name) {
    if (!select || !id) return;
    var sid = String(id);
    var $ = jq();
    if ($) {
      var $sel = $(select);
      if (!$sel.find('option[value="' + sid + '"]').length) {
        $sel.append(new Option(name || sid, sid, true, true));
      }
      $sel.val(sid).trigger("change");
      return;
    }
    select.value = sid;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillRow(tr, line) {
    setMaterial(materialSelect(tr), line.material_id, line.material_name);
    var qty = tr.querySelector('input[name$="-quantity"]');
    var amount = tr.querySelector('input[name$="-amount"]');
    var price = tr.querySelector('input[name$="-unit_price"]');
    if (qty) {
      qty.value = fmt(line.quantity, 4);
      qty.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (amount) {
      amount.value = fmt(line.amount, 2);
      amount.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (price) {
      price.value = fmt(line.unit_price, 4);
      price.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  window.faneraNestReceiptFillLines = function (lines, meta) {
    var group = inlineGroup();
    if (!group || !lines || !lines.length) return;
    lines.forEach(function (line) {
      if (!line.material_id) return;
      var tr = pickRow(group);
      if (tr) fillRow(tr, line);
    });
    if (meta && meta.receipt_total != null) {
      var totalEl = document.getElementById("id_total_amount");
      if (totalEl) {
        totalEl.value = fmt(meta.receipt_total, 2);
        totalEl.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
    document.dispatchEvent(new CustomEvent("fanera-nest:lines-filled"));
  };
})();
