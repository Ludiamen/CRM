/* Связка HTMX со страницей без inline-кода (CSP): защита от CSRF, закрытие слайдера клавишей Esc,
   фокус на панель после подгрузки. CSRF-кука с HttpOnly, поэтому токен берётся из скрытого поля
   формы выхода или любой другой формы страницы. */
(function () {
  document.addEventListener('htmx:configRequest', function (event) {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && !event.detail.headers['X-CSRFToken']) {
      event.detail.headers['X-CSRFToken'] = input.value;
    }
  });

  /* Диалог подтверждения (T-2231): откуда открыт — туда вернётся фокус после закрытия. */
  var dialogOpener = null;

  function rememberOpener(event) {
    var target = event.detail && (event.detail.target || (event.detail.requestConfig && event.detail.requestConfig.target));
    var source = event.detail && (event.detail.elt || (event.detail.requestConfig && event.detail.requestConfig.elt));
    if (target && target.id === 'dialog-root' && source) {
      dialogOpener = source;
    }
  }
  document.addEventListener('htmx:beforeRequest', rememberOpener);
  document.addEventListener('htmx:configRequest', rememberOpener);

  function closeDialog(root) {
    root.replaceChildren();
    var opener = dialogOpener;
    dialogOpener = null;
    if (opener && document.contains(opener) && opener.focus) {
      opener.focus();
    }
  }

  /* Esc: открытый диалог закрывается как «Отмена» (без запроса), слайдер под ним остаётся. */
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
      return;
    }
    var dialogRoot = document.getElementById('dialog-root');
    if (dialogRoot && dialogRoot.querySelector('.dialog-panel')) {
      closeDialog(dialogRoot);
      return;
    }
    var close = document.querySelector('#slider-root [data-slider-close]');
    if (close) {
      close.click();
    }
  });

  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === 'slider-root') {
      var panel = target.querySelector('.slider-panel');
      if (panel) {
        panel.focus();
      }
    }
    if (target && target.id === 'dialog-root') {
      var dialog = target.querySelector('.dialog-panel');
      if (dialog) {
        dialog.focus();
      }
    }
  });

  /* Диалоги подтверждения (T-2231, CONTRACT-002 § 9.8): «Отмена» закрывает диалог без запроса. */
  document.addEventListener('click', function (event) {
    var cancel = event.target.closest ? event.target.closest('button[data-dialog-cancel]') : null;
    if (!cancel) {
      return;
    }
    var root = cancel.closest('#dialog-root');
    if (root) {
      closeDialog(root);
    }
  });

  /* Дерево «Структуры» (доделка T-2230b): после подмены карточки узла отметка текущего узла переезжает на новую ссылку. */
  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (!target || target.id !== 'unit-card') {
      return;
    }
    var links = document.querySelectorAll('[data-unit-tree] a[data-unit-link]');
    var card = target.querySelector('[data-unit-card][data-unit-id]');
    var id = card ? card.getAttribute('data-unit-id') : null;
    Array.prototype.forEach.call(links, function (link) {
      var item = link.closest('[data-unit-id]');
      if (id !== null && item && item.getAttribute('data-unit-id') === id) {
        link.setAttribute('aria-current', 'true');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  });
})();
