/**
 * Заполнение строк приёмки в Django admin из калькулятора раскроя.
 */
(function () {
  "use strict";

  function fmt(n, digits) {
    return Number(n).toFixed(digits).replace(".", ",");
  }

  function jq() {
    return window.django && window.django.jQuery ? window.django.jQuery : null;
  }

  function inlineGroup() {
    return (
      document.getElementById("lines-group") ||
      document.getElementById("goodsreceiptline_set-group") ||
      document.querySelector(".inline-group[id*='lines']")
    );
  }

  function formPrefix(group) {
    var id = (group && group.id) || "";
    if (id.slice(-6) === "-group") {
      return id.slice(0, -6);
    }
    return "lines";
  }

  function materialSelect(tr) {
    return tr.querySelector('select[name$="-material"]');
  }

  function field(tr, suffix) {
    return tr.querySelector('input[name$="-' + suffix + '"]');
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
    if (!tr || tr.classList.contains("empty-form")) return false;
    var mat = materialSelect(tr);
    return !!(mat && !selectValue(mat));
  }

  function updateElementIndex(el, prefix, ndx) {
    var idRegex = new RegExp("(" + prefix + "-(\\d+|__prefix__))");
    var replacement = prefix + "-" + ndx;
    if (el.htmlFor) el.htmlFor = el.htmlFor.replace(idRegex, replacement);
    if (el.id) el.id = el.id.replace(idRegex, replacement);
    if (el.name) el.name = el.name.replace(idRegex, replacement);
  }

  function visibleLineRows(group) {
    return group.querySelectorAll("tbody tr.form-row:not(.empty-form)");
  }

  function cloneInlineRow(group) {
    var $ = jq();
    if (!$) return null;
    var prefix = formPrefix(group);
    var totalForms = $("#id_" + prefix + "-TOTAL_FORMS");
    var template = $("#" + prefix + "-empty");
    if (!totalForms.length || !template.length) return null;

    var nextIndex = parseInt(totalForms.val(), 10);
    var row = template.clone(true);
    row.removeClass("empty-form")
      .addClass("dynamic-" + prefix + " form-row")
      .attr("id", prefix + "-" + nextIndex);
    row.find(".select2-container").remove();
    row.find(".admin-autocomplete")
      .removeClass("select2-hidden-accessible")
      .removeAttr("data-select2-id")
      .show();
    row.find("*").addBack().each(function () {
      updateElementIndex(this, prefix, nextIndex);
    });
    row.insertBefore(template);
    totalForms.val(nextIndex + 1);

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
    var before = visibleLineRows(group).length;
    if (addLink) {
      addLink.click();
      var after = visibleLineRows(group);
      if (after.length > before) {
        return after[after.length - 1];
      }
    }
    return cloneInlineRow(group);
  }

  function pickRow(group) {
    var rows = visibleLineRows(group);
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
      if (!$sel.find('option[value="' + sid.replace(/"/g, '\\"') + '"]').length) {
        $sel.append(new Option(name || sid, sid, true, true));
      }
      $sel.val(sid).trigger("change");
      if ($sel.data("select2")) {
        $sel.trigger({
          type: "select2:select",
          params: { data: { id: sid, text: name || sid } },
        });
      }
      return;
    }
    if (![].some.call(select.options, function (opt) { return opt.value === sid; })) {
      var opt = document.createElement("option");
      opt.value = sid;
      opt.text = name || sid;
      select.appendChild(opt);
    }
    select.value = sid;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillRow(tr, line) {
    if (!tr) return;
    tr.setAttribute("data-gr-filling", "1");
    setMaterial(materialSelect(tr), line.material_id, line.material_name);
    var qtyVal = fmt(line.quantity, 4);
    var pack = field(tr, "pack_count");
    var inPack = field(tr, "qty_in_pack");
    var qty = field(tr, "quantity");
    var amount = field(tr, "amount");
    var price = field(tr, "unit_price");
    if (inPack) inPack.value = "1";
    if (pack) pack.value = qtyVal;
    if (qty) qty.value = qtyVal;
    if (amount) amount.value = fmt(line.amount, 2);
    if (price) price.value = fmt(line.unit_price, 4);
    tr.setAttribute("data-gr-last", "amount");
    tr.removeAttribute("data-gr-filling");
  }

  function setReceiptTotal(value) {
    var formatted = fmt(value, 2);
    var totalEl = document.getElementById("id_total_amount");
    if (totalEl) {
      totalEl.value = formatted;
    }
    var totalReadonly = document.querySelector(".field-total_amount .readonly");
    if (totalReadonly) {
      totalReadonly.textContent = formatted;
    }
  }

  window.faneraNestReceiptFillLines = function (lines, meta) {
    var group = inlineGroup();
    if (!group || !lines || !lines.length) return;
    var filled = 0;
    lines.forEach(function (line) {
      if (!line.material_id) return;
      var tr = pickRow(group);
      if (tr) {
        fillRow(tr, line);
        filled += 1;
      }
    });
    if (meta && meta.receipt_total != null) {
      setReceiptTotal(meta.receipt_total);
    }
    document.dispatchEvent(
      new CustomEvent("fanera-nest:lines-filled", { detail: { filled: filled } })
    );
  };
})();
