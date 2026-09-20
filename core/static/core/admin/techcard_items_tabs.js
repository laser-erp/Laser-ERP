'use strict';
/**
 * ОТКАТ ВЕРСТКИ МАТЕРИАЛОВ (на 2026-03): если нужно вернуть старый вид, восстановите в трёх файлах
 * снимок из git до правок «6 колонок / сворачивание техкарты / ресайз всех колонок»:
 * - templates/admin/production/techcardproxy/techcarditem/tabular.html (шапка 8 колонок: чек | этап | код | …)
 * - core/static/core/admin/techcard_items_tabs.css (--tc-items-cols 8 дорожек, рейка grid-column: 2)
 * - core/static/core/admin/techcard_items_tabs.js (карточка: drag|chk|spacer|code|material|…; layoutStagePanelGrid col 2)
 * Старый смысл: рейка этапа в колонке 2; отдельные колонки под ручку и чекбокс; один ресайзер «Этап».
 *
 * ТЕКУЩАЯ РЕАЛИЗАЦИЯ (актуально для правок — не ломать без явного запроса):
 * - Шесть колонок сетки: Этап | Код | Материал | Норма | Техкарта | Параметры (⚙ + чекбокс скрытия «Техкарта»).
 * - Рейка названия этапа: колонка 1, span по числу строк позиций; карточки — subgrid; подвал — отдельная строка.
 * - В карточке: … | норма материала + ед. + рез (м) | техкарта | меню ⋯
 * - Чек «все» и «Переместить в другой этап» — в шапке колонки «Материал»; синхронизация с tbody и formset без изменения префиксов полей.
 * - Ресайз: ручки на правом краю шапок Этап/Код/Материал/Норма/Техкарта; переменные --tc-* (кол. «Материал» — --tc-material-pref) и localStorage.
 * - Скрытие колонки «Техкарта»: класс tc-tech-col-collapsed на группе, LS techcardItemsTechColCollapsed, --tc-tech-pref: 0.
 * - Подвал поиска: .tc-stage-search-footer — grid-column 3 / -1 в сетке панели (Материал…Параметры).
 * - Статика: версии ?v= в tabular.html для сброса кэша при правках css/js.
 */
(function () {
  function init() {
    var $ = django.jQuery;
    var U = window.TECHCARD_ITEMS_UI;
    if (!U || !U.prefix || !U.kinds) {
      return;
    }
    var K = U.kinds;
    var prefix = U.prefix;
    var $group = $('#' + prefix + '-group').filter('.techcard-items-inline-group');
    if (!$group.length) {
      $group = $('#' + prefix + '-group');
    }
    if (!$group.length) {
      return;
    }

    var $backend = $group.find('.techcard-items-backend');

    /** Актуальный tbody инлайна (после переноса DOM в панель «Материалы»). */
    function backendItemTbody() {
      return $backend.find('table tbody').first();
    }

    var $tbody = backendItemTbody();

    function adminUrl(tpl, id) {
      if (!tpl || id == null || String(id).trim() === '') {
        return '';
      }
      return tpl.replace('{id}', String(id));
    }

    function getAddLink() {
      var $tb = backendItemTbody();
      var $a = $tb.find('tr.add-row a.addlink');
      if (!$a.length) {
        $a = $backend.find('tr.add-row a.addlink');
      }
      if (!$a.length) {
        $a = $group.find('tr.add-row a.addlink');
      }
      return $a.first();
    }

    var acUrl = U.autocompleteUrl;
    var materialParams = U.materialFieldParams;
    var productParams = U.productFieldParams;
    var stagesMap = U.stagesMap && typeof U.stagesMap === 'object' ? U.stagesMap : {};
    var techCardsCache = {};
    var unitCacheProduct = {};
    var unitCacheMaterial = {};
    var techcardProductAreaCache = {};

    function parseAreaM2(raw) {
      if (raw == null || String(raw).trim() === '') {
        return null;
      }
      var n = parseFloat(String(raw).replace(',', '.'));
      return isFinite(n) && n > 0 ? n : null;
    }

    function formatNormQty(n) {
      if (!isFinite(n) || n <= 0) {
        return '';
      }
      var s = n.toFixed(6).replace(/\.?0+$/, '');
      return s.replace('.', ',');
    }

    function techcardProductId() {
      var el = document.getElementById('id_product');
      if (!el || el.value == null) {
        return '';
      }
      return String(el.value).trim();
    }

    function withTechcardProductArea(cb) {
      var pid = techcardProductId();
      if (!pid) {
        cb(null);
        return;
      }
      if (Object.prototype.hasOwnProperty.call(techcardProductAreaCache, pid)) {
        cb(techcardProductAreaCache[pid]);
        return;
      }
      var tpl = U.productTcMetaTpl;
      if (!tpl) {
        cb(null);
        return;
      }
      var url = tpl.replace('999888777', pid);
      fetch(url, {
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
      })
        .then(function (r) {
          if (!r.ok) {
            throw new Error('product area');
          }
          return r.json();
        })
        .then(function (data) {
          var area = parseAreaM2(data && data.area_m2);
          techcardProductAreaCache[pid] = area;
          cb(area);
        })
        .catch(function () {
          techcardProductAreaCache[pid] = null;
          cb(null);
        });
    }

    /** Норма листа = площадь изделия / площадь листа материала. */
    function maybeAutofillMaterialSheetNorm($row, force) {
      if (!$row || !$row.length) {
        return;
      }
      var kind = rowItemKind($row);
      if (kind !== K.material && kind !== K.raw) {
        return;
      }
      var $qty = $row.find('[name$="-quantity"]');
      if (!$qty.length) {
        return;
      }
      var cur = String($qty.val() || '').trim();
      if (!force && cur !== '') {
        return;
      }
      var matArea = parseAreaM2($row.attr('data-material-area-m2'));
      if (matArea == null) {
        return;
      }
      withTechcardProductArea(function (prodArea) {
        if (prodArea == null || matArea <= 0) {
          return;
        }
        var qty = prodArea / matArea;
        var formatted = formatNormQty(qty);
        if (!formatted) {
          return;
        }
        $qty.val(formatted).trigger('change');
        var rid = $row.attr('id') || '';
        if (rid) {
          var $cardQty = $group.find(
            '.tc-item-card[data-row-id="' + rid.replace(/"/g, '\\"') + '"] .tc-item-card-qty'
          );
          if ($cardQty.length) {
            $cardQty.val(formatted);
          }
        }
      });
    }

    function withTechCardsForProduct(pid, cb) {
      if (!pid) {
        cb([]);
        return;
      }
      var pk = String(pid);
      if (techCardsCache[pk]) {
        cb(techCardsCache[pk]);
        return;
      }
      var tpl = U.techCardsForProductTpl;
      if (!tpl) {
        cb([]);
        return;
      }
      var url = tpl.replace('999888777', pk);
      fetch(url, {
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
      })
        .then(function (r) {
          if (!r.ok) {
            throw new Error('tech cards http');
          }
          return r.json();
        })
        .then(function (rows) {
          var list = Array.isArray(rows) ? rows : [];
          techCardsCache[pk] = list;
          cb(list);
        })
        .catch(function () {
          cb([]);
        });
    }

    function currentStages() {
      var tp = document.getElementById('id_tech_process');
      var pid = tp && tp.value != null ? String(tp.value).trim() : '';
      if (!pid || !stagesMap[pid]) {
        return [];
      }
      return stagesMap[pid];
    }

    /** Поле «рез, м» только для лазерной резки / гравировки (или этапа с ₽/м). */
    function stageSupportsCutMeters(stageId) {
      if (!stageId) {
        return false;
      }
      var stages = currentStages();
      var st = null;
      for (var i = 0; i < stages.length; i++) {
        if (String(stages[i].id) === String(stageId)) {
          st = stages[i];
          break;
        }
      }
      if (!st) {
        return false;
      }
      var name = String(st.name || '')
        .toLowerCase()
        .replace(/ё/g, 'е');
      var isLaser = name.indexOf('лазер') >= 0 || name.indexOf('laser') >= 0;
      if (isLaser && (name.indexOf('рез') >= 0 || name.indexOf('гравир') >= 0)) {
        return true;
      }
      if (name.indexOf('гравир') >= 0) {
        return true;
      }
      var rateRaw = st.cut_rate_per_meter;
      if (rateRaw != null && String(rateRaw).trim() !== '') {
        var rate = parseFloat(String(rateRaw).replace(',', '.'));
        if (isFinite(rate) && rate > 0) {
          return true;
        }
      }
      return false;
    }

    /** Только «Лазерная резка»: без каталога материалов, одна норма — метры траектории. */
    function stageIsLaserCutOnly(stageId) {
      if (!stageId) {
        return false;
      }
      var stages = currentStages();
      var st = null;
      for (var i = 0; i < stages.length; i++) {
        if (String(stages[i].id) === String(stageId)) {
          st = stages[i];
          break;
        }
      }
      if (!st) {
        return false;
      }
      var name = String(st.name || '')
        .toLowerCase()
        .replace(/ё/g, 'е');
      return name.indexOf('лазер') >= 0 && name.indexOf('рез') >= 0 && name.indexOf('гравир') < 0;
    }

    function stageIsLaserEngraveOnly(stageId) {
      if (!stageId) {
        return false;
      }
      var stages = currentStages();
      var st = null;
      for (var i = 0; i < stages.length; i++) {
        if (String(stages[i].id) === String(stageId)) {
          st = stages[i];
          break;
        }
      }
      if (!st) {
        return false;
      }
      var name = String(st.name || '')
        .toLowerCase()
        .replace(/ё/g, 'е');
      return name.indexOf('гравир') >= 0;
    }

    function stageIsLaserMeterOnly(stageId) {
      return stageIsLaserCutOnly(stageId) || stageIsLaserEngraveOnly(stageId);
    }

    function clearFkSilent($select) {
      if (!$select || !$select.length) {
        return;
      }
      var el = $select[0];
      if (el.tagName === 'SELECT') {
        $select.empty();
        $select.append(new Option('---------', '', true, true));
        $select.val('');
      } else {
        $select.val('');
      }
    }

    /** Без trigger('change') — иначе rebuildMirrors зацикливается и строка «моргает». */
    function syncLaserCutRowBackend($row, stageId) {
      if (!stageIsLaserCutOnly(stageId)) {
        return;
      }
      var $mat = $row.find('[name$="-material"]');
      var $prod = $row.find('[name$="-product"]');
      if (($mat.val() || '').trim()) {
        clearFkSilent($mat);
        $row.attr('data-material-id', '');
      }
      if (($prod.val() || '').trim()) {
        clearFkSilent($prod);
      }
      var $qty = $row.find('[name$="-quantity"]');
      if ($qty.length && String($qty.val() || '').trim() !== '0') {
        $qty.val('0');
      }
      $row.find('[name$="-item_kind"]').val(K.material);
    }

    function syncLaserEngraveRowBackend($row, stageId) {
      if (!stageIsLaserEngraveOnly(stageId)) {
        return;
      }
      syncLaserCutRowBackend($row, stageId);
    }

    function onTechProcessUiChange() {
      window.setTimeout(rebuildMirrors, 0);
    }

    var tpEl = document.getElementById('id_tech_process');
    if (tpEl) {
      tpEl.addEventListener('change', onTechProcessUiChange);
    }
    if ($.fn.select2) {
      var $tp = $('#id_tech_process');
      if ($tp.length) {
        $tp.on('select2:select select2:clear select2:unselect change', onTechProcessUiChange);
      }
    }

    function onTechcardProductChange() {
      techcardProductAreaCache = {};
    }
    var prodEl = document.getElementById('id_product');
    if (prodEl && prodEl.getAttribute('data-tc-prod-area-bound') !== '1') {
      prodEl.setAttribute('data-tc-prod-area-bound', '1');
      prodEl.addEventListener('change', onTechcardProductChange);
      if ($.fn.select2) {
        $(prodEl).on('select2:select select2:clear select2:unselect change', onTechcardProductChange);
      }
    }

    var pendingAdd = null;
    var adding = false;
    var materialBatchTail = [];
    var materialBatchStageId = '';

    function parseMaterialQty(s) {
      if (s == null || s === '') {
        return null;
      }
      var t = String(s).trim().replace(',', '.');
      var n = parseFloat(t);
      return isFinite(n) ? n : null;
    }

    function isRowDeleted($row) {
      var $cb = $row.find('input[name$="-DELETE"]');
      return $cb.length && $cb.prop('checked');
    }

    function rowItemKind($r) {
      var k = ($r.find('[name$="-item_kind"]').val() || '').trim();
      return k || ($r.attr('data-item-kind') || '').trim();
    }

    function isDuplicate(kind, fkName, id, stageId) {
      var dup = false;
      backendItemTbody()
        .find('tr.form-row')
        .not('.empty-form')
        .not('.add-row')
        .not('.row-form-errors')
        .each(function () {
        var $r = $(this);
        if (isRowDeleted($r)) {
          return;
        }
        if (rowItemKind($r) !== kind) {
          return;
        }
        var st = ($r.find('[name$="-production_stage"]').val() || '').trim();
        if (stageId != null && String(st) !== String(stageId)) {
          return;
        }
        var v = fkName === 'product' ? $r.find('[name$="-product"]').val() : $r.find('[name$="-material"]').val();
        if (String(v) === String(id)) {
          dup = true;
        }
      });
      return dup;
    }


    function wipeAndSetFk($select, id, text) {
      if (!$select.length) {
        return;
      }
      var el = $select[0];
      if (el.tagName === 'SELECT') {
        $select.empty();
        if (id) {
          $select.append(new Option(text, String(id), true, true));
        } else {
          $select.append(new Option('---------', '', true, true));
        }
        $select.val(id ? String(id) : '');
        $select.trigger('change');
        return;
      }
      if (el.tagName === 'INPUT') {
        $select.val(id ? String(id) : '');
        $select.trigger('change');
      }
    }

    function applyPendingToRow($row, p) {
      var $kind = $row.find('[name$="-item_kind"]');
      var $mat = $row.find('[name$="-material"]');
      var $prod = $row.find('[name$="-product"]');
        if (p.kind === 'laser_cut' || p.kind === 'laser_engrave') {
        $kind.val(K.material);
        clearFkSilent($mat);
        clearFkSilent($prod);
        $row.attr('data-material-id', '');
        $row.attr('data-product-name', '');
        $row.attr('data-product-id', '');
        var $stLc = $row.find('[name$="-production_stage"]');
        if ($stLc.length && p.stageId != null) {
          $stLc.val(String(p.stageId));
        }
        var $qnLc = $row.find('[name$="-quantity"]');
        if ($qnLc.length) {
          $qnLc.val('0');
        }
        if (p.kind === 'laser_cut') {
          $row.find('[name$="-engrave_kind"]').val('');
          $row.find('[name$="-engrave_area_m2"]').val('');
          if (p.cutMeters != null && String(p.cutMeters).trim() !== '') {
            $row.find('[name$="-cut_length_meters_per_unit"]').val(String(p.cutMeters).trim());
          }
        } else {
          var ek = (p.engraveKind || 'contour').trim() || 'contour';
          $row.find('[name$="-engrave_kind"]').val(ek);
          if (ek === 'fill') {
            $row.find('[name$="-cut_length_meters_per_unit"]').val('');
            $row.find('[name$="-engrave_area_m2"]').val(
              p.normValue != null ? String(p.normValue).trim() : ''
            );
          } else {
            $row.find('[name$="-engrave_area_m2"]').val('');
            if (p.normValue != null && String(p.normValue).trim() !== '') {
              $row.find('[name$="-cut_length_meters_per_unit"]').val(String(p.normValue).trim());
            } else if (p.cutMeters != null && String(p.cutMeters).trim() !== '') {
              $row.find('[name$="-cut_length_meters_per_unit"]').val(String(p.cutMeters).trim());
            }
          }
        }
        return;
      }
      $kind.val(p.kind);
      if (p.kind === K.component) {
        wipeAndSetFk($mat, null, '');
        wipeAndSetFk($prod, p.id, p.text);
        $row.attr('data-product-name', (p.text || '').trim());
        $row.attr('data-product-id', p.id != null ? String(p.id) : '');
      } else {
        wipeAndSetFk($prod, null, '');
        wipeAndSetFk($mat, p.id, p.text);
        $row.attr('data-product-name', '');
        $row.attr('data-product-id', '');
        $row.attr('data-material-id', p.id != null ? String(p.id) : '');
      }
      var stages = currentStages();
      var $st = $row.find('[name$="-production_stage"]');
      if ($st.length && stages.length) {
        var cur = ($st.val() || '').trim();
        if (p.stageId != null) {
          $st.val(String(p.stageId)).trigger('change');
        } else if (!cur) {
          $st.val(String(stages[0].id)).trigger('change');
        }
      }
      if (p.quantity != null && p.quantity !== '') {
        var $qn = $row.find('[name$="-quantity"]');
        if ($qn.length) {
          $qn.val(String(p.quantity)).trigger('change');
        }
      }
    }

    function rowStageId($row) {
      var stages = currentStages();
      var $st = $row.find('[name$="-production_stage"]');
      var v = ($st.val() || '').trim();
      var valid = {};
      stages.forEach(function (s) {
        valid[String(s.id)] = true;
      });
      if (v && valid[v]) {
        return v;
      }
      if (stages.length) {
        return String(stages[0].id);
      }
      return '';
    }

    function rowDisplayCode($row, kind) {
      if (kind === K.component) {
        var c = ($row.attr('data-product-code') || '').trim();
        if (c) {
          return c;
        }
        var a = ($row.attr('data-product-article') || '').trim();
        return a || '—';
      }
      var mc = ($row.attr('data-material-code') || '').trim();
      if (mc) {
        return mc;
      }
      var mid = ($row.attr('data-material-id') || '').trim();
      return mid ? '#' + mid : '—';
    }

    function rowUnit($row, kind) {
      if (kind === K.component) {
        return ($row.attr('data-product-unit') || '').trim() || '—';
      }
      return ($row.attr('data-material-unit') || '').trim() || '—';
    }

    function rowProductId($row) {
      var v = ($row.find('[name$="-product"]').val() || '').trim();
      if (v) {
        return v;
      }
      return ($row.attr('data-product-id') || '').trim();
    }

    /** Скрытый input product не даёт option:selected — имя из data-product-name или select. */
    function rowComponentDisplayName($row, $prodSel) {
      var n = ($row.attr('data-product-name') || '').trim();
      if (n) {
        return n;
      }
      var el = $prodSel[0];
      if (el && el.tagName === 'SELECT') {
        var t = ($prodSel.find('option:selected').text() || '').trim();
        if (t && t !== '---------') {
          return t;
        }
      }
      return '';
    }

    function applyRowTcMeta($row, kind, pk, meta) {
      if (kind === K.component) {
        $row.attr('data-product-id', pk);
        $row.attr('data-product-unit', meta.unit != null ? meta.unit : '');
        $row.attr('data-product-code', meta.code != null ? meta.code : '');
        $row.attr('data-product-article', meta.article != null ? meta.article : '');
        if (meta.name != null && String(meta.name).trim() !== '') {
          $row.attr('data-product-name', String(meta.name).trim());
        }
        if (meta.area_m2 != null) {
          $row.attr('data-product-area-m2', meta.area_m2);
        }
      } else {
        $row.attr('data-material-id', pk);
        $row.attr('data-material-unit', meta.unit != null ? meta.unit : '');
        $row.attr(
          'data-material-area-m2',
          meta.area_m2 != null ? String(meta.area_m2) : ''
        );
        $row.attr(
          'data-material-sheet-length-mm',
          meta.sheet_length_mm != null ? String(meta.sheet_length_mm) : ''
        );
        $row.attr(
          'data-material-sheet-width-mm',
          meta.sheet_width_mm != null ? String(meta.sheet_width_mm) : ''
        );
      }
    }

    function prefetchRowUnits($row, done, opts) {
      opts = opts || {};
      if (!$row || !$row.length) {
        if (done) {
          done();
        }
        return;
      }
      var kind = rowItemKind($row);
      var id;
      var tpl;
      var cache;
      if (kind === K.component) {
        id = ($row.find('[name$="-product"]').val() || '').trim();
        tpl = U.productTcMetaTpl;
        cache = unitCacheProduct;
      } else if (kind === K.material || kind === K.raw) {
        id = ($row.find('[name$="-material"]').val() || '').trim();
        tpl = U.materialTcMetaTpl;
        cache = unitCacheMaterial;
      } else {
        if (done) {
          done();
        }
        return;
      }
      var pk = String(id);
      if (!id) {
        if (kind === K.component) {
          $row.attr('data-product-id', '');
          $row.attr('data-product-unit', '');
          $row.attr('data-product-code', '');
          $row.attr('data-product-article', '');
          $row.attr('data-product-name', '');
        } else {
          $row.attr('data-material-id', '');
          $row.attr('data-material-unit', '');
          $row.attr('data-material-area-m2', '');
        }
        if (done) {
          done();
        }
        return;
      }
      function afterMeta() {
        if (opts.autofillNorm) {
          maybeAutofillMaterialSheetNorm($row, !!opts.forceAutofill);
        }
        if (done) {
          done();
        }
      }
      if (Object.prototype.hasOwnProperty.call(cache, pk)) {
        applyRowTcMeta($row, kind, pk, cache[pk]);
        afterMeta();
        return;
      }
      if (!tpl) {
        afterMeta();
        return;
      }
      var url = tpl.replace('999888777', pk);
      fetch(url, {
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
      })
        .then(function (r) {
          if (!r.ok) {
            throw new Error('meta');
          }
          return r.json();
        })
        .then(function (data) {
          var meta =
            kind === K.component
              ? {
                  unit: data && data.unit != null ? String(data.unit).trim() : '',
                  code: data && data.code != null ? String(data.code).trim() : '',
                  article: data && data.article != null ? String(data.article).trim() : '',
                  name: data && data.name != null ? String(data.name).trim() : '',
                  area_m2: data && data.area_m2 != null ? String(data.area_m2).trim() : '',
                }
              : {
                  unit: data && data.unit != null ? String(data.unit).trim() : '',
                  area_m2: data && data.area_m2 != null ? String(data.area_m2).trim() : '',
                  sheet_length_mm:
                    data && data.sheet_length_mm != null ? String(data.sheet_length_mm).trim() : '',
                  sheet_width_mm:
                    data && data.sheet_width_mm != null ? String(data.sheet_width_mm).trim() : '',
                };
          cache[pk] = meta;
          applyRowTcMeta($row, kind, pk, meta);
        })
        .catch(function () {})
        .finally(function () {
          afterMeta();
        });
    }

    function $rowFromCardId(rid) {
      if (!rid) {
        return $();
      }
      var el = document.getElementById(rid);
      return el ? $(el) : $();
    }

    function syncMaterialHeaderSelectionUi() {
      var $cards = $group.find('.tc-item-card-select:checked');
      var n = $cards.length;
      var $label = $group.find('.tc-mgh-material-label');
      var $move = $group.find('.tc-mgh-move-wrap');
      var $menu = $group.find('.tc-mgh-move-menu');
      var $btn = $group.find('.tc-mgh-move-btn');
      if (n === 0) {
        $label.show();
        $move.hide();
        $menu.attr('hidden', 'hidden').empty();
        $btn.attr('aria-expanded', 'false');
      } else {
        $label.hide();
        $move.show();
      }
      var total = $group.find('.tc-item-card-select').length;
      var $all = $group.find('.tc-mgh-select-all');
      if ($all.length) {
        $all[0].indeterminate = n > 0 && n < total;
        $all.prop('checked', total > 0 && n === total);
      }
    }

    function populateMoveMenu() {
      var $menu = $group.find('.tc-mgh-move-menu');
      $menu.empty();
      currentStages().forEach(function (s) {
        var $li = $('<li role="option" tabindex="0"></li>');
        $li.text(s.name || String(s.id));
        $li.attr('data-stage-id', String(s.id));
        $menu.append($li);
      });
    }

    function moveSelectedRowsToStage(targetStageId) {
      var tid = String(targetStageId);
      $group.find('.tc-item-card-select:checked').each(function () {
        var $card = $(this).closest('.tc-item-card');
        var rid = $card.attr('data-row-id');
        var $row = $rowFromCardId(rid);
        if (!$row.length) {
          return;
        }
        var $st = $row.find('[name$="-production_stage"]');
        if ($st.length) {
          $st.val(tid).trigger('change');
        }
        $(this).prop('checked', false);
      });
      $group.find('.tc-mgh-move-menu').attr('hidden', 'hidden').empty();
      $group.find('.tc-mgh-move-btn').attr('aria-expanded', 'false');
      syncMaterialHeaderSelectionUi();
      rebuildMirrors();
    }

    function bindHeaderSelectionOnce() {
      if ($group.data('tcHeaderSel')) {
        return;
      }
      $group.data('tcHeaderSel', true);

      $group.on('change', '.tc-item-card-select', function () {
        syncMaterialHeaderSelectionUi();
      });

      $group.on('change', '.tc-mgh-select-all', function () {
        var on = $(this).prop('checked');
        $group.find('.tc-item-card-select').prop('checked', on);
        syncMaterialHeaderSelectionUi();
      });

      $group.on('click', '.tc-mgh-move-btn', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var $menu = $group.find('.tc-mgh-move-menu');
        var open = $menu.attr('hidden') == null;
        if (open) {
          $menu.attr('hidden', 'hidden');
          $(this).attr('aria-expanded', 'false');
        } else {
          populateMoveMenu();
          $menu.removeAttr('hidden');
          $(this).attr('aria-expanded', 'true');
        }
      });

      $group.on('click', '.tc-mgh-move-menu li', function (e) {
        e.preventDefault();
        var sid = $(this).attr('data-stage-id');
        if (sid) {
          moveSelectedRowsToStage(sid);
        }
      });

      $(document).on('click.techcardMghMove', function (e) {
        if (!$(e.target).closest('.tc-mgh-move-wrap').length) {
          $group.find('.tc-mgh-move-menu').attr('hidden', 'hidden');
          $group.find('.tc-mgh-move-btn').attr('aria-expanded', 'false');
        }
      });
    }

    function bindCardMenusOnce() {
      if ($group.data('tcCardMenus')) {
        return;
      }
      $group.data('tcCardMenus', true);

      function closeAllCardMenus() {
        $group.find('.tc-item-card-menu').attr('hidden', 'hidden').removeClass('tc-item-card-menu--flip');
      }

      $group.on('click', '.tc-item-card-kebab', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var $wrap = $(this).closest('.tc-item-card-menu-wrap');
        var $pop = $wrap.find('.tc-item-card-menu');
        var open = $pop.attr('hidden') == null;
        closeAllCardMenus();
        if (!open) {
          $pop.removeAttr('hidden');
          $pop.removeClass('tc-item-card-menu--flip');
          window.setTimeout(function () {
            var el = $pop[0];
            var wrapEl = $wrap[0];
            if (!el || !wrapEl) {
              return;
            }
            var br = wrapEl.getBoundingClientRect();
            var mh = el.offsetHeight;
            var pad = 8;
            var spaceBelow = window.innerHeight - br.bottom;
            if (spaceBelow < mh + pad && br.top > mh + pad) {
              $pop.addClass('tc-item-card-menu--flip');
            }
          }, 0);
        }
      });

      $(document).on('click.techcardCardMenu', function (e) {
        if (!$(e.target).closest('.tc-item-card-menu-wrap').length) {
          closeAllCardMenus();
        }
      });

      $group.on('click', '.tc-item-card-menu button', function (e) {
        e.preventDefault();
        var act = $(this).attr('data-act');
        var $card = $(this).closest('.tc-item-card');
        var rid = $card.attr('data-row-id');
        var $row = $rowFromCardId(rid || '');
        var kind = $row.length ? rowItemKind($row) : '';
        var pid = ($row.attr('data-product-id') || '').trim();
        var mid = ($row.attr('data-material-id') || '').trim();
        closeAllCardMenus();

        if (act === 'open-card') {
          if (kind === K.component && pid && U.adminProductChange) {
            window.open(adminUrl(U.adminProductChange, pid), '_blank');
          } else if (mid && U.adminMaterialChange) {
            window.open(adminUrl(U.adminMaterialChange, mid), '_blank');
          }
        } else if (act === 'replace') {
          $row.find('[name$="-material"], [name$="-product"]').first().trigger('focus');
        } else if (act === 'edit-techcard') {
          var htc = ($row.find('select[name$="-component_tech_card"]').val() || '').trim();
          if (htc && U.adminTechcardChange) {
            window.open(U.adminTechcardChange.replace('999888777', htc), '_blank');
          } else if (U.adminTechcardChangelist) {
            window.open(U.adminTechcardChangelist, '_blank');
          }
        } else if (act === 'create-techcard') {
          if (U.adminTechcardAdd) {
            var q = pid ? '?product=' + encodeURIComponent(pid) : '';
            window.open(U.adminTechcardAdd + q, '_blank');
          }
        } else if (act === 'delete') {
          removeRow($row);
        }
      });
    }

    function bindStageDnDOnce() {
      if ($group.data('tcStageDnd')) {
        return;
      }
      $group.data('tcStageDnd', true);

      $group.on('dragstart', '.tc-item-card-drag', function (e) {
        var $card = $(this).closest('.tc-item-card');
        var rid = $card.attr('data-row-id');
        var sid = $card.attr('data-stage-id') || '';
        try {
          e.originalEvent.dataTransfer.setData(
            'application/x-techcard-item',
            JSON.stringify({ rowId: rid, stageId: sid })
          );
          e.originalEvent.dataTransfer.effectAllowed = 'move';
        } catch (err) {}
      });

      $group.on('dragover', '.tc-stage-panel', function (e) {
        e.preventDefault();
        try {
          e.originalEvent.dataTransfer.dropEffect = 'move';
        } catch (err2) {}
      });

      $group.on('drop', '.tc-stage-panel', function (e) {
        e.preventDefault();
        var targetSid = $(this).attr('data-stage-id');
        if (!targetSid) {
          return;
        }
        var raw = null;
        try {
          raw = e.originalEvent.dataTransfer.getData('application/x-techcard-item');
        } catch (err3) {}
        if (!raw) {
          return;
        }
        var data = null;
        try {
          data = JSON.parse(raw);
        } catch (err4) {}
        if (!data || !data.rowId) {
          return;
        }
        if (String(data.stageId) === String(targetSid)) {
          return;
        }
        var $row = $rowFromCardId(String(data.rowId));
        if (!$row.length) {
          return;
        }
        if (stageIsLaserMeterOnly(targetSid)) {
          if (rowItemKind($row) === K.component) {
            window.alert(
              'На этап лазерной резки/гравировки нельзя перенести комплектующее. Здесь только нормы работы.'
            );
            return;
          }
          var mid = ($row.find('[name$="-material"]').val() || '').trim();
          var qn = parseMaterialQty($row.find('[name$="-quantity"]').val());
          if (mid && qn != null && qn > 0) {
            window.alert(
              'Материал с расходом оставьте на своём этапе. На лазере — только метры или м² гравировки.'
            );
            return;
          }
        }
        $row.find('[name$="-production_stage"]').val(String(targetSid)).trigger('change');
        if (stageIsLaserCutOnly(targetSid)) {
          syncLaserCutRowBackend($row, targetSid);
        } else if (stageIsLaserEngraveOnly(targetSid)) {
          syncLaserEngraveRowBackend($row, targetSid);
        }
        rebuildMirrors();
      });
    }

    function renderStageShells() {
      var $root = $group.find('.tc-materials-stages-root').first();
      $root.empty();
      var stages = currentStages();
      if (!stages.length) {
        $root.append(
          $('<div class="tc-stages-empty"></div>').text(
            'Укажите техпроцесс в карте — этапы подставятся из него.'
          )
        );
        return;
      }
      stages.forEach(function (s) {
        var sid = String(s.id);
        var $panel = $('<div class="tc-stage-panel"></div>').attr('data-stage-id', sid);

        /* Сетка как у шапки: рейка с названием этапа в кол. 2 на все строки позиций; подвал — отдельная строка. */
        var $inner = $('<div class="tc-stage-panel-inner"></div>');
        $inner.append($('<div class="tc-stage-name-rail"></div>').text(s.name));
        var $items = $('<div class="tc-stage-items"></div>');

        var $footer = $('<div class="tc-stage-search-footer"></div>');
        var $footInner = $('<div class="tc-stage-search-footer-inner"></div>');
        var laserCutFooter = stageIsLaserCutOnly(sid);
        var laserEngraveFooter = stageIsLaserEngraveOnly(sid);
        var laserFooter = laserCutFooter || laserEngraveFooter;
        if (laserFooter) {
          $panel.addClass('tc-stage-panel--laser-cut-only');
        }
        if (laserEngraveFooter) {
          $panel.addClass('tc-stage-panel--laser-engrave-only');
        }
        var footerPh = 'Поиск по наименованию, коду, штрихкоду или артикулу';
        if (laserCutFooter) {
          footerPh = 'Метры реза на 1 изделие — Enter для новой строки';
        } else if (laserEngraveFooter) {
          footerPh = 'Метры контура на 1 изделие — Enter для новой строки';
        }
        var $sr = $('<div class="tc-item-search-row tc-item-search-row--stage"></div>');
        if (laserEngraveFooter) {
          $sr.addClass('tc-item-search-row--laser-engrave');
        }
        var $wrap = $('<div class="tc-item-search-wrap"></div>');
        var $footInput = $(
          '<input type="text" class="tc-item-search-input" autocomplete="off" inputmode="decimal" />'
        ).attr('placeholder', footerPh);
        if (laserEngraveFooter) {
          var $footKind = $(
            '<select class="tc-item-kind-select--stage tc-engrave-footer-kind" aria-label="Тип гравировки для новой строки"></select>'
          );
          $footKind.append(new Option('Контур', 'contour', true, true));
          $footKind.append(new Option('Заливка', 'fill', false, false));
          $footKind.on('change', function () {
            var ph =
              ($footKind.val() || 'contour') === 'fill'
                ? 'Площадь заливки, м² — Enter для новой строки'
                : 'Метры контура на 1 изделие — Enter для новой строки';
            $footInput.attr('placeholder', ph);
          });
          $sr.append($footKind);
        }
        $wrap.append($footInput);
        if (!laserFooter) {
          $wrap.append($('<ul class="tc-item-dropdown"></ul>'));
        }
        $sr.append($wrap);
        if (!laserFooter) {
          $sr.append(
            $('<button type="button" class="tc-item-add-from-directory"></button>').text('Добавить из справочника')
          );
          $sr.append(
            $('<button type="button" class="tc-item-import tc-item-import--stage" disabled title="Импорт из файла — в разработке"></button>')
              .append($('<span class="tc-item-import-icon" aria-hidden="true"></span>').text('↓'))
              .append($('<span class="tc-item-import-label"></span>').text('Импортировать'))
          );
        }
        $footInner.append($sr);
        $footer.append($footInner);

        $inner.append($items);
        $inner.append($footer);
        $panel.append($inner);
        $root.append($panel);
      });
    }

    var rebuildMirrorsTimer = null;

    function rebuildMirrorsImpl() {
      /* tbody заново: после загрузки/переноса панелей ссылка должна быть актуальной */
      $tbody = backendItemTbody();
      renderStageShells();
      var stages = currentStages();
      var valid = {};
      stages.forEach(function (s) {
        valid[String(s.id)] = true;
      });

      function appendCard($card, stageKey) {
        var $target = $group.find(
          '.tc-stage-panel[data-stage-id="' + stageKey + '"] .tc-stage-items'
        );
        if (!$target.length) {
          $target = $group.find('.tc-stage-panel').first().find('.tc-stage-items');
        }
        if ($target.length) {
          $target.append($card);
        }
      }

      function optExists($sel, val) {
        var s = String(val);
        return $sel.find('option').filter(function () {
          return this.value === s;
        }).length > 0;
      }

      var $prodCompTbody = $('#tc-ms-product-composition-tbody');
      if ($prodCompTbody.length) {
        $prodCompTbody.empty();
      }

      function appendProductCompositionRow($row, sk, label, qty, code, unit) {
        var $tb = $('#tc-ms-product-composition-tbody');
        if (!$tb.length) {
          return;
        }
        var displayLabel = label === '---------' || label === '' ? '—' : label;
        var titleMain = displayLabel;
        var codeStr = code && code !== '—' ? String(code) : '';
        if (codeStr && titleMain.indexOf(codeStr) === 0) {
          titleMain = titleMain
            .substring(codeStr.length)
            .replace(/^\s*[—\-]\s*/, '')
            .trim();
        }
        if (!titleMain) {
          titleMain = displayLabel;
        }

        var $tr = $('<tr class="tc-ms-product-comp-row"></tr>');
        $tr.attr('data-row-id', $row.attr('id') || '');
        $tr.attr('data-stage-id', sk);

        var $tdName = $('<td class="tc-ms-product-col-name"></td>');
        var $nameLine = $('<div class="tc-ms-product-name-line"></div>');
        /* Точки рисуются в CSS (SVG фон у .tc-ms-product-comp-drag), не span — иначе в таблице не видны */
        var $drag = $(
          '<div class="tc-item-card-drag tc-ms-product-comp-drag" draggable="true" title="Перетащить выше или ниже в списке"></div>'
        );
        var $titleWrap = $('<div class="tc-ms-product-title-wrap"></div>');
        var $textAfterDrag = $('<span class="tc-ms-product-title-text"></span>');
        if (codeStr) {
          $textAfterDrag.append($('<span class="tc-ms-product-code"></span>').text(codeStr));
          $textAfterDrag.append(document.createTextNode(' '));
        }
        $textAfterDrag.append($('<span class="tc-ms-product-title"></span>').text(titleMain));
        /* Шесть точек сразу перед артикулом (в одной строке с текстом) */
        $titleWrap.append($drag);
        $titleWrap.append($textAfterDrag);
        $nameLine.append($titleWrap);
        $tdName.append($nameLine);

        var $tdNorm = $('<td class="tc-ms-product-col-norm"></td>');
        var $qtyIn = $('<input type="text" class="tc-item-card-qty vTextField">');
        $qtyIn.attr('placeholder', 'Норма');
        $qtyIn.val(qty);
        $qtyIn.on('input change', function () {
          $row.find('[name$="-quantity"]').val($qtyIn.val()).trigger('change');
        });
        var $unitSel = $('<select class="tc-item-card-unit" aria-label="Единица измерения"></select>');
        $unitSel.append(new Option(unit, unit, true, true));
        $tdNorm.append($qtyIn);
        $tdNorm.append($unitSel);

        var $tdRm = $('<td class="tc-ms-product-col-remove"></td>');
        var $rmBtn = $(
          '<button type="button" class="tc-ms-product-comp-remove" aria-label="Удалить из списка"></button>'
        );
        $rmBtn.append($('<span class="tc-ms-product-comp-remove-x" aria-hidden="true">×</span>'));
        $tdRm.append($rmBtn);

        $tr.append($tdName);
        $tr.append($tdNorm);
        $tr.append($tdRm);
        $tb.append($tr);
      }

      $tbody.find('tr.form-row').not('.empty-form').not('.add-row').not('.row-form-errors').each(function () {
        var $row = $(this);
        if (isRowDeleted($row)) {
          return;
        }
        var kind = rowItemKind($row);
        if (!kind) {
          return;
        }
        var $matSel = $row.find('[name$="-material"]');
        var $prodSel = $row.find('[name$="-product"]');
        var label =
          kind === K.component
            ? rowComponentDisplayName($row, $prodSel) || '—'
            : ($matSel.find('option:selected').text() || '—').trim();
        if (label === '---------' || label === '') {
          label = '—';
        }
        var qty = $row.find('[name$="-quantity"]').val() || '';

        var sk = rowStageId($row);
        if (!sk || !valid[sk]) {
          sk = stages.length ? String(stages[0].id) : '';
        }

        var code = rowDisplayCode($row, kind);
        var unit = rowUnit($row, kind);

        if (kind === K.component) {
          appendProductCompositionRow($row, sk, label, qty, code, unit);
          return;
        }

        var laserCutOnly = stageIsLaserCutOnly(sk);
        var laserEngraveOnly = stageIsLaserEngraveOnly(sk);
        var laserMeterOnly = laserCutOnly || laserEngraveOnly;
        if (laserCutOnly) {
          syncLaserCutRowBackend($row, sk);
          label = 'Метры реза';
          code = '—';
          unit = 'м';
          qty = '';
        } else if (laserEngraveOnly) {
          syncLaserEngraveRowBackend($row, sk);
          label = 'Метры контура';
          code = '—';
          unit = 'м';
          qty = '';
        }

        var $card = $('<div class="tc-item-card"></div>');
        $card.attr('data-row-id', $row.attr('id') || '');
        $card.attr('data-stage-id', sk);

        $card.append($('<div class="tc-item-card-col-stage-spacer"></div>'));

        $card.append(
          $('<div class="tc-item-card-col-code"></div>').text(code).attr('title', code)
        );

        var $drag = $('<div class="tc-item-card-drag" draggable="true" title="Перетащить в другой этап"></div>');
        for (var d = 0; d < 6; d++) {
          $drag.append($('<span class="tc-item-card-drag-dot"></span>'));
        }
        var $cb = $('<input type="checkbox" class="tc-item-card-select" aria-label="Выбрать позицию" />');

        var $matCell = $('<div class="tc-item-card-material-cell"></div>');
        $matCell.append($drag);
        $matCell.append($cb);
        var $nameEl = $('<div class="tc-item-card-name"></div>').text(label).attr('title', label);
        $matCell.append($nameEl);
        $card.append($matCell);

        var $normCell = $('<div class="tc-item-card-norm-cell"></div>');
        var $cutField = $row.find('[name$="-cut_length_meters_per_unit"]');
        if (laserCutOnly) {
          var cutValLc = $cutField.val() || '';
          var $cutWrapLc = $('<div class="tc-item-card-cut-wrap"></div>');
          var $cutOnly = $('<input type="text" class="tc-item-card-cut vTextField" inputmode="decimal">');
          $cutOnly.attr('placeholder', 'рез');
          $cutOnly.attr(
            'title',
            'Длина реза на 1 изделие, м. Стоимость = м × ₽/м этапа.'
          );
          $cutOnly.attr('aria-label', 'Норма длины реза, м');
          $cutOnly.val(cutValLc);
          $cutOnly.on('input change', function () {
            $cutField.val($cutOnly.val());
          });
          $cutWrapLc.append($cutOnly);
          $cutWrapLc.append($('<span class="tc-item-card-cut-unit"></span>').text('м'));
          $normCell.append($cutWrapLc);
        } else if (laserEngraveOnly) {
          var $kindField = $row.find('[name$="-engrave_kind"]');
          var $areaField = $row.find('[name$="-engrave_area_m2"]');
          var kindVal0 = ($kindField.val() || '').trim() || 'contour';
          if (!$kindField.val()) {
            $kindField.val('contour');
          }
          var $kindSel = $(
            '<select class="tc-item-card-unit tc-item-card-engrave-kind" aria-label="Тип гравировки"></select>'
          );
          $kindSel.append(new Option('Контур', 'contour', kindVal0 === 'contour', kindVal0 === 'contour'));
          $kindSel.append(new Option('Заливка', 'fill', kindVal0 === 'fill', kindVal0 === 'fill'));
          $normCell.append($kindSel);
          function paintEngraveNormFields() {
            $normCell.find('.tc-engrave-contour-wrap, .tc-engrave-fill-wrap').remove();
            var k = ($kindSel.val() || 'contour').trim();
            $kindField.val(k);
            var rowLabel = k === 'fill' ? 'Площадь заливки' : 'Метры контура';
            $nameEl.text(rowLabel).attr('title', rowLabel);
            if (k === 'fill') {
              $cutField.val('');
              var $fillWrap = $('<div class="tc-engrave-fill-wrap tc-item-card-cut-wrap"></div>');
              var $areaIn = $('<input type="text" class="tc-item-card-engrave-area vTextField" inputmode="decimal">');
              $areaIn.attr('placeholder', 'площадь');
              $areaIn.attr(
                'title',
                'Площадь заливки на 1 изделие, м². Стоимость = м² × ₽/м² этапа «Лазерная гравировка».'
              );
              $areaIn.attr('aria-label', 'Норма площади гравировки, м²');
              $areaIn.val($areaField.val() || '');
              $areaIn.on('input change', function () {
                $areaField.val($areaIn.val());
              });
              $fillWrap.append($areaIn);
              $fillWrap.append($('<span class="tc-item-card-cut-unit"></span>').text('м²'));
              $normCell.append($fillWrap);
            } else {
              $areaField.val('');
              var $cWrap = $('<div class="tc-engrave-contour-wrap tc-item-card-cut-wrap"></div>');
              var $cIn = $('<input type="text" class="tc-item-card-cut vTextField" inputmode="decimal">');
              $cIn.attr('placeholder', 'контур');
              $cIn.attr(
                'title',
                'Метры контура на 1 изделие. Стоимость = м × ₽/м этапа «Лазерная гравировка».'
              );
              $cIn.attr('aria-label', 'Норма контура гравировки, м');
              $cIn.val($cutField.val() || '');
              $cIn.on('input change', function () {
                $cutField.val($cIn.val());
              });
              $cWrap.append($cIn);
              $cWrap.append($('<span class="tc-item-card-cut-unit"></span>').text('м'));
              $normCell.append($cWrap);
            }
          }
          $kindSel.on('change', paintEngraveNormFields);
          paintEngraveNormFields();
        } else {
          var $qty = $('<input type="text" class="tc-item-card-qty vTextField">');
          $qty.attr('placeholder', 'Норма');
          $qty.attr('title', 'Расход материала на 1 изделие (в единицах материала: лист, шт и т.п.)');
          $qty.val(qty);
          $qty.on('input change', function () {
            $row.find('[name$="-quantity"]').val($qty.val()).trigger('change');
          });
          var $unitSel = $('<select class="tc-item-card-unit" aria-label="Единица измерения"></select>');
          $unitSel.append(new Option(unit, unit, true, true));
          $normCell.append($qty);
          $normCell.append($unitSel);
        }

        if (!laserMeterOnly && stageSupportsCutMeters(sk)) {
          var cutVal = $cutField.val() || '';
          var $cutWrap = $('<div class="tc-item-card-cut-wrap"></div>');
          var $cut = $('<input type="text" class="tc-item-card-cut vTextField" inputmode="decimal">');
          $cut.attr('placeholder', 'рез');
          $cut.attr(
            'title',
            'Длина реза/траектории на 1 изделие, м. Не путать с ед. материала (лист). Стоимость = м × ₽/м этапа.'
          );
          $cut.attr('aria-label', 'Норма длины реза, м');
          $cut.val(cutVal);
          $cut.on('input change', function () {
            $cutField.val($cut.val()).trigger('change');
          });
          $cutWrap.append($cut);
          $cutWrap.append($('<span class="tc-item-card-cut-unit"></span>').text('м'));
          $normCell.append($cutWrap);
        } else if (!laserMeterOnly && $cutField.length) {
          /* На шлифовке/сборке и т.п. метры реза не нужны */
          $cutField.val('');
        }
        $card.append($normCell);

        var $techCell = $('<div class="tc-item-card-tech-cell"></div>');
        $techCell.attr(
          'title',
          'Техкарта изготовления полуфабриката (то же изделие, что в позиции).'
        );
        var $hiddenTc = $row.find('select[name$="-component_tech_card"]');
        var pidComp = rowProductId($row);
        var tcSaved =
          ($hiddenTc.val() || '').trim() ||
          ($row.attr('data-component-tech-card-id') || '').trim();

        if (kind === K.component && pidComp) {
          var $techSel = $(
            '<select class="tc-item-card-tech-select vTextField" aria-label="Техкарта полуфабриката"></select>'
          );
          var rowDomId = $row.attr('id') || '';

          function rowById() {
            return rowDomId ? $(document.getElementById(rowDomId)) : $row;
          }

          function fillTechSelectFromRows(rows) {
            var $r = rowById();
            if (!$r.length) {
              return;
            }
            var $h = $r.find('select[name$="-component_tech_card"]');
            $techSel.empty();
            $techSel.append(new Option('—', '', false, false));
            rows.forEach(function (tc) {
              if (tc && tc.id != null) {
                $techSel.append(new Option(tc.name || '#' + tc.id, String(tc.id)));
              }
            });
            var v = ($h.val() || '').trim() || ($r.attr('data-component-tech-card-id') || '').trim();
            if (v && !optExists($techSel, v)) {
              $techSel.append(new Option('#' + v, v, true, true));
            }
            if (v) {
              $techSel.val(String(v));
            }
            $h.empty();
            $techSel.find('option').each(function () {
              $h.append(new Option(this.text, this.value, false, false));
            });
            $h.val($techSel.val() || '');
            $h.trigger('change');
          }

          function rebuildVisibleFromHidden() {
            $techSel.empty();
            $techSel.append(new Option('—', '', false, false));
            var nReal = 0;
            $hiddenTc.find('option').each(function () {
              var val = (this.value || '').trim();
              var txt = (this.text || '').trim();
              if (!val && (txt === '' || txt === '---------')) {
                return;
              }
              nReal += 1;
              $techSel.append(new Option(txt || val, val, this.selected, this.selected));
            });
            var v = ($hiddenTc.val() || '').trim() || tcSaved;
            if (v && !optExists($techSel, v)) {
              $techSel.append(new Option('#' + v, String(v), true, true));
            }
            $techSel.val(v ? String(v) : '');
            return nReal;
          }

          var nReal = rebuildVisibleFromHidden();
          if (nReal === 0) {
            var $z = $techSel.find('option').first();
            if ($z.length) {
              $z.text('Загрузка…');
            }
            withTechCardsForProduct(pidComp, function (rows) {
              fillTechSelectFromRows(rows);
            });
          }

          $techSel.on('change', function () {
            var $r = rowById();
            if (!$r.length) {
              return;
            }
            var $h = $r.find('select[name$="-component_tech_card"]');
            if (!$h.length) {
              return;
            }
            var v = ($techSel.val() || '').trim();
            $h.val(v || '');
            $r.attr('data-component-tech-card-id', v);
            $h.trigger('change');
          });

          $techCell.append($techSel);
        } else {
          $techCell.append(
            $('<span class="tc-item-card-tech-placeholder"></span>').text(
              kind === K.component ? 'Укажите изделие' : '—'
            )
          );
        }
        $card.append($techCell);

        var $menuWrap = $('<div class="tc-item-card-menu-wrap"></div>');
        var $kebab = $('<button type="button" class="tc-item-card-kebab" aria-haspopup="true" aria-expanded="false"></button>');
        $kebab.append($('<span class="tc-item-card-kebab-dot"></span>'));
        $kebab.append($('<span class="tc-item-card-kebab-dot"></span>'));
        $kebab.append($('<span class="tc-item-card-kebab-dot"></span>'));
        var $pop = $('<div class="tc-item-card-menu" role="menu" hidden></div>');
        var items = laserMeterOnly
          ? [{ act: 'delete', label: 'Удалить' }]
          : [
              { act: 'open-card', label: 'Открыть карточку товара' },
              { act: 'replace', label: 'Заменить товар' },
              { act: 'edit-techcard', label: 'Редактировать техкарту' },
              { act: 'create-techcard', label: 'Создать техкарту товара' },
              { act: 'delete', label: 'Удалить' },
            ];
        items.forEach(function (it) {
          $pop.append(
            $('<button type="button" role="menuitem"></button>')
              .attr('data-act', it.act)
              .text(it.label)
          );
        });
        $menuWrap.append($kebab);
        $menuWrap.append($pop);
        $card.append($('<div class="tc-item-card-col-menu"></div>').append($menuWrap));

        appendCard($card, sk);
      });

      setupStageSearches();
      syncMaterialHeaderSelectionUi();
      layoutStagePanelGrid();
    }

    /** Схлопывает частые вызовы — меньше нагрузка на слабый ПК при открытой техкарте. */
    function rebuildMirrors() {
      if (rebuildMirrorsTimer) {
        window.clearTimeout(rebuildMirrorsTimer);
      }
      rebuildMirrorsTimer = window.setTimeout(function () {
        rebuildMirrorsTimer = null;
        rebuildMirrorsImpl();
      }, 60);
    }

    function layoutStagePanelGrid() {
      $group.find('.tc-stage-panel').each(function () {
        var panel = this;
        var $panel = $(panel);
        var $rail = $panel.find('.tc-stage-name-rail');
        var railEl = $rail[0];
        var $cards = $panel.find('.tc-item-card');
        var n = $cards.length;
        var $footer = $panel.find('.tc-stage-search-footer');
        var footEl = $footer[0];
        $panel.toggleClass('tc-stage-panel--empty', n === 0);
        if (railEl) {
          railEl.style.gridColumn = '1';
          if (n === 0) {
            railEl.style.gridRow = '1';
          } else {
            railEl.style.gridRow = '1 / span ' + n;
          }
        }
        $cards.each(function (idx) {
          this.style.gridColumn = '1 / -1';
          this.style.gridRow = String(idx + 1);
        });
        if (footEl) {
          if (n === 0) {
            footEl.style.gridColumn = '3 / -1';
            footEl.style.gridRow = '1';
          } else {
            footEl.style.gridColumn = '1 / -1';
            footEl.style.gridRow = String(n + 1);
          }
        }
      });
    }

    function removeRow($row) {
      var $cb = $row.find('input[name$="-DELETE"]');
      if ($cb.length) {
        $cb.prop('checked', true);
        $row.hide();
      } else {
        var $link = $row.find('a.inline-deletelink');
        if ($link.length) {
          $link.trigger('click');
        }
      }
      setTimeout(rebuildMirrors, 80);
    }

    /** Порядок строк комплектующих в POST и при перезагрузке (поле composition_order). */
    function syncCompositionOrderForComponents() {
      var n = 0;
      var $tb = backendItemTbody();
      $tb
        .find('tr.form-row')
        .not('.empty-form')
        .not('.add-row')
        .not('.row-form-errors')
        .each(function () {
          var $r = $(this);
          if (isRowDeleted($r)) {
            return;
          }
          if (rowItemKind($r) !== K.component) {
            return;
          }
          var $in = $r.find('[name$="-composition_order"]');
          if ($in.length) {
            $in.val(String(n++));
          }
        });
    }

    var PRODUCT_COMP_DRAG_TYPE = 'application/x-techcard-product-comp';

    function parseProductCompDragData(e) {
      try {
        var raw = e.originalEvent.dataTransfer.getData(PRODUCT_COMP_DRAG_TYPE);
        if (!raw) {
          return null;
        }
        return JSON.parse(raw);
      } catch (errP) {
        return null;
      }
    }

    function clearProductCompDragOver() {
      $('#tc-ms-product-composition-tbody tr.tc-ms-product-comp-row').removeClass(
        'tc-ms-product-comp-row--drag-over'
      );
    }

    function bindProductTabUiOnce() {
      if ($('body').data('tcProductTabUi')) {
        return;
      }
      $('body').data('tcProductTabUi', true);
      $(document).on('click', '#tc-ms-panel-product .tc-ms-product-comp-remove', function (e) {
        e.preventDefault();
        var $tr = $(this).closest('.tc-ms-product-comp-row');
        var rid = ($tr.attr('data-row-id') || '').trim();
        removeRow($rowFromCardId(rid));
      });
      $(document).on('dragstart.tcProductComp', '#tc-ms-panel-product .tc-item-card-drag', function (e) {
        var $tr = $(this).closest('.tc-ms-product-comp-row');
        var rid = $tr.attr('data-row-id');
        try {
          e.originalEvent.dataTransfer.setData(
            PRODUCT_COMP_DRAG_TYPE,
            JSON.stringify({ rowId: rid })
          );
          e.originalEvent.dataTransfer.effectAllowed = 'move';
        } catch (errD) {}
      });
      $(document).on('dragend.tcProductComp', '#tc-ms-panel-product .tc-item-card-drag', function () {
        clearProductCompDragOver();
      });
      $(document).on(
        'dragover.tcProductComp',
        '#tc-ms-product-composition-tbody tr.tc-ms-product-comp-row',
        function (e) {
          e.preventDefault();
          e.stopPropagation();
          var $tr = $(this);
          $tr.siblings('.tc-ms-product-comp-row').removeClass('tc-ms-product-comp-row--drag-over');
          $tr.addClass('tc-ms-product-comp-row--drag-over');
          try {
            e.originalEvent.dataTransfer.dropEffect = 'move';
          } catch (errO) {}
        }
      );
      $(document).on('dragleave.tcProductComp', '#tc-ms-product-composition-tbody tr.tc-ms-product-comp-row', function (
        ev
      ) {
        var rel = ev.relatedTarget;
        if (rel && this.contains(rel)) {
          return;
        }
        $(this).removeClass('tc-ms-product-comp-row--drag-over');
      });
      $(document).on('drop.tcProductComp', '#tc-ms-product-composition-tbody tr.tc-ms-product-comp-row', function (e) {
        e.preventDefault();
        e.stopPropagation();
        clearProductCompDragOver();
        var data = parseProductCompDragData(e);
        if (!data || !data.rowId) {
          return;
        }
        var $src = $rowFromCardId(String(data.rowId));
        var tgtRid = ($(this).attr('data-row-id') || '').trim();
        var $tgt = $rowFromCardId(tgtRid);
        if (!$src.length || !$tgt.length || $src[0] === $tgt[0]) {
          return;
        }
        var rect = this.getBoundingClientRect();
        var before = e.originalEvent.clientY < rect.top + rect.height / 2;
        if (before) {
          $src.insertBefore($tgt);
        } else {
          $src.insertAfter($tgt);
        }
        syncCompositionOrderForComponents();
        rebuildMirrors();
      });
      $(document).on('dragover.tcProductComp', '#tc-ms-product-composition-tbody', function (e) {
        if ($(e.target).closest('tr.tc-ms-product-comp-row').length) {
          return;
        }
        e.preventDefault();
        try {
          e.originalEvent.dataTransfer.dropEffect = 'move';
        } catch (errT) {}
      });
      $(document).on('drop.tcProductComp', '#tc-ms-product-composition-tbody', function (e) {
        if ($(e.target).closest('tr.tc-ms-product-comp-row').length) {
          return;
        }
        e.preventDefault();
        var data = parseProductCompDragData(e);
        if (!data || !data.rowId) {
          return;
        }
        var $src = $rowFromCardId(String(data.rowId));
        if (!$src.length) {
          return;
        }
        var $last = $();
        backendItemTbody()
          .find('tr.form-row')
          .not('.empty-form')
          .not('.add-row')
          .not('.row-form-errors')
          .each(function () {
            var $r = $(this);
            if (isRowDeleted($r)) {
              return;
            }
            if (rowItemKind($r) === K.component) {
              $last = $r;
            }
          });
        if ($last.length) {
          $src.insertAfter($last);
        }
        syncCompositionOrderForComponents();
        rebuildMirrors();
      });
    }

    function continueMaterialBatchAfterRow() {
      var next = null;
      while (materialBatchTail.length > 0) {
        var cand = materialBatchTail.shift();
        if (!isDuplicate(K.material, 'material', cand.id, materialBatchStageId)) {
          next = cand;
          break;
        }
      }
      if (next) {
        pendingAdd = {
          kind: K.material,
          id: next.id,
          text: next.name,
          stageId: materialBatchStageId,
          quantity: next.qty,
        };
        adding = true;
        window.setTimeout(function () {
          var $lnk = getAddLink();
          if ($lnk.length) {
            $lnk[0].click();
          } else {
            pendingAdd = null;
            adding = false;
            materialBatchTail = [];
            materialBatchStageId = '';
            rebuildMirrors();
          }
        }, 60);
        return;
      }
      materialBatchStageId = '';
      rebuildMirrors();
    }

    function queueAddBatch(stageId, items) {
      materialBatchTail = [];
      materialBatchStageId = '';
      if (!items || !items.length) {
        return;
      }
      var valid = [];
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var qn = parseMaterialQty(it.qty);
        if (qn == null || qn <= 0) {
          continue;
        }
        if (isDuplicate(K.material, 'material', it.id, stageId)) {
          continue;
        }
        valid.push({ id: it.id, name: it.name, qty: qn });
      }
      if (!valid.length) {
        return;
      }
      materialBatchTail = valid.slice(1);
      materialBatchStageId = stageId != null ? String(stageId) : '';
      var first = valid[0];
      pendingAdd = {
        kind: K.material,
        id: first.id,
        text: first.name,
        stageId: stageId,
        quantity: first.qty,
      };
      adding = true;
      var $addLink = getAddLink();
      if (!$addLink.length) {
        pendingAdd = null;
        adding = false;
        materialBatchTail = [];
        materialBatchStageId = '';
        return;
      }
      $addLink[0].click();
    }

    function queueAddLaserCutNorm(stageId, cutMeters) {
      materialBatchTail = [];
      materialBatchStageId = '';
      if (adding || pendingAdd) {
        return;
      }
      var $addLink = getAddLink();
      if (!$addLink.length) {
        return;
      }
      pendingAdd = {
        kind: 'laser_cut',
        stageId: stageId,
        cutMeters: cutMeters != null ? String(cutMeters).trim() : '',
      };
      adding = true;
      $addLink[0].click();
      window.setTimeout(function () {
        if (adding && pendingAdd) {
          adding = false;
          pendingAdd = null;
        }
      }, 3000);
    }

    function queueAddLaserEngraveNorm(stageId, normValue, engraveKind) {
      materialBatchTail = [];
      materialBatchStageId = '';
      if (adding || pendingAdd) {
        return;
      }
      var $addLink = getAddLink();
      if (!$addLink.length) {
        return;
      }
      var ek = (engraveKind || 'contour').trim() || 'contour';
      pendingAdd = {
        kind: 'laser_engrave',
        stageId: stageId,
        engraveKind: ek,
        normValue: normValue != null ? String(normValue).trim() : '',
        cutMeters: normValue != null ? String(normValue).trim() : '',
      };
      adding = true;
      $addLink[0].click();
      window.setTimeout(function () {
        if (adding && pendingAdd) {
          adding = false;
          pendingAdd = null;
        }
      }, 3000);
    }

    function queueAdd(kind, id, text, fkName, stageId) {
      materialBatchTail = [];
      materialBatchStageId = '';
      if (adding || pendingAdd) {
        return;
      }
      if (isDuplicate(kind, fkName, id, stageId)) {
        return;
      }
      var $addLink = getAddLink();
      if (!$addLink.length) {
        return;
      }
      pendingAdd = { kind: kind, id: id, text: text, stageId: stageId };
      adding = true;
      $addLink[0].click();
      window.setTimeout(function () {
        if (adding && pendingAdd) {
          adding = false;
          pendingAdd = null;
        }
      }, 3000);
    }

    document.addEventListener(
      'formset:added',
      function (e) {
        if (!pendingAdd) {
          return;
        }
        var row = e.target;
        if (row && typeof row.closest === 'function') {
          var tr = row.closest('tr.form-row');
          if (tr) {
            row = tr;
          }
        }
        if (!row || !row.classList || !row.classList.contains('form-row')) {
          return;
        }
        var $row = $(row);
        if (!$row.closest('#' + prefix + '-group').length) {
          return;
        }
        if (!$row.find('[name^="' + prefix + '-"][name$="-item_kind"]').length) {
          return;
        }
        var p = pendingAdd;
        window.setTimeout(function () {
          applyPendingToRow($row, p);
          if (p.kind === K.component) {
            syncCompositionOrderForComponents();
          }
          pendingAdd = null;
          adding = false;
          if (p.kind === 'laser_cut' || p.kind === 'laser_engrave') {
            rebuildMirrors();
            return;
          }
          prefetchRowUnits($row, continueMaterialBatchAfterRow, {
            autofillNorm: true,
            forceAutofill: !(p.quantity != null && String(p.quantity).trim() !== ''),
          });
        }, 220);
      },
      false
    );

    document.addEventListener('formset:removed', function () {
      window.setTimeout(rebuildMirrors, 80);
    });

    var openMaterialPicker = null;
    if (U.materialPickerGroups && U.materialPickerItems) {
      (function () {
        var $overlay = null;
        var $toolbar = null;
        var $table = null;
        var $side = null;
        var $more = null;
        var mpStageId = '';
        var mpGroup = '';
        var mpSearchTimer = null;
        var mpPage = 1;
        var mpLoading = false;

        function renderGroups(groups) {
          $side.empty();
          (groups || []).forEach(function (g) {
            var $b = $('<button type="button" class="tc-mp-group-btn"></button>').text(g.name || '');
            var isAll = g.id == null;
            var gkey = isAll ? '' : String(g.id);
            if (isAll) {
              $b.attr('data-group', 'all');
            } else {
              $b.attr('data-group', gkey);
            }
            if (
              (mpGroup === '' && isAll) ||
              (!isAll && String(mpGroup) === gkey)
            ) {
              $b.addClass('is-active');
            }
            $b.on('click', function () {
              mpGroup = gkey;
              $side.find('.tc-mp-group-btn').removeClass('is-active');
              $b.addClass('is-active');
              loadItems(true);
            });
            $side.append($b);
          });
        }

        function appendRows(results) {
          var $tbEl = $table.find('tbody');
          (results || []).forEach(function (r) {
            var $tr = $('<tr></tr>')
              .attr('data-mid', r.id)
              .attr('data-mname', r.name || '');
            $tr.append($('<td></td>').text(r.name || ''));
            var $inp = $(
              '<input type="text" class="tc-mp-qty" value="0" inputmode="decimal" autocomplete="off" />'
            );
            $tr.append($('<td class="tc-mp-col-qty"></td>').append($inp));
            $tr.append($('<td></td>').text(r.stock != null ? r.stock : '—'));
            $tr.append($('<td></td>').text(r.unit || '—'));
            var typeCol = (r.material_type || '').trim();
            if (!typeCol && r.group_name) {
              typeCol = r.group_name;
            }
            $tr.append($('<td></td>').text(typeCol || '—'));
            $tbEl.append($tr);
          });
        }

        function loadItems(reset) {
          if (mpLoading || !$table || !$toolbar) {
            return;
          }
          if (reset) {
            mpPage = 1;
            $table.find('tbody').empty();
          }
          mpLoading = true;
          var q = ($toolbar.find('.tc-mp-search').val() || '').trim();
          var gq = mpGroup === '' ? 'all' : mpGroup;
          var url =
            U.materialPickerItems +
            (U.materialPickerItems.indexOf('?') >= 0 ? '&' : '?') +
            'group=' +
            encodeURIComponent(gq) +
            '&q=' +
            encodeURIComponent(q) +
            '&page=' +
            mpPage +
            '&page_size=80';
          fetch(url, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
          })
            .then(function (r) {
              if (!r.ok) {
                throw new Error('picker');
              }
              return r.json();
            })
            .then(function (data) {
              appendRows(data.results || []);
              if (data.more) {
                $more.removeAttr('hidden');
              } else {
                $more.attr('hidden', 'hidden');
              }
              mpPage += 1;
            })
            .catch(function () {})
            .then(function () {
              mpLoading = false;
            });
        }

        function ensureDom() {
          if ($overlay && $overlay.length) {
            return;
          }
          $overlay = $('<div class="tc-mp-overlay" hidden role="presentation"></div>');
          var $dlg = $(
            '<div class="tc-mp-dialog" role="dialog" aria-modal="true" aria-labelledby="tc-mp-title"></div>'
          );
          $dlg.append(
            '<div class="tc-mp-head"><h2 id="tc-mp-title">Выбор материалов</h2><button type="button" class="tc-mp-close" aria-label="Закрыть">×</button></div>'
          );
          $toolbar = $(
            '<div class="tc-mp-toolbar"><input type="search" class="tc-mp-search" placeholder="Наименование или тип материала" autocomplete="off" /></div>'
          );
          var $body = $('<div class="tc-mp-body"></div>');
          $side = $('<nav class="tc-mp-sidebar" aria-label="Группы материалов"></nav>');
          var $main = $('<div class="tc-mp-main"></div>');
          var $tw = $('<div class="tc-mp-table-wrap"></div>');
          $table = $(
            '<table class="tc-mp-table"><thead><tr><th>Наименование</th><th class="tc-mp-col-qty">Норма на изд.</th><th>Остаток</th><th>Ед.</th><th>Тип / группа</th></tr></thead><tbody></tbody></table>'
          );
          $tw.append($table);
          $more = $(
            '<button type="button" class="tc-mp-loadmore">Показать ещё</button>'
          ).attr('hidden', 'hidden');
          $main.append($tw);
          $main.append($more);
          $body.append($side);
          $body.append($main);
          var $foot = $(
            '<div class="tc-mp-footer"><button type="button" class="tc-mp-btn-primary">Выбрать</button><button type="button" class="tc-mp-btn-secondary">Отмена</button><p class="tc-mp-hint">Введите норму в нужных строках (&gt; 0) и нажмите «Выбрать» — все такие материалы сразу попадут в техкарту на выбранный этап.</p></div>'
          );
          $dlg.append($toolbar);
          $dlg.append($body);
          $dlg.append($foot);
          $overlay.append($dlg);
          $('body').append($overlay);

          function closeMp() {
            $overlay.attr('hidden', 'hidden');
          }

          $overlay.on('click', function (ev) {
            if (ev.target === $overlay[0]) {
              closeMp();
            }
          });
          $dlg.on('click', '.tc-mp-close', closeMp);
          $dlg.on('click', '.tc-mp-btn-secondary', closeMp);

          $dlg.on('click', '.tc-mp-btn-primary', function () {
            var rows = [];
            $table.find('tbody tr').each(function () {
              var $tr = $(this);
              var id = $tr.attr('data-mid');
              var name = ($tr.attr('data-mname') || '').trim();
              var qv = $tr.find('.tc-mp-qty').val();
              rows.push({ id: id, name: name, qty: qv });
            });
            queueAddBatch(mpStageId, rows);
            closeMp();
          });

          $more.on('click', function () {
            if (!mpLoading) {
              loadItems(false);
            }
          });

          $toolbar.find('.tc-mp-search').on('input', function () {
            window.clearTimeout(mpSearchTimer);
            mpSearchTimer = window.setTimeout(function () {
              loadItems(true);
            }, 320);
          });
        }

        openMaterialPicker = function (stageId) {
          ensureDom();
          mpStageId = stageId != null ? String(stageId) : '';
          mpGroup = '';
          $toolbar.find('.tc-mp-search').val('');
          $table.find('tbody').empty();
          mpPage = 1;
          $overlay.removeAttr('hidden');

          fetch(U.materialPickerGroups, {
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
          })
            .then(function (r) {
              if (!r.ok) {
                throw new Error('groups');
              }
              return r.json();
            })
            .then(function (data) {
              renderGroups(data.groups || []);
              loadItems(true);
            })
            .catch(function () {
              renderGroups([{ id: null, name: 'Все материалы' }]);
              loadItems(true);
            });
        };
      })();
    }

    function setupStageSearches() {
      $group.find('.tc-stage-panel').each(function () {
        var $panel = $(this);
        var stageId = $panel.attr('data-stage-id');
        var $input = $panel.find('.tc-item-search-input');
        var $dd = $panel.find('.tc-item-dropdown');
        var $btn = $panel.find('.tc-item-add-from-directory');
        var timer;

        $input.off('.tcStg');
        $btn.off('.tcStg');
        if (stageIsLaserCutOnly(stageId) || stageIsLaserEngraveOnly(stageId)) {
          $input.on('keydown.tcStg', function (e) {
            if (e.key !== 'Enter') {
              return;
            }
            e.preventDefault();
            var v = ($input.val() || '').trim();
            if (stageIsLaserEngraveOnly(stageId)) {
              var ek = 'contour';
              var $fk = $panel.find('.tc-engrave-footer-kind');
              if ($fk.length) {
                ek = ($fk.val() || 'contour').trim() || 'contour';
              }
              queueAddLaserEngraveNorm(stageId, v, ek);
            } else {
              queueAddLaserCutNorm(stageId, v);
            }
            $input.val('');
          });
          return;
        }

        function buildMaterialAcUrl(term, page) {
          var u =
            acUrl +
            (acUrl.indexOf('?') !== -1 ? '&' : '?') +
            materialParams +
            '&term=' +
            encodeURIComponent(term != null ? String(term) : '');
          if (page && page > 1) {
            u += '&page=' + page;
          }
          return u;
        }

        function fillMaterialDropdown(results) {
          var kind = K.material;
          var fkName = 'material';
          $dd.empty();
          results.forEach(function (item) {
            var li = document.createElement('li');
            li.textContent = item.text;
            li.addEventListener('click', function () {
              queueAdd(kind, item.id, item.text, fkName, stageId);
              $input.val('');
              $dd.removeClass('visible').empty();
            });
            $dd.append(li);
          });
          if (results.length) {
            $dd.addClass('visible');
          } else {
            $dd.removeClass('visible');
          }
        }

        function runAutocomplete(term) {
          var trimmed = (term != null ? String(term) : '').trim();
          var fetchOpts = {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
          };

          /* Пустой term + «Добавить из справочника»: Django отдаёт только 20 записей на страницу —
           * дальше по алфавиту материал не виден. Подгружаем страницы, пока есть pagination.more. */
          if (trimmed === '') {
            var merged = [];
            var seen = {};
            var page = 1;
            var maxPages = 40;

            function loadNext() {
              fetch(buildMaterialAcUrl('', page), fetchOpts)
                .then(function (r) {
                  if (!r.ok) {
                    throw new Error('autocomplete http');
                  }
                  return r.json();
                })
                .then(function (data) {
                  var results = data && data.results ? data.results : [];
                  results.forEach(function (item) {
                    if (item && item.id != null && !seen[item.id]) {
                      seen[item.id] = true;
                      merged.push(item);
                    }
                  });
                  var more = data && data.pagination && data.pagination.more;
                  if (more && page < maxPages) {
                    page += 1;
                    loadNext();
                  } else {
                    merged.sort(function (a, b) {
                      return String(a.text || '').localeCompare(String(b.text || ''), 'ru', {
                        sensitivity: 'base',
                      });
                    });
                    fillMaterialDropdown(merged);
                  }
                })
                .catch(function () {
                  $dd.removeClass('visible');
                });
            }

            loadNext();
            return;
          }

          var mergedT = [];
          var seenT = {};
          var pTyped = 1;
          var maxTypedPages = 12;

          function loadTypedPage() {
            fetch(buildMaterialAcUrl(trimmed, pTyped), fetchOpts)
              .then(function (r) {
                if (!r.ok) {
                  throw new Error('autocomplete http');
                }
                return r.json();
              })
              .then(function (data) {
                var results = data && data.results ? data.results : [];
                results.forEach(function (item) {
                  if (item && item.id != null && !seenT[item.id]) {
                    seenT[item.id] = true;
                    mergedT.push(item);
                  }
                });
                var more = data && data.pagination && data.pagination.more;
                if (more && pTyped < maxTypedPages) {
                  pTyped += 1;
                  loadTypedPage();
                } else {
                  fillMaterialDropdown(mergedT);
                }
              })
              .catch(function () {
                $dd.removeClass('visible');
              });
          }

          loadTypedPage();
        }

        $input.on('input.tcStg', function () {
          var q = ($input.val() || '').trim();
          window.clearTimeout(timer);
          $dd.removeClass('visible').empty();
          if (q.length < 1) {
            return;
          }
          timer = window.setTimeout(function () {
            runAutocomplete(q);
          }, 200);
        });

        $btn.on('click.tcStg', function (ev) {
          ev.preventDefault();
          if (openMaterialPicker) {
            openMaterialPicker(stageId);
          } else {
            $input.trigger('focus');
            runAutocomplete('');
          }
        });
      });
    }

    function setupProductTabSearch() {
      var $panel = $('#tc-ms-panel-product');
      if (!$panel.length || $panel.data('tcProdSearchReady')) {
        return;
      }
      $panel.data('tcProdSearchReady', true);
      var $input = $panel.find('.tc-ms-product-search-input').first();
      var $dd = $panel.find('.tc-item-dropdown').first();
      var $btn = $panel.find('.tc-ms-product-add-from-directory').first();
      var timer;

      function defaultProductStageId() {
        var st = currentStages();
        return st.length ? String(st[0].id) : '';
      }

      function buildProductAcUrl(term, page) {
        var u =
          acUrl +
          (acUrl.indexOf('?') !== -1 ? '&' : '?') +
          productParams +
          '&term=' +
          encodeURIComponent(term != null ? String(term) : '');
        if (page && page > 1) {
          u += '&page=' + page;
        }
        return u;
      }

      function fillProductDropdown(results) {
        var fkName = 'product';
        var stageId = defaultProductStageId();
        $dd.empty();
        results.forEach(function (item) {
          var li = document.createElement('li');
          li.textContent = item.text;
          li.addEventListener('click', function () {
            queueAdd(K.component, item.id, item.text, fkName, stageId);
            $input.val('');
            $dd.removeClass('visible').empty();
          });
          $dd.append(li);
        });
        if (results.length) {
          $dd.addClass('visible');
        } else {
          $dd.removeClass('visible');
        }
      }

      function runProductAutocomplete(term) {
        var trimmed = (term != null ? String(term) : '').trim();
        var fetchOpts = {
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        };

        if (trimmed === '') {
          var merged = [];
          var seen = {};
          var page = 1;
          var maxPages = 40;

          function loadNext() {
            fetch(buildProductAcUrl('', page), fetchOpts)
              .then(function (r) {
                if (!r.ok) {
                  throw new Error('autocomplete http');
                }
                return r.json();
              })
              .then(function (data) {
                var results = data && data.results ? data.results : [];
                results.forEach(function (item) {
                  if (item && item.id != null && !seen[item.id]) {
                    seen[item.id] = true;
                    merged.push(item);
                  }
                });
                var more = data && data.pagination && data.pagination.more;
                if (more && page < maxPages) {
                  page += 1;
                  loadNext();
                } else {
                  merged.sort(function (a, b) {
                    return String(a.text || '').localeCompare(String(b.text || ''), 'ru', {
                      sensitivity: 'base',
                    });
                  });
                  fillProductDropdown(merged);
                }
              })
              .catch(function () {
                $dd.removeClass('visible');
              });
          }

          loadNext();
          return;
        }

        var mergedT = [];
        var seenT = {};
        var pTyped = 1;
        var maxTypedPages = 12;

        function loadTypedPage() {
          fetch(buildProductAcUrl(trimmed, pTyped), fetchOpts)
            .then(function (r) {
              if (!r.ok) {
                throw new Error('autocomplete http');
              }
              return r.json();
            })
            .then(function (data) {
              var results = data && data.results ? data.results : [];
              results.forEach(function (item) {
                if (item && item.id != null && !seenT[item.id]) {
                  seenT[item.id] = true;
                  mergedT.push(item);
                }
              });
              var more = data && data.pagination && data.pagination.more;
              if (more && pTyped < maxTypedPages) {
                pTyped += 1;
                loadTypedPage();
              } else {
                fillProductDropdown(mergedT);
              }
            })
            .catch(function () {
              $dd.removeClass('visible');
            });
        }

        loadTypedPage();
      }

      $input.on('input.tcProd', function () {
        var q = ($input.val() || '').trim();
        window.clearTimeout(timer);
        $dd.removeClass('visible').empty();
        if (q.length < 1) {
          return;
        }
        timer = window.setTimeout(function () {
          runProductAutocomplete(q);
        }, 200);
      });

      $btn.on('click.tcProd', function (ev) {
        ev.preventDefault();
        $input.trigger('focus');
        runProductAutocomplete('');
      });
    }

    $(document)
      .off('click.techcardItemsDd')
      .on('click.techcardItemsDd', function (e) {
        if (
          $(e.target).closest('.techcard-items-inline-group .tc-item-search-wrap').length ||
          $(e.target).closest('#tc-ms-panel-product .tc-item-search-wrap').length
        ) {
          return;
        }
        $('.techcard-items-inline-group .tc-item-dropdown, #tc-ms-panel-product .tc-item-dropdown').removeClass(
          'visible'
        );
      });

    var TC_TECH_COL_COLLAPSE_LS = 'techcardItemsTechColCollapsed';

    function applyTechColCollapsedFromStorage() {
      var root = $group[0];
      if (!root) {
        return;
      }
      var on = localStorage.getItem(TC_TECH_COL_COLLAPSE_LS) === '1';
      $group.toggleClass('tc-tech-col-collapsed', on);
      var $cb = $group.find('.tc-mgh-tech-col-collapse');
      if ($cb.length) {
        $cb.prop('checked', on);
      }
      if (on) {
        root.style.setProperty('--tc-tech-pref', '0px');
      } else {
        var wTech = parseInt(localStorage.getItem('techcardItemsTechColPx'), 10);
        if (!isFinite(wTech) || wTech < 80) {
          wTech = 120;
        }
        if (wTech > 240) {
          wTech = 240;
        }
        root.style.setProperty('--tc-tech-pref', wTech + 'px');
      }
    }

    function bindTechColCollapseOnce() {
      if ($group.data('tcTechColCollapse')) {
        return;
      }
      $group.data('tcTechColCollapse', true);
      $group.on('change', '.tc-mgh-tech-col-collapse', function () {
        var on = $(this).prop('checked');
        localStorage.setItem(TC_TECH_COL_COLLAPSE_LS, on ? '1' : '0');
        applyTechColCollapsedFromStorage();
      });
    }

    function bindMaterialsColumnResizesOnce() {
      if ($group.data('tcMatColResize')) {
        return;
      }
      var root = $group[0];
      if (!root) {
        return;
      }
      $group.data('tcMatColResize', true);

      try {
        if (
          !localStorage.getItem('techcardItemsMaterialColPx') &&
          localStorage.getItem('techcardItemsMaterialMinPx')
        ) {
          localStorage.setItem(
            'techcardItemsMaterialColPx',
            localStorage.getItem('techcardItemsMaterialMinPx')
          );
        }
      } catch (eLs) {}

      var specs = [
        {
          sel: '.tc-mgh-stage',
          cssVar: '--tc-stage-pref',
          ls: 'techcardItemsStageColPx',
          min: 72,
          max: 480,
          def: 132,
          title: 'Ширина колонки «Этап»',
        },
        {
          sel: '.tc-mgh-code',
          cssVar: '--tc-code-pref',
          ls: 'techcardItemsCodeColPx',
          min: 48,
          max: 140,
          def: 72,
          title: 'Ширина колонки «Код»',
        },
        {
          sel: '.tc-mgh-material',
          cssVar: '--tc-material-pref',
          ls: 'techcardItemsMaterialColPx',
          min: 120,
          max: 560,
          def: 220,
          title: 'Ширина колонки «Материал»',
        },
        {
          sel: '.tc-mgh-norm',
          cssVar: '--tc-norm-pref',
          ls: 'techcardItemsNormColPx',
          min: 90,
          max: 220,
          def: 132,
          title: 'Ширина колонки «Норма»',
        },
        {
          sel: '.tc-mgh-tech',
          cssVar: '--tc-tech-pref',
          ls: 'techcardItemsTechColPx',
          min: 80,
          max: 280,
          def: 120,
          title: 'Ширина колонки «Техкарта»',
        },
      ];

      specs.forEach(function (sp) {
        var w = parseInt(localStorage.getItem(sp.ls), 10);
        if (!isFinite(w) || w < sp.min) {
          w = sp.def;
        }
        if (w > sp.max) {
          w = sp.max;
        }
        root.style.setProperty(sp.cssVar, w + 'px');
      });

      specs.forEach(function (sp) {
        var $h = $group.find('.tc-materials-grid-head ' + sp.sel).first();
        if (!$h.length || $h.find('.tc-col-resizer').length) {
          return;
        }
        var $g = $(
          '<span class="tc-col-resizer" role="separator" aria-orientation="vertical"></span>'
        );
        $g.attr('data-tc-resize-ls', sp.ls);
        $g.attr('title', sp.title);
        $h.append($g);
      });

      var dragState = null;

      function specByLs(ls) {
        for (var i = 0; i < specs.length; i++) {
          if (specs[i].ls === ls) {
            return specs[i];
          }
        }
        return null;
      }

      $group.on('mousedown.tcColR touchstart.tcColR', '.tc-col-resizer', function (e) {
        if ($group.hasClass('tc-tech-col-collapsed')) {
          var ls0 = $(this).attr('data-tc-resize-ls');
          if (ls0 === 'techcardItemsTechColPx') {
            return;
          }
        }
        var ls = $(this).attr('data-tc-resize-ls');
        var sp = specByLs(ls);
        if (!sp) {
          return;
        }
        var $head = $(this).closest('.tc-mgh-cell');
        if (!$head.length) {
          $head = $group.find('.tc-materials-grid-head ' + sp.sel).first();
        }
        dragState = {
          sp: sp,
          startX: e.type.indexOf('touch') === 0 ? e.originalEvent.touches[0].clientX : e.clientX,
          startW: $head[0] ? $head[0].getBoundingClientRect().width : 0,
        };
        e.preventDefault();
        $(document.body).css('cursor', 'col-resize');
      });

      $(document)
        .on('mousemove.tcColR touchmove.tcColR', function (e) {
          if (!dragState) {
            return;
          }
          var x =
            e.type.indexOf('touch') === 0
              ? e.originalEvent.touches[0].clientX
              : e.clientX;
          var nw = Math.round(dragState.startW + (x - dragState.startX));
          nw = Math.max(dragState.sp.min, Math.min(dragState.sp.max, nw));
          root.style.setProperty(dragState.sp.cssVar, nw + 'px');
          e.preventDefault();
        })
        .on('mouseup.tcColR touchend.tcColR', function () {
          if (!dragState) {
            return;
          }
          var sp = dragState.sp;
          dragState = null;
          $(document.body).css('cursor', '');
          var cur = root.style.getPropertyValue(sp.cssVar).trim();
          if (cur) {
            var px = parseInt(cur, 10);
            if (isFinite(px)) {
              localStorage.setItem(sp.ls, String(px));
            }
          }
        });
    }

    function clearComponentTechCardIfNeeded(el) {
      var $t = $(el);
      var name = $t.attr('name') || '';
      var $r = $t.closest('tr.form-row');
      if (!$r.length) {
        return;
      }
      var $htc = $r.find('select[name$="-component_tech_card"]');
      if (!$htc.length) {
        return;
      }
      if (name.indexOf('-product') !== -1) {
        $htc.val('').trigger('change');
        $r.attr('data-component-tech-card-id', '');
        return;
      }
      if (name.indexOf('-item_kind') !== -1 && rowItemKind($r) !== K.component) {
        $htc.val('').trigger('change');
        $r.attr('data-component-tech-card-id', '');
      }
    }

    function bindBackendRowMirrorOnce() {
      if ($group.data('tcBackendRowMirror')) {
        return;
      }
      $group.data('tcBackendRowMirror', true);
      $backend.on(
        'change.tcRowMirror',
        'select[name$="-material"], select[name$="-item_kind"], input[name$="-product"]',
        function () {
          clearComponentTechCardIfNeeded(this);
          var $r = $(this).closest('tr.form-row');
          var nm = ($(this).attr('name') || '');
          if (nm.indexOf('-item_kind') !== -1) {
            $r.attr('data-item-kind', ($(this).val() || '').trim());
          }
          window.setTimeout(function () {
            prefetchRowUnits($r, rebuildMirrors, {
              autofillNorm: true,
              forceAutofill: nm.indexOf('-material') !== -1,
            });
          }, 0);
        }
      );
      $backend.on(
        'select2:select.tcRowMirror select2:clear.tcRowMirror select2:unselect.tcRowMirror',
        'select[name$="-material"]',
        function () {
          clearComponentTechCardIfNeeded(this);
          var $r = $(this).closest('tr.form-row');
          window.setTimeout(function () {
            prefetchRowUnits($r, rebuildMirrors, {
              autofillNorm: true,
              forceAutofill: true,
            });
          }, 0);
        }
      );
    }

    window.addEventListener('tc-ms-tab-activate', function (ev) {
      if (ev && ev.detail && (ev.detail.name === 'materials' || ev.detail.name === 'product')) {
        window.setTimeout(rebuildMirrors, 0);
      }
    });

    bindBackendRowMirrorOnce();
    bindHeaderSelectionOnce();
    bindCardMenusOnce();
    bindStageDnDOnce();
    bindProductTabUiOnce();
    setupProductTabSearch();
    bindTechColCollapseOnce();
    bindMaterialsColumnResizesOnce();
    rebuildMirrorsImpl();
    window.setTimeout(rebuildMirrors, 450);
    applyTechColCollapsedFromStorage();
  }

  function boot() {
    if (!window.TECHCARD_ITEMS_UI || !window.TECHCARD_ITEMS_UI.prefix) {
      return;
    }
    if (typeof django === 'undefined' || !django.jQuery) {
      window.setTimeout(boot, 30);
      return;
    }
    var $ = django.jQuery;
    $(function () {
      window.setTimeout(init, 350);
    });
  }

  boot();
})();
