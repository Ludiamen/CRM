// Слайдер на узкой ширине, выбор в сетке, подтверждения (PLAN-003, «Где живёт код»); внешний файл из-за CSP.
(function () {
  var NARROW = 600;
  var listUrl = null;

  /* Узкая ширина: ссылка строки списка ведёт обычным переходом на страницу заявки, слайдера нет. */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var source = event.detail && event.detail.elt;
    if (!source || !source.getAttribute) {
      return;
    }
    if (source.getAttribute('hx-target') === '#slider-root' && window.innerWidth <= NARROW && source.href) {
      event.preventDefault();
      window.location.href = source.href;
    }
  });

  /* Слайдер: запоминаем адрес списка и возвращаем его при закрытии (hx-push-url меняет адрес на адрес заявки). */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === 'slider-root' && !/^\/tickets\/[0-9]+\/$/.test(window.location.pathname)) {
      listUrl = window.location.pathname + window.location.search;
    }
  });
  document.addEventListener('click', function (event) {
    var closer = event.target.closest ? event.target.closest('#slider-root [data-slider-close], #slider-root .slider-backdrop') : null;
    if (!closer) {
      return;
    }
    event.preventDefault();
    document.getElementById('slider-root').replaceChildren();
    if (listUrl && window.history && window.history.replaceState) {
      window.history.replaceState(null, '', listUrl);
    }
  });

  /* Групповая панель: видна только группа параметров выбранного действия. */
  function showBulkGroup() {
    var select = document.querySelector('#tickets-bulk select[name=action]');
    if (!select) {
      return;
    }
    Array.prototype.forEach.call(document.querySelectorAll('#tickets-bulk [data-bulk-action]'), function (group) {
      group.hidden = group.getAttribute('data-bulk-action') !== select.value;
    });
  }
  document.addEventListener('change', function (event) {
    if (event.target && event.target.matches && event.target.matches('#tickets-bulk select[name=action]')) {
      showBulkGroup();
    }
  });
  document.addEventListener('DOMContentLoaded', showBulkGroup);

  /* Панель фильтра: на широком экране открыта всегда; до 576 px сворачивается, если фильтр не задан. */
  function foldFilterPanel() {
    var panel = document.querySelector('details[data-filter-panel]');
    if (panel && window.innerWidth <= 576 && !panel.hasAttribute('data-filtered')) {
      panel.removeAttribute('open');
    }
  }
  document.addEventListener('DOMContentLoaded', foldFilterPanel);

  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (!target) {
      return;
    }
    /* Успех действия из диалога: карточка подменена, диалог закрывается. */
    if (target.hasAttribute && target.hasAttribute('data-ticket-card')) {
      var dialogRoot = document.getElementById('dialog-root');
      if (dialogRoot) {
        dialogRoot.replaceChildren();
      }
    }
    /* После группового действия сетка читается заново (решение T-3231: список сам её не обновляет). */
    if (target.id === 'bulk-result' && window.htmx) {
      var grid = document.getElementById('tickets-grid');
      if (grid) {
        window.htmx.ajax('GET', window.location.pathname + window.location.search, {target: '#tickets-grid', swap: 'outerHTML'});
      }
    }
  });
})();
