/* Мессенджер (срез 008): подсказка «@» и «#» (T-8210).
 *
 * Набирая «@Ив» или «#Ан», сотрудник видит до 20 строк участников и своих чатов. Выбор подставляется в поле
 * как «@ФИО»/«#название», а на сервер уходит маркер «@[u<id>]»/«@[c<id>]»: перед отправкой формы подставленные
 * подписи заменяются на маркеры (CONTRACT-008, 12.3).
 */
(function () {
  "use strict";

  var TOKEN = /(^|\s)([@#])([A-Za-zА-Яа-яЁё0-9_-]{2,})$/;

  function setup(form) {
    var box = form.querySelector("[data-messenger-mention-list]");
    var area = form.querySelector('textarea[name="text"]');
    if (!box || !area || !box.dataset.mentionUrl) return;
    var chosen = [];

    function hide() {
      box.classList.remove("is-open");
      box.replaceChildren();
    }

    function tokenAt() {
      var before = area.value.slice(0, area.selectionStart);
      var match = TOKEN.exec(before);
      if (!match) return null;
      return {kind: match[2], query: match[3], start: match.index + match[1].length};
    }

    function pick(row) {
      var token = tokenAt();
      if (!token) return;
      var value = row.getAttribute("data-mention-value") || "";
      var label = row.getAttribute("data-mention-label") || "";
      if (!value || !label) return;
      if (token.kind === "#" ? value.charAt(0) !== "c" : "uc".indexOf(value.charAt(0)) < 0) return;
      var shown = (value.charAt(0) === "c" ? "#" : "@") + label;
      var marker = "@[" + value + "]";
      var before = area.value.slice(0, token.start);
      var after = area.value.slice(area.selectionStart);
      area.value = before + shown + " " + after;
      area.selectionStart = area.selectionEnd = (before + shown + " ").length;
      chosen.push({shown: shown, marker: marker});
      hide();
      area.focus();
    }

    area.addEventListener("input", function () {
      var token = tokenAt();
      if (!token) return hide();
      var url = box.dataset.mentionUrl + "&q=" + encodeURIComponent(token.query);
      fetch(url, {credentials: "same-origin", headers: {"X-Requested-With": "fetch"}})
        .then(function (response) { return response.ok ? response.text() : ""; })
        .then(function (html) {
          var holder = document.createElement("div");
          holder.innerHTML = html;
          var rows = Array.prototype.slice.call(holder.querySelectorAll("[data-mention-value]"));
          rows = rows.filter(function (row) {
            var value = (row.getAttribute("data-mention-value") || "");
            // «@» показывает и участников, и свои чаты (подпись «#название» подставляет выбор);
            // «#» — только чаты.
            return token.kind === "#" ? value.charAt(0) === "c" : true;
          });
          box.replaceChildren.apply(box, rows);
          box.classList.toggle("is-open", rows.length > 0);
        })
        .catch(hide);
    });

    box.addEventListener("mousedown", function (event) {
      var row = event.target.closest("[data-mention-value]");
      if (row) {
        event.preventDefault();
        pick(row);
      }
    });

    area.addEventListener("keydown", function (event) {
      if (event.key === "Escape") hide();
    });

    form.addEventListener("submit", function () {
      var value = area.value;
      chosen.forEach(function (item) {
        value = value.split(item.shown).join(item.marker);
      });
      area.value = value;
    });
  }

  function start() {
    document.querySelectorAll("#messenger-form").forEach(setup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
  document.body.addEventListener("htmx:afterSwap", start);
})();
/* Соединение беседы (T-8213): состояние `data-ws`, `sync` при открытии, переход по `data-hx-redirect`.
 *
 * Узел соединения ищется по адресу слоя мессенджера: у колокольчика тоже есть `data-ws`, и он стоит в
 * разметке первым, поэтому голый `[data-ws]` давал чужое соединение (приёмка T-8302, 2026-11-20).
 */
(function () {
  "use strict";

  var SELECTOR = '[data-ws][ws-connect*="/ws/messenger/"]';

  function isMessenger(elt) {
    return !!(elt && elt.getAttribute && (elt.getAttribute("ws-connect") || "").indexOf("/ws/messenger/") >= 0);
  }

  function node() {
    return document.querySelector(SELECTOR);
  }

  function state(value) {
    var ws = node();
    if (ws) ws.dataset.ws = value;
  }

  function chatId(elt) {
    var match = /[?&]chat=(\d+)/.exec((elt && elt.getAttribute("ws-connect")) || "");
    if (match) return Number(match[1]);
    var byPath = window.location.pathname.match(/\/messenger\/chats\/(\d+)\//);
    return byPath ? Number(byPath[1]) : 0;
  }

  function send(wrapper, payload) {
    if (!wrapper || typeof wrapper.send !== "function") return;
    try {
      wrapper.send(JSON.stringify(payload));
    } catch (error) {
      /* соединение закрылось между событиями — переподключение делает расширение htmx */
    }
  }

  var socket = null;

  document.body.addEventListener("htmx:wsOpen", function (event) {
    var detail = event.detail || {};
    var elt = detail.elt || node();
    if (!isMessenger(elt)) return;
    socket = detail.socketWrapper || socket;
    // Первая беседа справа от списка — предпросмотр: соединение открыто, но `sync` не шлём,
    // иначе сервер поставил бы отметку прочтения за заход в список (решение владельца 2026-11-20).
    if (elt.hasAttribute("data-preview")) {
      state("open");
      return;
    }
    var id = chatId(elt);
    if (id) send(socket, {sync: {chat: id, at: new Date().toISOString()}});
  });

  document.body.addEventListener("htmx:wsBeforeMessage", function (event) {
    var elt = event.target;
    if (!isMessenger(elt)) return;
    var message = (event.detail && event.detail.message) || "";
    if (message.indexOf("messenger-synced") >= 0) {
      // Служебный кадр идёт с `hx-swap-oob`, а цели `#messenger-synced` в разметке нет: htmx удалил бы его
      // с ошибкой в консоли. Состояние ставим сами (CONTRACT-008 12.4).
      event.preventDefault();
      state("open");
      return;
    }
    // Сообщение в открытой беседе прочитано: клиент отвечает отметкой, как только кадр пришёл (FR-666).
    if (message.indexOf("data-message-id") >= 0 && !elt.hasAttribute("data-preview")) {
      var id = chatId(elt);
      if (id) send(socket, {read: {chat: id, at: new Date().toISOString()}});
    }
  });

  document.body.addEventListener("htmx:wsClose", function (event) {
    var elt = (event.detail && event.detail.elt) || node();
    if (isMessenger(elt)) state("closed");
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (document.getElementById("messenger-synced")) state("open");
    var target = event.detail && event.detail.elt;
    var redirect = target && target.querySelector ? target.querySelector("[data-hx-redirect]") : null;
    if (redirect) window.location.assign(redirect.getAttribute("data-hx-redirect"));
    if (document.querySelector("[data-hx-redirect]")) {
      window.location.assign(document.querySelector("[data-hx-redirect]").getAttribute("data-hx-redirect"));
    }
  });
})();

/* История: сохранение места при догрузке старых и «Назад» на телефоне (T-8222). */
(function () {
  "use strict";

  var scroll = null;

  function firstVisible(box) {
    var boxTop = box.getBoundingClientRect().top;
    var nodes = box.querySelectorAll("article[data-message-id]");
    for (var index = 0; index < nodes.length; index += 1) {
      if (nodes[index].getBoundingClientRect().bottom > boxTop) return nodes[index];
    }
    return null;
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var box = document.getElementById("messenger-messages");
    var target = event.detail && event.detail.elt;
    if (!box || !target || !box.contains(target)) return;
    var anchor = firstVisible(box);
    // Место держим по видимому сообщению: высота контейнера меняется и сверху, и снизу (кнопка «раньше»).
    scroll = anchor ? {node: box, id: anchor.id,
                       offset: anchor.getBoundingClientRect().top - box.getBoundingClientRect().top} : null;
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (!scroll) return;
    var box = document.getElementById("messenger-messages");
    if (!box || box !== scroll.node) {
      scroll = null;
      return;
    }
    var anchor = scroll.id ? document.getElementById(scroll.id) : null;
    if (anchor) {
      var offset = anchor.getBoundingClientRect().top - box.getBoundingClientRect().top;
      box.scrollTop += offset - scroll.offset;
    }
    scroll = null;
  });
})();

/* Вложения (T-8215): выбранный файл сразу уходит на `/messenger/files/`, ответ — таблетка со скрытым `files`;
 * крестик таблетки убирает файл (CONTRACT-008 10.2, 12.5). Ошибка службы (размер, тип, предел) рисуется рядом. */
(function () {
  "use strict";

  function csrf(form) {
    var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function current(form) {
    return Array.prototype.slice.call(form.querySelectorAll("[data-messenger-file]"));
  }

  function sendFile(form, box, input, file) {
    var body = new FormData();
    body.append("chat", input.getAttribute("data-chat") || "");
    current(form).forEach(function (pill) {
      body.append("have", pill.getAttribute("data-messenger-file") || "");
    });
    body.append("file", file, file.name);
    fetch("/messenger/files/", {
      method: "POST",
      credentials: "same-origin",
      headers: {"X-CSRFToken": csrf(form), "X-Requested-With": "fetch"},
      body: body
    })
      .then(function (response) { return response.text(); })
      .then(function (html) { box.insertAdjacentHTML("beforeend", html); })
      .catch(function () { /* сеть недоступна — файл просто не прикрепился */ });
  }

  function setup(form) {
    var input = form.querySelector("input[type='file'][data-messenger-upload]");
    var box = form.querySelector("[data-messenger-files]");
    if (!input || !box) return;

    input.addEventListener("change", function () {
      Array.prototype.forEach.call(input.files || [], function (file) {
        sendFile(form, box, input, file);
      });
      input.value = "";
    });

    form.addEventListener("click", function (event) {
      var button = event.target.closest('[data-action="file-remove"]');
      if (!button) return;
      event.preventDefault();
      var pill = button.closest("[data-messenger-file]");
      if (!pill) return;
      fetch("/messenger/files/" + pill.getAttribute("data-messenger-file") + "/delete/", {
        method: "POST",
        credentials: "same-origin",
        headers: {"X-CSRFToken": csrf(form), "X-Requested-With": "fetch"}
      }).then(function (response) {
        if (response.ok) pill.remove();
      }).catch(function () { /* остаётся на месте — повтор */ });
    });
  }

  function start() {
    document.querySelectorAll("#messenger-form").forEach(setup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
  document.body.addEventListener("htmx:afterSwap", start);
})();

/* Действия с сообщением (T-8209): «Ответить» — цитата в форме ввода, «Править» — форма в самом сообщении. */
(function () {
  "use strict";

  function clearQuote() {
    var box = document.querySelector("#messenger-form [data-quote-box]");
    var hidden = document.querySelector('#messenger-form input[name="quote"]');
    if (box) box.replaceChildren();
    if (hidden) hidden.value = "";
  }

  function quoteFor(article) {
    var box = document.querySelector("#messenger-form [data-quote-box]");
    var hidden = document.querySelector('#messenger-form input[name="quote"]');
    if (!box || !hidden || !article) return;
    hidden.value = article.getAttribute("data-message-id") || "";
    var author = article.querySelector(".messenger-message-author");
    var text = article.querySelector(".messenger-message-text");
    var block = document.createElement("blockquote");
    block.setAttribute("data-quote", "");
    block.setAttribute("data-quote-id", hidden.value);
    var who = document.createElement("span");
    who.className = "messenger-quote-author";
    who.textContent = author ? author.textContent.trim() : "";
    var body = document.createElement("span");
    body.className = "messenger-quote-text";
    body.textContent = text ? text.textContent.trim() : "";
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-link btn-sm";
    remove.setAttribute("data-action", "quote-remove");
    remove.setAttribute("aria-label", "Убрать цитату");
    remove.textContent = "×";
    block.append(who, body, remove);
    box.replaceChildren(block);
  }

  document.body.addEventListener("click", function (event) {
    var action = event.target.closest ? event.target.closest("[data-action]") : null;
    if (!action) return;
    var name = action.getAttribute("data-action");
    if (name === "reply") {
      event.preventDefault();
      quoteFor(action.closest("article"));
      return;
    }
    if (name === "quote-remove") {
      event.preventDefault();
      clearQuote();
      return;
    }
    if (name === "edit") {
      var article = action.closest("article");
      var editor = article ? article.querySelector("[data-messenger-edit]") : null;
      if (editor) {
        event.preventDefault();
        editor.hidden = false;
        var area = editor.querySelector('textarea[name="text"]');
        if (area) area.focus();
      }
    }
  });
})();

/* Числа пункта меню и строки списка приходят в колокольчик; на странице беседы строк списка нет, и htmx
 * пишет в консоль `oobErrorNoTarget`. Цели строк — данные списка, их отсутствие нормально: глушим только
 * этот случай, прочие ошибки OOB остаются видимыми (критерий T-8301 — чистая консоль). */
(function () {
  "use strict";
  var native = console.error;
  console.error = function () {
    var text = Array.prototype.join.call(arguments, " ");
    if (text.indexOf("htmx:oobErrorNoTarget") >= 0 && /#chat-\d+-(unread|preview)/.test(text)) return;
    return native.apply(console, arguments);
  };
})();
