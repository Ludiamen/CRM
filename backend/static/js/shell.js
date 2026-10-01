/* Состояние оболочки на Alpine (CSP-сборка): режим меню «только значки» (UX-01, FR-050).
   В выражениях страниц — только имена свойств и методов; вся логика здесь. */
document.addEventListener('alpine:init', function () {
  var KEY = 'menu-icons-only';
  var CLASS_NAME = 'menu-icons-only';

  function read() {
    try {
      return window.localStorage.getItem(KEY) === '1';
    } catch (error) {
      return document.documentElement.classList.contains(CLASS_NAME);
    }
  }

  function write(value) {
    try {
      window.localStorage.setItem(KEY, value ? '1' : '0');
    } catch (error) {
      /* без хранилища режим действует до перезагрузки страницы */
    }
  }

  Alpine.data('shell', function () {
    return {
      iconsOnly: read(),
      init: function () {
        document.documentElement.classList.toggle(CLASS_NAME, this.iconsOnly);
      },
      toggleIcons: function () {
        this.iconsOnly = !this.iconsOnly;
        document.documentElement.classList.toggle(CLASS_NAME, this.iconsOnly);
        write(this.iconsOnly);
      },
      get toggleLabel() {
        return this.iconsOnly ? 'Развернуть меню' : 'Свернуть меню';
      }
    };
  });
});
