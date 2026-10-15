// Подписка Web Push по кнопке (PLAN-004, «Где живёт код»); внешний файл из-за CSP.
/* Страница «Мои уведомления» (CONTRACT-004 § 13.2, 14.3, дополнение 27):
   1. `button[data-action="push-permission"]` — запрос разрешения браузера только по нажатию (FR-320); кнопка
      скрыта, когда разрешение уже дано или запрещено.
   2. `button[data-action="push-subscribe"]` — разрешение (если ещё нет) → регистрация `data-sw-url` →
      `pushManager.subscribe` с `data-vapid-public` → POST JSON на `data-subscribe-url` с CSRF. Скрыта только при
      `data-device-subscribed="1"` (признак с портала) и при запрете браузера.
   3. `[data-push-denied]` показывается, когда браузер запретил уведомления; обе кнопки скрыты.
   4. Ячейки `td[data-channel="push"][data-available="0"]` без разрешения браузера получают `data-locked="1"`,
      щелчок по флажку отменяется (значение уходит прежним).
   Слушатели общие (на документе), страница при замене корня HTMX заново ничего не вешает. */
(function () {
  'use strict';

  if (window.__notifyPushLoaded) { return; }
  window.__notifyPushLoaded = true;

  function permission() {
    return ('Notification' in window) ? window.Notification.permission : 'denied';
  }

  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  function setHidden(element, hidden) {
    if (!element) { return; }
    if (hidden) { element.setAttribute('hidden', ''); } else { element.removeAttribute('hidden'); }
  }

  /* Приводит страницу к состоянию разрешения браузера. */
  function sync() {
    var state = permission();
    var denied = state === 'denied';
    var permissionButton = document.querySelector('button[data-action="push-permission"]');
    var subscribeButton = document.querySelector('button[data-action="push-subscribe"]');
    setHidden(permissionButton, state !== 'default');
    if (subscribeButton) {
      setHidden(subscribeButton, denied || subscribeButton.getAttribute('data-device-subscribed') === '1');
    }
    setHidden(document.querySelector('[data-push-denied]'), !denied);
    var cells = document.querySelectorAll('td[data-channel="push"]');
    for (var i = 0; i < cells.length; i += 1) {
      var cell = cells[i];
      if (cell.getAttribute('data-available') === '0' && state !== 'granted') {
        cell.setAttribute('data-locked', '1');
      } else {
        cell.removeAttribute('data-locked');
      }
    }
  }

  function requestPermission() {
    if (!('Notification' in window)) { return Promise.resolve('denied'); }
    if (permission() !== 'default') { return Promise.resolve(permission()); }
    try {
      var result = window.Notification.requestPermission(function () { /* старая форма: ответ читаем ниже */ });
      return Promise.resolve(result).then(function () { return permission(); });
    } catch (e) {
      return Promise.resolve(permission());
    }
  }

  function keyBytes(base64url) {
    var padding = '='.repeat((4 - base64url.length % 4) % 4);
    var raw = window.atob((base64url + padding).replace(/-/g, '+').replace(/_/g, '/'));
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i += 1) { bytes[i] = raw.charCodeAt(i); }
    return bytes;
  }

  function send(button, subscription) {
    var data = subscription.toJSON();
    return window.fetch(button.getAttribute('data-subscribe-url'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify({ endpoint: data.endpoint, keys: data.keys })
    });
  }

  function subscribe(button) {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) { return; }
    button.disabled = true;
    requestPermission().then(function (state) {
      sync();
      if (state !== 'granted') { return null; }
      return navigator.serviceWorker.register(button.getAttribute('data-sw-url')).then(function () {
        return navigator.serviceWorker.ready;
      }).then(function (registration) {
        return registration.pushManager.getSubscription().then(function (existing) {
          return existing || registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: keyBytes(button.getAttribute('data-vapid-public') || '')
          });
        });
      }).then(function (subscription) {
        return send(button, subscription);
      }).then(function (response) {
        if (response && response.ok) { window.location.reload(); }
      });
    }).catch(function () {
      /* подписка не удалась (отказ браузера или сети): кнопка остаётся, сервер ничего не сохранил */
    }).then(function () {
      button.disabled = false;
    });
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var box = target.closest('td[data-channel="push"] input[type="checkbox"]');
    if (box && box.closest('td').getAttribute('data-locked') === '1') {
      event.preventDefault();
      return;
    }
    var permissionButton = target.closest('button[data-action="push-permission"]');
    if (permissionButton) {
      requestPermission().then(sync);
      return;
    }
    var subscribeButton = target.closest('button[data-action="push-subscribe"]');
    if (subscribeButton) { subscribe(subscribeButton); }
  });

  document.addEventListener('htmx:afterSettle', sync);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sync);
  } else {
    sync();
  }
})();
