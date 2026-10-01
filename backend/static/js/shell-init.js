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
