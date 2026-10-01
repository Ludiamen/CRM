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

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
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
  });
})();
