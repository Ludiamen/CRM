/* Режим меню «только значки» применяется до первой отрисовки, чтобы страница не мигала (UX-01, FR-050).
   Подключается обычным (не отложенным) скриптом в <head>; скрипты в самой странице под CSP запрещены. */
(function () {
  try {
    if (window.localStorage.getItem('menu-icons-only') === '1') {
      document.documentElement.classList.add('menu-icons-only');
    }
  } catch (error) {
    /* localStorage может быть закрыт (частное окно): меню остаётся развёрнутым */
  }
})();

/* Кадры колокольчика несут OOB-строки списка чатов и строку «Прочитали N из M»; на страницах, где этих узлов
   нет, htmx пишет в консоль `htmx:oobErrorNoTarget`. Цели — данные, их отсутствие нормально: глушим только
   этот случай, прочие ошибки OOB остаются видимыми (критерий T-8301 — чистая консоль). */
(function () {
  var native = console.error;
  console.error = function () {
    var text = Array.prototype.join.call(arguments, " ");
    if (text.indexOf("htmx:oobErrorNoTarget") >= 0 && /#chat-\d+-(unread|preview)|#messenger-read/.test(text)) return;
    return native.apply(console, arguments);
  };
})();
