/* T-7215: форма публикации; T-7216: перенос прочитанного важного в ленту.
   CSP Alpine.data и настоящие HTMX parameters:
   https://alpinejs.dev/advanced/csp, https://htmx.org/events/#htmx:configRequest */
(function () {
  if (window.feedFormLoaded) { return; }
  window.feedFormLoaded = true;
  var feedSocket = null;

  /* T-7301 (oobErrorNoTarget): захват внутреннего API htmx через defineExtension — тот же приём, которым
     пользуется htmx-ext-ws (`init(api)` вызывается синхронно при определении). API нужен, чтобы в
     `htmx:wsBeforeMessage` отфильтровать OOB-фрагменты без цели ДО передачи htmx и применить годные его же
     `oobSwap`, сохранив штатные события (`oobBeforeSwap`, `oobAfterSwap`, `wsAfterMessage`) и settle. */
  var htmxInternal = null;
  if (window.htmx && typeof window.htmx.defineExtension === 'function') {
    window.htmx.defineExtension('feed-oob-guard', {
      init: function (api) { htmxInternal = api; }
    });
  }

  function feedLive(node) {
    if (!node) { return null; }
    if (node.id === 'feed-live') { return node; }
    return node.closest ? node.closest('#feed-live') : null;
  }

  function postIds(root) {
    var ids = [];
    if (!root) { return ids; }
    var nodes = [];
    if (root.matches && root.matches('article[data-post-id]')) { nodes.push(root); }
    if (root.querySelectorAll) { nodes = nodes.concat(Array.from(root.querySelectorAll('article[data-post-id]'))); }
    nodes.forEach(function (article) {
      var value = article.dataset.postId;
      if (/^[1-9]\d*$/.test(value) && ids.indexOf(Number(value)) < 0) { ids.push(Number(value)); }
    });
    return ids;
  }

  function sendFeedMessage(message) {
    if (feedSocket && typeof feedSocket.send === 'function') {
      feedSocket.send(JSON.stringify(message));
    }
  }

  document.addEventListener('htmx:wsOpen', function (event) {
    var live = feedLive(event.target);
    var wrapper = event.detail && event.detail.socketWrapper;
    if (!live || !wrapper || typeof wrapper.send !== 'function') { return; }
    feedSocket = wrapper;
    sendFeedMessage({sync: {ids: postIds(document), since: live.dataset.opened || new Date().toISOString()}});
  });

  document.addEventListener('htmx:wsAfterMessage', function (event) {
    var live = feedLive(event.target);
    var message = event.detail && event.detail.message;
    if (!live || typeof message !== 'string') { return; }
    var parsed = new DOMParser().parseFromString(message, 'text/html');
    if (parsed.getElementById('feed-synced')) { live.dataset.ws = 'open'; }
  });

  document.addEventListener('htmx:wsClose', function (event) {
    var live = feedLive(event.target);
    if (live) { live.dataset.ws = 'closed'; }
  });

  /* T-7301 (oobErrorNoTarget): рассылка кадров портала идёт всем сокетам, включая инициатора, поэтому кадр
     может не иметь цели на этой странице — удаление записи/комментария (у инициатора узел уже снят
     HTTP-ответом; старый комментарий — вне показанных последних трёх) и notify-кадры вроде
     `#notify-binding-telegram` (блок живёт только в «Моих уведомлениях»). htmx 2.0.11 на OOB-фрагмент без
     цели отвечает console.error (`htmx:oobErrorNoTarget`). Проверяем сообщение на отменяемом
     `htmx:wsBeforeMessage` (все сокеты страницы, в том числе колокольчик):
     - у всех верхних фрагментов цель есть — сообщение не трогаем, htmx обрабатывает его штатно;
     - есть фрагмент без цели — отменяем сообщение и применяем годные фрагменты сами тем же внутренним
       `oobSwap`, который вызвал бы htmx-ext-ws: правила подмены, `htmx:oobBeforeSwap` (отмена дубля —
       решение 62), `htmx:oobAfterSwap` и settle не отличаются; бесцельные фрагменты отбрасываются — то, что
       htmx сделал бы с ними в любом случае, но без ошибки в консоли. Завершаем сообщение штатным
       `htmx:wsAfterMessage` (состояния `data-ws` ленты и колокольчика не ломаются).
     HTTP-ответы (сброс формы публикации, вставка записи) не затрагиваются: событие бывает только у кадров
     WebSocket. Селектор цели вычисляется по правилам htmx oobSwap; формы, которые `querySelectorAll` не
     понимает (специальные селекторы htmx), считаем годными — фильтр ничего не отбрасывает наугад. */
  function oobSelectorOf(value, child) {
    if (typeof value !== 'string' || !value) { return null; }
    var colon = value.indexOf(':');
    if (colon > 0) { return value.substring(colon + 1); }
    /* Как в htmx oobSwap: цель — `#` + CSS.escape(id); без id это заведомо отсутствующая цель. */
    var id = child.getAttribute ? child.getAttribute('id') : null;
    return '#' + (window.CSS && typeof window.CSS.escape === 'function' ? window.CSS.escape(id) : String(id));
  }

  function oobTargetMissing(value, child) {
    var selector = oobSelectorOf(value, child);
    if (selector === null) { return true; }
    try {
      return document.querySelectorAll(selector).length === 0;
    } catch (error) {
      return false; /* селектор не проверить — не фильтруем, пусть решает htmx */
    }
  }

  document.addEventListener('htmx:wsBeforeMessage', function (event) {
    var detail = event.detail || {};
    var message = detail.message;
    if (!htmxInternal || typeof message !== 'string' || !message) { return; }
    var socket = event.target;
    var fragment;
    try {
      fragment = htmxInternal.makeFragment(message);
    } catch (error) { return; /* сообщение не разбирается — оставим штатному пути */ }
    var children = Array.prototype.slice.call(fragment.children || []);
    if (!children.length) { return; }
    var specs = children.map(function (child) {
      var value = htmxInternal.getAttributeValue(child, 'hx-swap-oob') || 'true';
      return {child: child, value: value, missing: oobTargetMissing(value, child)};
    });
    if (!specs.some(function (spec) { return spec.missing; })) { return; }
    event.preventDefault(); /* htmx сообщение не получает: фрагменты без цели отфильтрованы */
    var settle = htmxInternal.makeSettleInfo(socket);
    specs.forEach(function (spec) {
      if (!spec.missing) { htmxInternal.oobSwap(spec.value, spec.child, settle); }
    });
    htmxInternal.settleImmediately(settle.tasks);
    htmxInternal.triggerEvent(socket, 'htmx:wsAfterMessage',
      {message: message, socketWrapper: detail.socketWrapper});
  });

  /* T-7301 (oobErrorNoTarget, HTTP-путь): та же гонка с другой стороны — кадр WS успевает снять узел
     ДО того, как страницу обработает HTTP-ответ действия (удаление записи/комментария: ответ
     `<div id="…" hx-swap-oob="delete">` приходит на страницу, где цели уже нет), и htmx логирует
     console.error уже на OOB из HTTP-ответа — WS-guard тут не помогает. Документный слушатель
     `htmx:beforeSwap` тоже не годится: к моменту ответа цель (вся статья) отцеплена от DOM, и htmx
     dispatch'ит событие на отцепленном узле — до document оно не доходит. Поэтому фильтр висит на
     `htmx.logger` — htmx синхронно зовёт его для каждого события ДО dispatch (публичный API; слот
     `logAll`/`logNone`) и ПЕРЕЧИТЫВАЕТ `detail.serverResponse` после `htmx:beforeSwap`: подменённый
     ответ уходит в swap уже без бесцельных OOB. Правило цели то же, что у WS-guard; OOB с целью на
     месте (сброс `#feed-form`, liker-list, счётчики, плашка) и основной контент не трогаются — ответ
     переписывается, только когда в нём нашёлся фрагмент без цели. Прежний logger сохраняется. */
  function filterOrphanOob(detail) {
    var html = detail && detail.serverResponse;
    if (typeof html !== 'string' || html.indexOf('hx-swap-oob') < 0) { return; }
    var parsed = new DOMParser().parseFromString(html, 'text/html');
    var nodes = Array.prototype.slice.call(parsed.querySelectorAll('[hx-swap-oob], [data-hx-swap-oob]'));
    var orphans = nodes.filter(function (node) {
      var value = node.getAttribute('hx-swap-oob') || node.getAttribute('data-hx-swap-oob') || 'true';
      return oobTargetMissing(value, node);
    });
    if (!orphans.length) { return; }
    orphans.forEach(function (node) { node.parentNode.removeChild(node); });
    detail.serverResponse = parsed.body.innerHTML;
  }

  if (window.htmx) {
    var previousHtmxLogger = window.htmx.logger || null;
    window.htmx.logger = function (elt, eventName, detail) {
      try {
        if (eventName === 'htmx:beforeSwap') { filterOrphanOob(detail); }
      } catch (error) { /* сбой фильтра не должен ломать обработку ответа */ }
      if (previousHtmxLogger) { previousHtmxLogger(elt, eventName, detail); }
    };
  }

  document.addEventListener('htmx:afterSwap', function (event) {
    var live = document.getElementById('feed-live');
    if (!live || !feedSocket) { return; }
    var detail = event.detail || {};
    var root = detail.target || detail.elt || event.target;
    var source = detail.requestConfig && detail.requestConfig.elt;
    var fromBanner = source && source.matches && source.matches('[data-feed-new-load]');
    var ids = postIds(fromBanner ? document : root);
    var message = {add: ids};
    if (fromBanner) {
      var banner = document.getElementById('feed-new');
      if (banner && banner.dataset.since) { message.since = banner.dataset.since; }
    }
    if (ids.length || message.since) { sendFeedMessage(message); }
  });

  document.addEventListener('htmx:oobBeforeSwap', function (event) {
    var detail = event.detail || {};
    var fragment = detail.fragment;
    var target = detail.target;
    if (!fragment || !target || !fragment.querySelectorAll) { return; }
    var root = fragment.firstElementChild;
    var replacesForm = target.isConnected && target.id === 'feed-form' && target.matches('form[data-feed-form]') &&
      fragment.children.length === 1 && root && root.matches('form#feed-form[data-feed-form]');
    var outsideIds;
    if (replacesForm) {
      outsideIds = new Set();
      document.querySelectorAll('[id]').forEach(function (existing) {
        if (existing !== target && !target.contains(existing)) { outsideIds.add(existing.id); }
      });
    }
    var incoming = Array.from(fragment.querySelectorAll('[id]'));
    if (fragment.firstElementChild && fragment.firstElementChild.id) { incoming.push(fragment.firstElementChild); }
    if (incoming.some(function (node) {
      if (replacesForm) { return outsideIds.has(node.id); }
      var existing = document.getElementById(node.id);
      return existing && existing !== target;
    })) { detail.shouldSwap = false; }
  });

  var forms = new WeakMap();
  var pickers = new WeakMap();

  document.addEventListener('click', function (event) {
    var open = event.target.closest('button[data-action="post-delete"]');
    if (open) {
      var dialog = open.closest('[data-post-menu]').querySelector('dialog[data-feed-confirm]');
      if (dialog && !dialog.open) { dialog.showModal(); }
      return;
    }
    var cancel = event.target.closest('dialog[data-feed-confirm] button[value="cancel"]');
    if (cancel) {
      event.preventDefault();
      cancel.closest('dialog').close();
    }
  });

  function publishedAt(card) {
    /* Первое время шапки — публикация; edited_at и срок важности не участвуют. */
    var time = card.querySelector('header time[data-at][datetime]');
    return time ? Date.parse(time.getAttribute('datetime')) : NaN;
  }

  document.addEventListener('htmx:beforeSwap', function (event) {
    var detail = event.detail;
    var source = detail.requestConfig && detail.requestConfig.elt;
    if (!source || !source.matches || !source.matches('button[data-action="read"]') ||
        detail.xhr.status !== 200 || !detail.shouldSwap) { return; }
    /* T-7301 (FR-614): кадр WS `#feed-post-<id>-imp` может прийти раньше ответа XHR и отцепить
       кнопку от DOM — на связанность `source` не опираемся: запись определяется по номеру из
       ответа и по текущему DOM (`#feed-post-<id>`). */
    var parsed = new DOMParser().parseFromString(detail.serverResponse, 'text/html');
    var card = parsed.querySelector('article[data-post-id]');
    if (!card || !card.id || card.querySelector('button[data-action="read"]')) { return; }
    var original = document.getElementById(card.id);
    if (!original || !original.matches('article[data-post-id]') ||
        original.dataset.postId !== card.dataset.postId) { return; }
    /* Карточка уже вне блока важных (карточка записи, перенос выполнен) — штатная замена
       обновляет её на месте; переноса нет и дубль не создаётся. */
    if (!original.closest('#feed-important')) { return; }
    var list = document.querySelector('ol#feed-list[data-feed-list-main]');
    if (!list) { return; }
    /* Ответ сервера уже без кнопки. Подмену внутри блока заменяем переносом;
       остальные HTMX-действия и неуспешные ответы идут штатным путём. */
    detail.shouldSwap = false;
    var cards = Array.from(list.querySelectorAll(':scope > li > article[data-post-id]'));
    window.htmx.remove(original);
    if (cards.some(function (existing) { return existing.dataset.postId === card.dataset.postId; })) { return; }
    var at = publishedAt(card);
    if (!Number.isFinite(at)) { return; }
    /* FR-614: прочитанная запись встаёт в ленту по времени публикации — новее первой наверх,
       внутри показанного — по месту. Полная страница с «Ещё записи»: запись старее показанного
       не вставляем — она придёт с «Ещё записи» (partial, дубль; план 462-463); без кнопки
       (конец ленты или пустая страница) — вставляем, в том числе последней строкой. */
    var more = list.querySelector('[data-feed-more]');
    var oldest = cards.length ? publishedAt(cards[cards.length - 1]) : NaN;
    if (more && Number.isFinite(at) && Number.isFinite(oldest) && at < oldest) { return; }
    var next = cards.find(function (existing) {
      var existingAt = publishedAt(existing);
      return existingAt < at || (existingAt === at && Number(existing.dataset.postId) < Number(card.dataset.postId));
    });
    var row = document.createElement('li');
    row.appendChild(card);
    if (next) { next.parentElement.before(row); }
    else if (cards.length) { cards[cards.length - 1].parentElement.after(row); }
    else { list.appendChild(row); }
    window.htmx.process(row);
    window.htmx.trigger(row, 'htmx:load');
  });

  function state(form) { return form && forms.get(form); }

  function currentForm(node) {
    return node && node.closest ? node.closest('form[data-feed-form]') : null;
  }

  function commentForm(button) {
    var article = button.closest('article[data-post-id]');
    if (article) {
      return article.querySelector('form[data-feed-comment-form]');
    }
    var container = button.closest('div[id$="-comments"]');
    if (container) {
      return container.querySelector('form[data-feed-comment-form]');
    }
    return null;
  }

  function serialized(data) {
    var text = data.area.value;
    data.mentions.slice().sort(function (a, b) { return b.start - a.start; }).forEach(function (item) {
      if (text.slice(item.start, item.end) === '@' + item.label) {
        text = text.slice(0, item.start) + '@[' + item.id + ']' + text.slice(item.end);
      }
    });
    return text;
  }

  function refresh(data) {
    var form = data.form;
    var kind = form.querySelector('[name="kind"]:checked');
    form.querySelectorAll('[data-kind-fields]').forEach(function (fields) {
      fields.classList.toggle('d-none', !kind || fields.dataset.kindFields !== kind.value);
    });
    data.counter.textContent = Array.from(serialized(data)).length + ' / 10000';
    var to = form.querySelector('[data-feed-to]');
    if (!to) { return; }
    to.querySelectorAll('[data-mentioned]').forEach(function (pill) { pill.remove(); });
    var seen = new Set();
    data.mentions.forEach(function (item) {
      if (seen.has(item.id)) { return; }
      seen.add(item.id);
      var pill = document.createElement('span');
      pill.dataset.toPill = 'm' + item.id;
      pill.setAttribute('data-mentioned', '');
      pill.textContent = item.label + ' — упомянут';
      to.appendChild(pill);
    });
  }

  /* T-7301 r2/r3 (форма правки, решение владельца 2026-11-14; ревью r2 — «Дополнение: until»):
     нативный `input[name=until]` с `min`/`max` (К61) в форме правки истёкшей важной записи хранит старое
     значение ниже `min`, и HTML5-валидация блокирует POST даже после переключения срока — сервер при
     term != date `until` не читает. Синхронизируем поле с ВИДОМ и СРОКОМ: оно включено и обязательно
     ТОЛЬКО при `kind == "important"` И `term == "date"`; в остальных случаях — очистить и выключить
     (disabled не валидируется и не отправляется). Учёт kind обязателен (r3): без него required-поле
     остается после переключения вида на «Сообщение»/«Событие», когда блок полей вида скрыт (d-none) —
     невидимое обязательное поле молча блокирует «Опубликовать». Вид берётся из
     `input[name="kind"]:checked` — радиокнопки формы публикации и скрытый checked-radio формы правки
     (`_form_edit.html`) читаются одинаково. Вызывается на загрузке и вставке формы (enhance) и при смене
     kind/term — для обеих форм (`form[data-feed-form]`). Серверные проверки (`term_required`,
     `invalid_until`, `date_passed`) остаются главными. */
  function syncUntilField(form) {
    if (!form) { return; }
    var until = form.querySelector('input[name="until"]');
    if (!until) { return; }
    var kind = form.querySelector('input[name="kind"]:checked');
    var term = form.querySelector('input[name="term"]:checked');
    if (kind && kind.value === 'important' && term && term.value === 'date') {
      until.disabled = false;
      until.required = true;
    } else {
      until.value = '';
      until.disabled = true;
      until.required = false;
    }
  }

  function initialize(form) {
    if (forms.has(form)) { return; }
    var area = form.querySelector('textarea[name="text"]');
    if (!area) { return; }
    var data = {form: form, area: area, mentions: [], previous: '', before: null};
    var names = {};
    try { names = JSON.parse(area.dataset.mentionNames || '{}') || {}; } catch (error) { /* маркеры остаются текстом */ }
    var original = area.value;
    var output = '';
    var last = 0;
    var expression = /@\[([1-9]\d{0,8})\]/g;
    var match;
    while ((match = expression.exec(original))) {
      output += original.slice(last, match.index);
      var label = Object.prototype.hasOwnProperty.call(names, match[1]) ? names[match[1]] : null;
      if (typeof label === 'string' && label) {
        data.mentions.push({id: match[1], label: label, start: output.length, end: output.length + label.length + 1});
        output += '@' + label;
      } else { output += match[0]; }
      last = expression.lastIndex;
    }
    area.value = output + original.slice(last);
    data.previous = area.value;
    data.counter = form.querySelector('[data-feed-count]');
    if (!data.counter) {
      data.counter = document.createElement('output');
      data.counter.setAttribute('data-feed-count', '');
      data.counter.setAttribute('for', area.id);
      data.counter.setAttribute('aria-label', 'Знаков в тексте');
      area.after(data.counter);
    }
    forms.set(form, data);
    refresh(data);
  }

  function changed(data) {
    var old = data.previous;
    var text = data.area.value;
    if (old === text && (!data.before || data.before.start === data.before.end)) { data.before = null; return; }
    var start = 0;
    var end = old.length;
    var newEnd = text.length;
    var before = data.before;
    if (before && old.slice(0, before.start) === text.slice(0, before.start) &&
        old.slice(before.end) === text.slice(text.length - (old.length - before.end))) {
      start = before.start;
      end = before.end;
      newEnd = text.length - (old.length - end);
    } else {
      while (start < old.length && start < text.length && old[start] === text[start]) { start++; }
      while (end > start && newEnd > start && old[end - 1] === text[newEnd - 1]) { end--; newEnd--; }
    }
    var delta = newEnd - end;
    data.mentions = data.mentions.filter(function (item) {
      if (item.end <= start) { return true; }
      if (item.start >= end) { item.start += delta; item.end += delta; return true; }
      return false;
    });
    data.previous = text;
    data.before = null;
    refresh(data);
  }

  function query(field) {
    var scope = field.dataset.feedPicker;
    if (scope !== 'mention') { return {q: field.value.trim(), start: 0, end: 0}; }
    if (field.selectionStart !== field.selectionEnd) { return null; }
    var prefix = field.value.slice(0, field.selectionStart);
    var found = /(?:^|[\s(])@([^@\n\[\]]*)$/.exec(prefix);
    if (!found) { return null; }
    return {q: found[1], start: prefix.lastIndexOf('@'), end: field.selectionStart};
  }

  function suggestions(field) {
    var scope = field.dataset.feedPicker;
    if (!/^(to|mention|author)$/.test(scope)) { return; }
    var owner = field.closest('form');
    if (!owner) { return; }
    var list = owner.querySelector('[data-feed-pick-list="' + scope + '"]');
    if (!list) { return; }
    var previous = pickers.get(field);
    if (previous) { clearTimeout(previous.timer); }
    var entry = {query: query(field), list: list};
    pickers.set(field, entry);
    list.replaceChildren();
    if (!entry.query || Array.from(entry.query.q).length < 2) { return; }
    var text = field.value;
    var caret = field.selectionStart;
    entry.timer = setTimeout(function () {
      fetch('/feed/pick/?' + new URLSearchParams({scope: scope, q: entry.query.q}), {
        credentials: 'same-origin', headers: {'HX-Request': 'true'}
      }).then(function (response) {
        if (!response.ok) { throw new Error('picker unavailable'); }
        return response.text();
      }).then(function (body) {
        if (pickers.get(field) !== entry || !field.isConnected || field.value !== text ||
            (scope === 'mention' && field.selectionStart !== caret)) { return; }
        /* Серверный фрагмент не вставляется в живой DOM: копируем только данные и текст. */
        var parsed = new DOMParser().parseFromString(body, 'text/html');
        var count = 0;
        parsed.querySelectorAll('[data-pick-value][data-pick-label]').forEach(function (row) {
          var value = row.dataset.pickValue;
          var valid = scope === 'to' ? /^[pu][1-9]\d{0,8}$/.test(value) :
            (scope === 'mention' ? /^p[1-9]\d{0,8}$/.test(value) : /^[1-9]\d{0,8}$/.test(value));
          if (!valid || count >= 20) { return; }
          count++;
          var button = document.createElement('button');
          button.type = 'button';
          button.dataset.pickValue = value;
          button.dataset.pickLabel = row.dataset.pickLabel;
          button.textContent = row.textContent;
          list.appendChild(button);
        });
      }).catch(function () {
        if (pickers.get(field) === entry) { list.replaceChildren(); }
      });
    }, 150);
  }

  function addTo(data, value, label) {
    if (!/^(all|[pu][1-9]\d{0,8})$/.test(value)) { return; }
    var container = data.form.querySelector('[data-feed-to]');
    if (!container || Array.from(container.querySelectorAll('input[name="to"]')).some(function (input) { return input.value === value; })) { return; }
    var pill = document.createElement('span');
    pill.dataset.toPill = value;
    pill.textContent = label;
    var input = document.createElement('input');
    input.type = 'hidden'; input.name = 'to'; input.value = value;
    var remove = document.createElement('button');
    remove.type = 'button'; remove.dataset.action = 'to-remove';
    remove.setAttribute('aria-label', 'Убрать адресата'); remove.textContent = '×';
    pill.append(input, remove); container.appendChild(pill);
  }

  document.addEventListener('beforeinput', function (event) {
    var data = state(currentForm(event.target));
    if (!data || event.target !== data.area) { return; }
    if (event.inputType === 'historyUndo' || event.inputType === 'historyRedo') {
      data.before = null;
      return;
    }
    var start = data.area.selectionStart;
    var end = data.area.selectionEnd;
    if (start === end && event.inputType === 'deleteContentBackward') { start = Math.max(0, start - 1); }
    if (start === end && event.inputType === 'deleteContentForward') { end++; }
    data.before = {start: start, end: end};
  });
  document.addEventListener('input', function (event) {
    var data = state(currentForm(event.target));
    if (data && event.target === data.area) {
      if (event.inputType === 'historyUndo' || event.inputType === 'historyRedo') {
        /* Каретка не задаёт диапазон history-правки; одинаковый текст не доказывает ID.
           Без истории диапазонов безопасно снять все связи только этого поля. */
        data.mentions = [];
        data.previous = data.area.value;
        data.before = null;
        refresh(data);
      } else { changed(data); }
    }
    if (event.target.matches('[data-feed-picker]')) { suggestions(event.target); }
  });
  document.addEventListener('change', function (event) {
    var form = currentForm(event.target);
    var data = state(form);
    if (data && event.target.name === 'kind') { refresh(data); }
    /* T-7301 r2/r3: синхронизация `until` при смене вида и срока — без зависимости от состояния Alpine
       (форма могла ещё не инициализироваться); при смене вида на не-«Важное» required-поле
       очищается/выключается, иначе невидимое поле блокировало бы submit. */
    if (event.target.name === 'term' || event.target.name === 'kind') { syncUntilField(form); }
  });
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-pick-value], [data-action="to-remove"], [data-action="pdn-fix"]');
    if (!button) { return; }
    var form = currentForm(button);
    var data = state(form);
    var list = button.closest('[data-feed-pick-list]');
    var owner = button.closest('form');
    if (!owner) { return; }
    if (button.dataset.action === 'pdn-fix') {
      var warning = button.closest('[data-feed-pdn]');
      if (warning) { warning.remove(); }
      if (data) { data.area.focus(); return; }
      var fallbackForm = button.closest('form');
      if (fallbackForm) {
        var fallbackArea = fallbackForm.querySelector('textarea[name="text"]');
        if (fallbackArea) { fallbackArea.focus(); }
      }
      return;
    }
    if (button.dataset.action === 'to-remove' && data) {
      var pill = button.closest('[data-to-pill]');
      if (pill && !pill.hasAttribute('data-mentioned') && !pill.hasAttribute('data-saved')) { pill.remove(); }
      return;
    }
    var scope = list ? list.dataset.feedPickList : 'to';
    var field = owner.querySelector('[data-feed-picker="' + scope + '"]');
    var entry = field && pickers.get(field);
    if (scope === 'mention' && data && entry) {
      var active = query(field);
      if (!active || !entry.query || active.start !== entry.query.start || active.end !== entry.query.end || active.q !== entry.query.q || !/^p[1-9]\d{0,8}$/.test(button.dataset.pickValue)) { return; }
      var label = button.dataset.pickLabel;
      var value = '@' + label;
      field.setRangeText(value, active.start, active.end, 'end');
      changed(data);
      data.mentions.push({id: button.dataset.pickValue.slice(1), label: label, start: active.start, end: active.start + value.length});
      refresh(data); field.focus();
    } else if (scope === 'to' && data) {
      addTo(data, button.dataset.pickValue, button.dataset.pickLabel);
      if (field) { field.value = ''; field.focus(); }
    } else if (scope === 'author' && field && /^[1-9]\d{0,8}$/.test(button.dataset.pickValue)) {
      var author = owner.querySelector('input[type="hidden"][name="author"]');
      if (author) { author.value = button.dataset.pickValue; field.value = button.dataset.pickLabel; }
    }
    if (list) { list.replaceChildren(); }
    if (field) { pickers.delete(field); }
  });

  /* Не мутируем textarea на HTMX-submit: ошибка сети оставляет имена и mapping в форме.
     configRequest идёт ПОСЛЕ сбора параметров, поэтому меняем именно parameters. */
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-action="reply"]');
    if (!button) { return; }
    var form = commentForm(button);
    var data = state(form);
    if (!data) { return; }
    var id = button.dataset.replyId;
    var name = button.dataset.replyName;
    var area = data.area;
    var start = area.selectionStart || area.value.length;
    var end = area.selectionEnd || start;
    var prefix = (start > 0 && !/\s$/.test(area.value.slice(0, start))) ? ' ' : '';
    var value = '@' + name;
    var trailing = ' ';
    area.setRangeText(prefix + value + trailing, start, end, 'end');
    changed(data);
    var mentionStart = start + prefix.length;
    data.mentions.push({id: id, label: name, start: mentionStart, end: mentionStart + value.length});
    refresh(data);
    area.focus();
  });

  document.addEventListener('htmx:configRequest', function (event) {
    var data = state(currentForm(event.detail.elt));
    if (data && event.detail.verb.toLowerCase() === 'post') {
      changed(data);
      event.detail.parameters.text = serialized(data);
    }
  });
  /* Native POST и FormData: событие не всплывает, поэтому capture; textarea не мутируем.
     https://developer.mozilla.org/en-US/docs/Web/API/HTMLFormElement/formdata_event */
  document.addEventListener('formdata', function (event) {
    var data = state(currentForm(event.target));
    if (data) { changed(data); event.formData.set('text', serialized(data)); }
  }, true);

  /* T-7226: файлы уходят по одному отдельным запросом в /feed/files/; scope и номер при
     правке — с атрибутов поля, have — скрытые поля файлов этой формы. Ответ — таблетка или
     отказ у поля file; крестик таблетки убирает свой непривязанный файл. */
  function csrfToken(form) {
    var input = form ? form.querySelector('input[name="csrfmiddlewaretoken"]') : null;
    return input ? input.value : '';
  }

  function filePost(url, form, data) {
    data.append('csrfmiddlewaretoken', csrfToken(form));
    return fetch(url, {method: 'POST', body: data, credentials: 'same-origin',
      headers: {'HX-Request': 'true'}}).then(function (response) {
      if (!response.ok) { throw new Error('feed files unavailable'); }
      return response.text();
    });
  }

  function fileErrorSpot(input) {
    return input.closest('[data-feed-files], form') || input.parentElement;
  }

  function clearFileErrors(input) {
    var form = input.closest('form');
    if (form) { form.querySelectorAll('[data-error="file"]').forEach(function (node) { node.remove(); }); }
  }

  function filePill(input, body) {
    var parsed = new DOMParser().parseFromString(body, 'text/html');
    var error = parsed.querySelector('[data-error="file"][data-code]');
    if (error) {
      clearFileErrors(input);
      fileErrorSpot(input).after(error);
      return;
    }
    clearFileErrors(input);
    var pill = parsed.querySelector('[data-feed-file]');
    var form = input.closest('form');
    var list = form && form.querySelector('[data-feed-files]');
    if (pill && list) { list.appendChild(pill); }
  }

  function uploadOne(input, file) {
    var form = input.closest('form');
    var data = new FormData();
    data.append('file', file);
    data.append('scope', input.dataset.feedUpload === 'comment' ? 'comment' : 'post');
    if (input.dataset.uploadPost) { data.append('post', input.dataset.uploadPost); }
    if (input.dataset.uploadComment) { data.append('comment', input.dataset.uploadComment); }
    if (form) {
      form.querySelectorAll('input[name="files"]').forEach(function (hidden) {
        data.append('have', hidden.value);
      });
    }
    return filePost('/feed/files/', form, data).then(function (body) { filePill(input, body); });
  }

  document.addEventListener('change', function (event) {
    var input = event.target;
    if (!input.matches || !input.matches('input[type="file"][data-feed-upload]')) { return; }
    var files = Array.from(input.files || []);
    input.value = '';
    files.reduce(function (chain, file) {
      return chain.then(function () { return uploadOne(input, file); });
    }, Promise.resolve()).catch(function () { /* сеть: файл не загружен, поле очищено */ });
  });

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-action="file-remove"]');
    if (!button) { return; }
    var pill = button.closest('[data-feed-file]');
    if (!pill) { return; }
    var form = pill.closest('form');
    filePost('/feed/files/' + pill.dataset.feedFile + '/delete/', form, new FormData())
      .then(function () { pill.remove(); })
      .catch(function () { /* убрать не удалось: таблетка остаётся */ });
  });

  function enhance() {
    document.querySelectorAll('form[data-feed-form]').forEach(function (form) {
      if (!form.hasAttribute('x-data')) { form.setAttribute('x-data', 'feedForm'); }
      syncUntilField(form);  /* T-7301 r2: состояние `until` — по отмеченному term, на каждой вставке */
      /* Alpine mutation observer initializes inserted roots, including HTMX OOB. */
    });
  }
  function register() {
    window.Alpine.data('feedForm', function () {
      return {init: function () { initialize(this.$el); }};
    });
    enhance();
  }
  if (window.Alpine) { register(); }
  else { document.addEventListener('alpine:init', register, {once: true}); }
  document.addEventListener('htmx:load', enhance);
  document.addEventListener('htmx:oobAfterSwap', enhance);
})();
