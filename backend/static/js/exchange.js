/* Обмен кода ссылки на сессию (FR-012, FR-032, секреты-в-url).
   Код лежит во фрагменте адреса (#…) и на сервер не уходит. Скрипт читает его, сразу стирает
   из адресной строки (history.replaceState) и отправляет POST-запросом в теле формы. */
(function () {
  var form = document.getElementById('exchange-form');
  if (!form) {
    return;
  }
  var hint = document.getElementById('exchange-hint');
  var code = window.location.hash ? window.location.hash.slice(1) : '';
  if (!code) {
    return; /* ссылку открыли без кода: страница объясняет, что делать */
  }
  try {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  } catch (error) {
    /* адрес не удалось очистить: код всё равно уйдёт только телом запроса */
  }
  form.elements.code.value = code;
  if (hint) {
    hint.textContent = 'Проверяем ссылку…';
  }
  form.submit();
})();
