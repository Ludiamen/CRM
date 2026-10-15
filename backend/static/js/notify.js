// Системное уведомление во вкладке по фрагменту живых обновлений (PLAN-004, «Где живёт код»); внешний файл из-за CSP.
/* Два дела (CONTRACT-004 § 14.1):
   1. `#notify-bell[data-ws]` — состояние соединения `/ws/notify/`: `open` после первого кадра сервера
      (htmx:wsAfterMessage), `closed` по htmx:wsClose; шаблон рисует `connecting`.
   2. `#notify-toast` — кадр сервера заменяет пустой элемент таким же с `data-text`, `data-url`, `data-tag`,
      `data-show`; при `data-show="1"` и разрешении браузера показывается системное уведомление, нажатие
      открывает `data-url` в этой вкладке и закрывает уведомление (FR-320). */
(function () {
  'use strict';

  if (window.__notifyJsLoaded) { return; }
  window.__notifyJsLoaded = true;

  var handled = typeof WeakSet === 'function' ? new WeakSet() : null;

  function setWsState(state) {
    var bell = document.getElementById('notify-bell');
    if (bell) { bell.setAttribute('data-ws', state); }
  }

  document.addEventListener('htmx:wsAfterMessage', function () { setWsState('open'); });
  document.addEventListener('htmx:wsClose', function () { setWsState('closed'); });

  /* Ссылка из данных открывается только на своём источнике; иначе — главная. */
  function safeUrl(raw) {
    try {
      var url = new URL(raw, window.location.href);
      if (url.origin === window.location.origin) { return url.href; }
    } catch (e) { /* разбор не удался — главная */ }
    return '/';
  }

  function show(toast) {
    if (toast.getAttribute('data-show') !== '1') { return; }
    if (!('Notification' in window) || window.Notification.permission !== 'granted') { return; }
    var text = toast.getAttribute('data-text') || '';
    var url = toast.getAttribute('data-url') || '';
    var tag = toast.getAttribute('data-tag') || '';
    if (!text) { return; }
    var notification;
    try {
      notification = new window.Notification(text, { tag: tag, data: { url: url } });
    } catch (e) {
      return; // браузер не умеет конструктор (часть мобильных) — остаётся колокольчик
    }
    notification.onclick = function () {
      try { window.focus(); } catch (e) { /* окно не в фокусе — не страшно */ }
      notification.close();
      if (url) { window.location.href = safeUrl(url); }
    };
  }

  /* Каждый вставленный элемент разбирается один раз; пустой элемент страницы (`data-show="0"`) молчит. */
  function inspect(node) {
    if (!node || node.nodeType !== 1) { return; }
    var toasts = [];
    if (node.id === 'notify-toast') { toasts.push(node); }
    if (node.querySelectorAll) {
      Array.prototype.push.apply(toasts, node.querySelectorAll('#notify-toast'));
    }
    toasts.forEach(function (toast) {
      if (handled) {
        if (handled.has(toast)) { return; }
        handled.add(toast);
      }
      show(toast);
    });
  }

  function start() {
    // Элемент, уже стоящий на странице при загрузке, не показывается: это пустой шаблон колокольчика.
    var current = document.getElementById('notify-toast');
    if (current && handled) { handled.add(current); }
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        Array.prototype.forEach.call(record.addedNodes, inspect);
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  start();
})();
