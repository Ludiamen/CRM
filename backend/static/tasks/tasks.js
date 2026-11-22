/* Задачи (срез 009): перетаскивание карточек досок (T-9205; FR-680…684).
 *
 * SortableJS подключается в _assets.html только для страниц /tasks/ и /settings/tasks/. Каждая колонка — отдельный
 * список одной группы доски; после ответа HTMX колонки заменяются и инициализируются заново. Без JS и на телефоне
 * работает выбор поля в карточке (FR-684).
 */
(function () {
  "use strict";

  function token() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function move(board, card, column) {
    var template = board.getAttribute("data-move-url");
    var taskId = card.getAttribute("data-task-id");
    if (!template || !taskId || !column) {
      return;
    }
    fetch(template.replace("{id}", taskId), {
      method: "POST",
      headers: { "X-CSRFToken": token(), "HX-Request": "true" },
      body: new URLSearchParams({
        board: board.getAttribute("data-board"),
        value: column.getAttribute("data-column")
      })
    }).then(function (response) {
      return response.text();
    }).then(function (html) {
      board.outerHTML = html;
      var next = document.querySelector("[data-board]");
      if (next) {
        init(next);
      }
    });
  }

  function init(board) {
    if (typeof window.Sortable !== "function" || !board.getAttribute("data-move-url")) {
      return;
    }
    board.querySelectorAll("[data-column]").forEach(function (column) {
      window.Sortable.create(column, {
        group: board.getAttribute("data-board"),
        draggable: "[data-task-card]",
        animation: 120,
        onEnd: function (event) {
          var card = event.item;
          var target = event.to.closest("[data-column]");
          if (!card || !target || target === event.from.closest("[data-column]")) {
            return;
          }
          move(board, card, target);
        }
      });
    });
  }

  function start() {
    document.querySelectorAll("[data-board]").forEach(init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();