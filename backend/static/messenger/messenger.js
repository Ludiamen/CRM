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
      if (!value || !label || value.charAt(0) !== (token.kind === "@" ? "u" : "c")) return;
      var shown = (token.kind === "@" ? "@" : "#") + label;
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
            return (row.getAttribute("data-mention-value") || "").charAt(0) === (token.kind === "@" ? "u" : "c");
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
/* Соединение беседы (T-8213): состояние `data-ws`, `sync` при открытии, переход по `data-hx-redirect`. */
(function () {
  "use strict";

  function node() {
    return document.querySelector("[data-ws]");
  }

  function state(value) {
    var ws = node();
    if (ws) ws.dataset.ws = value;
  }

  function send(payload) {
    var ws = node();
    if (!ws || !ws.ws || typeof ws.ws.send !== "function") return;
    try {
      ws.ws.send(JSON.stringify(payload));
    } catch (error) {
      /* соединение закрылось между событиями — переподключение делает расширение htmx */
    }
  }

  document.body.addEventListener("htmx:wsOpen", function () {
    var chat = new URLSearchParams(window.location.search).get("chat");
    var match = window.location.pathname.match(/\/messenger\/chats\/(\d+)\//);
    var id = match ? Number(match[1]) : Number(chat || 0);
    if (id) {
      send({sync: {chat: id, at: new Date().toISOString()}});
    }
  });

  document.body.addEventListener("htmx:wsClose", function () {
    state("closed");
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
