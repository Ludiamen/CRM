/* Редактор статьи базы знаний (T-5214): панель разметки, вкладки «Текст» и «Предпросмотр», подсказка тегов,
   вставка ссылки и картинки из списка вложений, «Вложить», «Вернуться к правке» в предупреждении ПДн.
   Без inline-кода (CSP): скрипт подключён файлом, обработчики — делегированием на document. */
(function () {
  var TAG_DELAY = 250;
  var tagTimer = null;

  function area(scope) {
    var form = scope.closest ? scope.closest('form[data-form="kb-article"]') : null;
    return form ? form.querySelector('textarea[name="text"]') : document.querySelector('textarea[name="text"]');
  }

  /* Вставка в позицию курсора; выделенный текст оборачивается в `before`…`after`. */
  function wrap(field, before, after, placeholder) {
    var start = field.selectionStart;
    var end = field.selectionEnd;
    var chosen = field.value.slice(start, end) || placeholder || '';
    field.value = field.value.slice(0, start) + before + chosen + after + field.value.slice(end);
    var caret = start + before.length;
    field.focus();
    field.setSelectionRange(caret, caret + chosen.length);
    field.dispatchEvent(new Event('input', {bubbles: true}));
  }

  /* Начало строки: префикс ставится в начало текущей строки (для заголовка и списков). */
  function prefixLine(field, prefix) {
    var start = field.selectionStart;
    var lineStart = field.value.lastIndexOf('\n', start - 1) + 1;
    field.value = field.value.slice(0, lineStart) + prefix + field.value.slice(lineStart);
    var caret = start + prefix.length;
    field.focus();
    field.setSelectionRange(caret, caret);
    field.dispatchEvent(new Event('input', {bubbles: true}));
  }

  function insertText(field, text) {
    var start = field.selectionStart;
    var end = field.selectionEnd;
    field.value = field.value.slice(0, start) + text + field.value.slice(end);
    var caret = start + text.length;
    field.focus();
    field.setSelectionRange(caret, caret);
    field.dispatchEvent(new Event('input', {bubbles: true}));
  }

  var TABLE = '| a | b |\n| --- | --- |\n|   |   |\n';

  function applyMarkdown(kind, field) {
    if (kind === 'bold') { wrap(field, '**', '**', 'текст'); }
    else if (kind === 'italic') { wrap(field, '*', '*', 'текст'); }
    else if (kind === 'code') { wrap(field, '`', '`', 'код'); }
    else if (kind === 'link') { wrap(field, '[', '](https://)', 'текст'); }
    else if (kind === 'heading') { prefixLine(field, '# '); }
    else if (kind === 'list') { prefixLine(field, '- '); }
    else if (kind === 'olist') { prefixLine(field, '1. '); }
    else if (kind === 'table') { insertText(field, TABLE); }
  }

  /* Имя файла в подписи ссылки: `\`, `[` и `]` экранируются, иначе разметка `[имя](att:N)` ломается. */
  function escapeLabel(name) {
    return name.replace(/[\\\[\]]/g, function (char) { return '\\' + char; });
  }

  function attachmentMarkup(button, image) {
    var row = button.closest('li[data-file-id]');
    if (!row) {
      return button.getAttribute('data-insert') || '';
    }
    var nameNode = row.querySelector('[data-field="name"]');
    var name = nameNode ? nameNode.textContent.trim() : '';
    return (image ? '!' : '') + '[' + escapeLabel(name) + '](att:' + row.getAttribute('data-file-id') + ')';
  }

  function pickImage(field) {
    var row = document.querySelector('[data-kb-files] li[data-image]:not([data-image=""])[data-file-state="clean"]');
    var button = row ? row.querySelector('[data-action="kb-insert-image"]') : null;
    if (button) {
      insertText(field, attachmentMarkup(button, true));
    } else {
      insertText(field, '![](att:)');
    }
  }

  function showTab(root, name) {
    root.querySelectorAll('[data-kb-panel]').forEach(function (panel) {
      panel.hidden = panel.getAttribute('data-kb-panel') !== name;
    });
    root.querySelectorAll('[data-kb-tab]').forEach(function (tab) {
      var active = tab.getAttribute('data-kb-tab') === name;
      tab.classList.toggle('btn-primary', active);
      tab.classList.toggle('btn-outline-primary', !active);
    });
  }

  /* Подсказка тегов: последний сегмент после запятой уходит в /kb/tags/suggest/?q=. */
  function suggestTags(input) {
    var list = input.parentNode.querySelector('[data-kb-tag-suggest]');
    if (!list) { return; }
    var segment = input.value.split(',').pop().trim();
    if (!segment) { list.replaceChildren(); return; }
    fetch('/kb/tags/suggest/?q=' + encodeURIComponent(segment), {headers: {'HX-Request': 'true'}, credentials: 'same-origin'})
      .then(function (response) { return response.ok ? response.text() : ''; })
      .then(function (html) {
        if (input.value.split(',').pop().trim() !== segment) { return; }
        var holder = document.createElement('div');
        holder.innerHTML = html;
        var source = holder.querySelector('[data-kb-tag-suggest]');
        list.replaceChildren.apply(list, source ? Array.prototype.slice.call(source.children) : []);
      })
      .catch(function () { list.replaceChildren(); });
  }

  function chooseTag(item, input) {
    var parts = input.value.split(',');
    parts[parts.length - 1] = ' ' + item.getAttribute('data-tag');
    input.value = parts.join(',').replace(/^\s+/, '') + ', ';
    item.parentNode.replaceChildren();
    input.focus();
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target.closest) { return; }
    var md = target.closest('button[data-md]');
    if (md && !md.disabled) {
      var field = area(md);
      if (!field) { return; }
      if (md.getAttribute('data-md') === 'image') { pickImage(field); } else { applyMarkdown(md.getAttribute('data-md'), field); }
      return;
    }
    var tab = target.closest('button[data-kb-tab]');
    if (tab) {
      showTab(tab.closest('[data-kb-editor]'), tab.getAttribute('data-kb-tab'));
      return;
    }
    var attach = target.closest('button[data-action="kb-attach"]');
    if (attach && !attach.disabled) {
      var file = document.querySelector('form[data-form="kb-attach"] input[name="file"]');
      if (file) { file.click(); }
      return;
    }
    var insert = target.closest('button[data-action="kb-insert-link"], button[data-action="kb-insert-image"]');
    if (insert) {
      var text = area(document.body);
      if (text) { insertText(text, attachmentMarkup(insert, insert.getAttribute('data-action') === 'kb-insert-image')); }
      return;
    }
    var back = target.closest('button[data-action="kb-pdn-back"]');
    if (back) {
      var block = back.closest('[data-kb-pdn]');
      var hidden = block && block.parentNode.querySelector('input[name="action"][type="hidden"]');
      if (hidden) { hidden.remove(); }
      if (block) { block.remove(); }
      return;
    }
    var tag = target.closest('[data-kb-tag-suggest] li[data-tag]');
    if (tag) {
      var tags = document.querySelector('input[name="tags"]');
      if (tags) { chooseTag(tag, tags); }
    }
  });

  /* Вкладка «Предпросмотр» открывается сразу, ответ приходит в панель; возврат на «Текст» ввод не трогает. */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var elt = event.detail && event.detail.elt;
    if (elt && elt.getAttribute && elt.getAttribute('data-kb-tab') === 'preview') {
      showTab(elt.closest('[data-kb-editor]'), 'preview');
    }
  });

  document.addEventListener('input', function (event) {
    var target = event.target;
    if (target && target.matches && target.matches('input[name="tags"]')) {
      window.clearTimeout(tagTimer);
      tagTimer = window.setTimeout(function () { suggestTags(target); }, TAG_DELAY);
    }
  });
})();
