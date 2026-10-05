// Поведение поля даты (PLAN-002, «Поле выбора даты», FR-148); внешний файл из-за CSP.
// Обработчики — на document (делегирование), чтобы работала и сетка, пришедшая по HTMX.
(function () {
  var GRID_URL = '/ui/date-picker/?month=';
  var MIN_YEAR = 1900;
  var MAX_YEAR = 2100;
  var CONTROLS = ['data-datefield-prev', 'data-datefield-next', 'data-datefield-month', 'data-datefield-year'];
  var pendingControl = null; // зацепка элемента управления сетки, который надо вернуть в фокус после подмены
  var pendingFocus = null; // ГГГГ-ММ-ДД: на какой день встать после загрузки соседнего месяца

  function pad(number, length) {
    var text = String(number);
    while (text.length < length) {
      text = '0' + text;
    }
    return text;
  }

  function iso(year, month, day) {
    return pad(year, 4) + '-' + pad(month, 2) + '-' + pad(day, 2);
  }

  function daysIn(year, month) {
    return new Date(Date.UTC(year, month, 0)).getUTCDate();
  }

  /* Дата из текста поля: ДД.ММ.ГГГГ или ГГГГ-ММ-ДД; неверная — null. */
  function parseText(text) {
    var value = (text || '').trim();
    var found = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value);
    var parts = null;
    if (found) {
      parts = [Number(found[3]), Number(found[2]), Number(found[1])];
    } else {
      found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
      if (found) {
        parts = [Number(found[1]), Number(found[2]), Number(found[3])];
      }
    }
    if (!parts || parts[1] < 1 || parts[1] > 12 || parts[2] < 1 || parts[2] > daysIn(parts[0], parts[1])) {
      return null;
    }
    return { year: parts[0], month: parts[1], day: parts[2] };
  }

  function parseIso(text) {
    return parseText(text);
  }

  function fieldParts(wrapper) {
    return {
      input: wrapper.querySelector('[data-datefield-input]'),
      opener: wrapper.querySelector('[data-datefield-open]'),
      picker: wrapper.querySelector('[data-datefield-picker]')
    };
  }

  function shownGrid(wrapper) {
    return wrapper.querySelector('[data-datefield-grid]');
  }

  /* Выбранный день — по значению поля, только если он в показанном месяце. */
  function markSelected(wrapper) {
    var grid = shownGrid(wrapper);
    var parts = fieldParts(wrapper);
    if (!grid || !parts.input) {
      return;
    }
    var chosen = parseText(parts.input.value);
    var chosenIso = chosen ? iso(chosen.year, chosen.month, chosen.day) : '';
    grid.querySelectorAll('button[data-date]').forEach(function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-date') === chosenIso ? 'true' : 'false');
    });
  }

  function focusDay(grid, dateIso) {
    var button = grid.querySelector('button[data-date="' + dateIso + '"]');
    if (button) {
      button.focus();
    }
    return !!button;
  }

  /* Фокус при открытии: выбранный день, иначе сегодняшний (если он в месяце), иначе 1-е число. */
  function focusInitial(grid) {
    var pressed = grid.querySelector('button[data-date][aria-pressed="true"]');
    if (pressed) {
      pressed.focus();
      return;
    }
    var today = grid.getAttribute('data-today');
    if (today && focusDay(grid, today)) {
      return;
    }
    focusDay(grid, grid.getAttribute('data-month') + '-01');
  }

  function openPicker(wrapper) {
    var parts = fieldParts(wrapper);
    parts.picker.hidden = false;
    parts.opener.setAttribute('aria-expanded', 'true');
  }

  function closePicker(wrapper, focusTarget) {
    var parts = fieldParts(wrapper);
    parts.picker.hidden = true;
    parts.picker.replaceChildren();
    parts.opener.setAttribute('aria-expanded', 'false');
    pendingFocus = null;
    pendingControl = null;
    if (focusTarget === 'opener') {
      parts.opener.focus();
    } else if (focusTarget === 'input') {
      parts.input.focus();
    }
  }

  function choose(wrapper, dateIso) {
    var date = parseIso(dateIso);
    var parts = fieldParts(wrapper);
    if (!date || !parts.input) {
      return;
    }
    parts.input.value = pad(date.day, 2) + '.' + pad(date.month, 2) + '.' + pad(date.year, 4);
    parts.input.dispatchEvent(new Event('input', { bubbles: true }));
    parts.input.dispatchEvent(new Event('change', { bubbles: true }));
    closePicker(wrapper, 'input');
  }

  function loadMonth(wrapper, year, month) {
    var parts = fieldParts(wrapper);
    window.htmx.ajax('GET', GRID_URL + pad(year, 4) + '-' + pad(month, 2), { target: parts.picker, swap: 'innerHTML' });
  }

  /* Дата на `shift` дней от `date`; null, если выходит за 1900…2100. */
  function shiftDays(date, shift) {
    var moved = new Date(Date.UTC(date.year, date.month - 1, date.day + shift));
    return fromUtc(moved);
  }

  function fromUtc(moved) {
    var year = moved.getUTCFullYear();
    if (year < MIN_YEAR || year > MAX_YEAR) {
      return null;
    }
    return { year: year, month: moved.getUTCMonth() + 1, day: moved.getUTCDate() };
  }

  /* PageUp и PageDown: тот же день соседнего месяца или его последний день. */
  function shiftMonths(date, shift) {
    var index = date.year * 12 + date.month - 1 + shift;
    var year = Math.floor(index / 12);
    var month = index % 12 + 1;
    if (year < MIN_YEAR || year > MAX_YEAR) {
      return null;
    }
    return { year: year, month: month, day: Math.min(date.day, daysIn(year, month)) };
  }

  function weekday(date) {
    return (new Date(Date.UTC(date.year, date.month - 1, date.day)).getUTCDay() + 6) % 7; // 0 — понедельник
  }

  function target(date, key) {
    switch (key) {
      case 'ArrowLeft': return shiftDays(date, -1);
      case 'ArrowRight': return shiftDays(date, 1);
      case 'ArrowUp': return shiftDays(date, -7);
      case 'ArrowDown': return shiftDays(date, 7);
      case 'PageUp': return shiftMonths(date, -1);
      case 'PageDown': return shiftMonths(date, 1);
      case 'Home': return shiftDays(date, -weekday(date));
      case 'End': return shiftDays(date, 6 - weekday(date));
      default: return null;
    }
  }

  function moveFocus(wrapper, grid, next) {
    var nextIso = iso(next.year, next.month, next.day);
    if (!focusDay(grid, nextIso)) {
      pendingFocus = nextIso;
      loadMonth(wrapper, next.year, next.month);
    }
  }

  document.addEventListener('keydown', function (event) {
    var key = event.key;
    var wrapper = event.target.closest ? event.target.closest('[data-datefield]') : null;
    if (!wrapper) {
      return;
    }
    var parts = fieldParts(wrapper);
    if (key === 'Escape' && !parts.picker.hidden) {
      event.preventDefault();
      event.stopPropagation(); // Esc закрывает только сетку, а не слайдер или диалог под ней
      closePicker(wrapper, 'opener');
      return;
    }
    var button = event.target.closest('button[data-date]');
    var grid = shownGrid(wrapper);
    if (!button || !grid) {
      return;
    }
    if (key === 'Enter') {
      event.preventDefault();
      choose(wrapper, button.getAttribute('data-date'));
      return;
    }
    var date = parseIso(button.getAttribute('data-date'));
    var next = date ? target(date, key) : null;
    if (key === 'ArrowLeft' || key === 'ArrowRight' || key === 'ArrowUp' || key === 'ArrowDown' ||
        key === 'PageUp' || key === 'PageDown' || key === 'Home' || key === 'End') {
      event.preventDefault();
      if (next) {
        moveFocus(wrapper, grid, next);
      }
    }
  }, true);

  document.addEventListener('click', function (event) {
    var source = event.target.closest ? event.target : null;
    if (!source) {
      return;
    }
    var button = source.closest('button[data-date]');
    if (button) {
      var wrapper = button.closest('[data-datefield]');
      if (wrapper) {
        choose(wrapper, button.getAttribute('data-date'));
      }
      return;
    }
    // щелчок вне поля закрывает открытые сетки
    document.querySelectorAll('[data-datefield]').forEach(function (other) {
      var parts = fieldParts(other);
      if (parts.picker && !parts.picker.hidden && !other.contains(source)) {
        closePicker(other, null);
      }
    });
  });

  /* Запомнить, какой элемент управления сетки вызвал подмену, чтобы вернуть на него фокус. */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var source = event.detail && event.detail.elt;
    pendingControl = null;
    if (!source || !source.hasAttribute) {
      return;
    }
    for (var i = 0; i < CONTROLS.length; i++) {
      if (source.hasAttribute(CONTROLS[i])) {
        pendingControl = CONTROLS[i];
        return;
      }
    }
  });

  /* Повторное нажатие «Выбрать дату» закрывает сетку, не делая запроса. */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var source = event.detail && event.detail.elt;
    if (!source || !source.hasAttribute || !source.hasAttribute('data-datefield-open')) {
      return;
    }
    var wrapper = source.closest('[data-datefield]');
    if (wrapper && !fieldParts(wrapper).picker.hidden) {
      event.preventDefault();
      closePicker(wrapper, 'opener');
    }
  });

  /* Сетка пришла: показать, отметить выбранный день, поставить фокус. */
  document.addEventListener('htmx:afterSwap', function (event) {
    var swapped = (event.detail && event.detail.target) || event.target;
    if (!swapped || !swapped.hasAttribute || !swapped.hasAttribute('data-datefield-picker')) {
      return;
    }
    var wrapper = swapped.closest('[data-datefield]');
    var grid = wrapper && shownGrid(wrapper);
    if (!grid) {
      return;
    }
    var wasHidden = swapped.hidden;
    var control = pendingControl;
    pendingControl = null;
    openPicker(wrapper);
    markSelected(wrapper);
    if (control) {
      var same = grid.querySelector('[' + control + ']:not([disabled])');
      if (same) {
        same.focus();
      } else {
        focusInitial(grid);
      }
    } else if (pendingFocus) {
      var wanted = pendingFocus;
      pendingFocus = null;
      focusDay(grid, wanted);
    } else if (wasHidden) {
      focusInitial(grid);
    }
  });

  /* Ввод с клавиатуры: маска ДД.ММ.ГГГГ; выбранный день в открытой сетке обновляется по значению поля. */
  document.addEventListener('input', function (event) {
    var field = event.target;
    if (!field.hasAttribute || !field.hasAttribute('data-datefield-input')) {
      return;
    }
    var type = event.inputType || '';
    var value = field.value;
    if (type.indexOf('insert') === 0 && !/^\d{4}-/.test(value) && !/[^\d.]/.test(value)) {
      var digits = value.replace(/\D/g, '').slice(0, 8);
      var masked = digits.slice(0, 2);
      if (digits.length > 2) {
        masked += '.' + digits.slice(2, 4);
      }
      if (digits.length > 4) {
        masked += '.' + digits.slice(4);
      }
      if (masked !== value) {
        field.value = masked;
      }
    }
    var wrapper = field.closest('[data-datefield]');
    if (wrapper) {
      markSelected(wrapper);
    }
  });
})();
