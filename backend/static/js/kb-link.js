/* Связь статей с заявками на карточке заявки (T-5212): подсказка статей и вставка ссылки в комментарий.
   Поле `input[name=pick]` шлёт запрос `/kb/pick/?q=…` (с `ticket` у раздела «Статьи» — строки с кнопкой «Привязать
   статью»); у инструмента «Ссылка на статью» выбор строки (щелчок или Enter) вставляет «Заголовок: адрес» в поле
   внутреннего комментария. Без inline-кода (CSP). */
(function () {
  var DELAY = 300;
  var MIN_LENGTH = 2;
  var timers = new WeakMap();

  function resultsOf(input) {
    var scope = input.closest('[data-kb-link-panel], form[data-form="kb-link"]');
    return scope ? scope.querySelector('[data-kb-pick-results]') : null;
  }

  function ticketOf(input) {
    var form = input.closest('form[data-form="kb-link"]');
    return form ? form.getAttribute('data-ticket') : '';
  }


  function search(input) {
    var list = resultsOf(input);
    if (!list) {
      return;
    }
    var text = input.value.trim();
    if (text.length < MIN_LENGTH) {
      list.replaceChildren();
      return;
    }
    var url = '/kb/pick/?q=' + encodeURIComponent(text);
    var ticket = ticketOf(input);
    if (ticket) {
      url += '&ticket=' + encodeURIComponent(ticket);
    }
    fetch(url, {headers: {'HX-Request': 'true'}, credentials: 'same-origin'}).then(function (response) {
      return response.ok ? response.text() : '';
    }).then(function (html) {
      if (input.value.trim() !== text) {
        return; /* пока шёл ответ, запрос изменился */
      }
      var current = resultsOf(input);
      if (!current) {
        return;
      }
      var holder = document.createElement('div');
      holder.innerHTML = html;
      var fresh = holder.querySelector('[data-kb-pick-results]');
      if (!fresh) {
        current.replaceChildren();
        return;
      }
      current.replaceChildren.apply(current, Array.prototype.slice.call(fresh.childNodes));
      if (window.htmx) {
        window.htmx.process(current);
      }
    }).catch(function () {
      list.replaceChildren();
    });
  }

  document.addEventListener('input', function (event) {
    var input = event.target;
    if (!input.matches || !input.matches('input[name="pick"]')) {
      return;
    }
    clearTimeout(timers.get(input));
    timers.set(input, setTimeout(function () { search(input); }, DELAY));
  });

  /* Enter в поле подсказки не отправляет ни привязку, ни внутренний комментарий (поле стоит в их формах). */
  document.addEventListener('keydown', function (event) {
    var target = event.target;
    if (!target || !target.matches) {
      return;
    }
    if (target.matches('input[name="pick"]') && event.key === 'Enter') {
      event.preventDefault();
      clearTimeout(timers.get(target));
      search(target);
      return;
    }
    if (target.matches('[data-kb-link-panel] li[data-article-id]') && event.key === 'Enter') {
      event.preventDefault();
      insert(target);
    }
  });

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (form.matches && form.matches('form[data-form="kb-link"]')) {
      event.preventDefault(); /* привязку делают кнопки в строках подсказки */
    }
  });

  function insert(row) {
    var form = row.closest('form');
    var field = form ? form.querySelector('textarea[name="text"]') : null;
    if (!field) {
      return;
    }
    var text = row.getAttribute('data-title') + ': ' + row.getAttribute('data-url');
    field.value = field.value ? field.value + '\n' + text : text;
    field.dispatchEvent(new Event('input', {bubbles: true}));
    field.focus();
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || !target.closest) {
      return;
    }
    var tool = target.closest('button[data-action="kb-link-tool"]');
    if (tool) {
      var panel = tool.parentNode.querySelector('[data-kb-link-panel]');
      if (panel) {
        panel.hidden = !panel.hidden;
        var input = panel.querySelector('input[name="pick"]');
        if (!panel.hidden && input) {
          input.focus();
        }
      }
      return;
    }
    var row = target.closest('[data-kb-link-panel] li[data-article-id]');
    if (row) {
      insert(row);
    }
  });
})();
