/* Строка поиска в шапке (CONTRACT-005, 11.9, п. 68 раздела 17): стрелки выбирают строку окна выдачи
   (data-selected="true"), Enter открывает выбранную строку или страницу результатов, Esc закрывает окно,
   щелчок вне строки поиска тоже закрывает его. Пауза ввода в 300 мс и порог в 2 знака — в разметке (hx-trigger)
   и на сервере. Без inline-кода (CSP): скрипт подключён файлом из templates/_assets.html. */
(function () {
  var MAX_LENGTH = 200;

  function field(target) {
    return target && target.closest ? target.closest('[data-search-bar] input[name="q"]') : null;
  }

  function popup() {
    return document.querySelector('[data-search-bar] [data-search-popup]');
  }

  /* Окно заменяется целиком после каждого ответа, поэтому ищется заново при каждом нажатии. */
  function isOpen(root) {
    return !!root && !root.hasAttribute('hidden');
  }

  function rowsOf(root) {
    return root ? Array.prototype.slice.call(root.querySelectorAll('li[data-search-row]')) : [];
  }

  function selectedIndex(rows) {
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i].getAttribute('data-selected') === 'true') {
        return i;
      }
    }
    return -1;
  }

  function select(rows, index) {
    rows.forEach(function (row, i) {
      if (i === index) {
        row.setAttribute('data-selected', 'true');
        if (row.scrollIntoView) {
          row.scrollIntoView({ block: 'nearest' });
        }
      } else {
        row.removeAttribute('data-selected');
      }
    });
  }

  function closePopup() {
    var root = popup();
    if (root) {
      rowsOf(root).forEach(function (row) {
        row.removeAttribute('data-selected');
      });
      root.setAttribute('hidden', '');
    }
  }

  function openSelected(rows, index) {
    var link = rows[index].querySelector('a[href]');
    if (link) {
      link.click();
    }
  }

  /* Фаза перехвата на document: срабатывает раньше обработчика Esc из htmx-glue.js (фаза всплытия на document),
     поэтому слайдер открытой карточки заявки не закрывается. */
  document.addEventListener('keydown', function (event) {
    var input = field(event.target);
    if (!input) {
      return;
    }
    var root = popup();
    var rows = isOpen(root) ? rowsOf(root) : [];
    var index = selectedIndex(rows);
    if (event.key === 'Escape') {
      /* Окно закрыто — Esc идёт дальше (закрывает слайдер карточки), как в datefield.js. */
      if (!isOpen(root)) {
        return;
      }
      event.stopPropagation();
      event.preventDefault();
      closePopup();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (rows.length) {
        select(rows, Math.min(index + 1, rows.length - 1));
      }
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (rows.length && index >= 0) {
        select(rows, index - 1);
      }
    } else if (event.key === 'Enter') {
      if (event.isComposing) {
        return;
      }
      event.preventDefault();
      if (index >= 0) {
        openSelected(rows, index);
        return;
      }
      var query = input.value.trim();
      if (query) {
        window.location.assign('/search/?q=' + encodeURIComponent(query));
      }
    }
  }, true);

  /* Длина запроса: браузер держит maxlength сам, здесь — страховка для вставки и автозаполнения. */
  document.addEventListener('input', function (event) {
    var input = field(event.target);
    if (input && input.value.length > MAX_LENGTH) {
      input.value = input.value.slice(0, MAX_LENGTH);
    }
  });

  /* Щелчок вне строки поиска закрывает окно; щелчок по строке или ссылке внутри — нет. */
  document.addEventListener('click', function (event) {
    if (event.target.closest && event.target.closest('[data-search-bar]')) {
      return;
    }
    if (isOpen(popup())) {
      closePopup();
    }
  });
})();
