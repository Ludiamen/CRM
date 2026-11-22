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

  function nativeDrag(board) {
    if (board.dataset.dnd === "1") {
      return;
    }
    board.dataset.dnd = "1";
    board.addEventListener("dragstart", function (event) {
      board.dataset.dragging = "1";
      var card = event.target.closest("[data-task-card]");
      if (card && event.dataTransfer) {
        event.dataTransfer.setData("text/plain", card.getAttribute("data-task-id"));
      }
    });
    board.addEventListener("dragend", function () {
      window.setTimeout(function () { delete board.dataset.dragging; }, 300);
    });
    board.addEventListener("click", function (event) {
      if (board.dataset.dragging) {
        event.preventDefault();
        event.stopPropagation();
      }
    }, true);
    board.addEventListener("dragover", function (event) {
      event.preventDefault();
    });
    board.addEventListener("drop", function (event) {
      var column = event.target.closest("[data-column]");
      var taskId = event.dataTransfer && event.dataTransfer.getData("text/plain");
      var card = taskId && board.querySelector('[data-task-card][data-task-id="' + taskId + '"]');
      if (column && card) {
        event.preventDefault();
        move(board, card, column);
      }
    });
  }

  function init(board) {
    if (typeof window.Sortable !== "function" || !board.getAttribute("data-move-url")) {
      return;
    }
    nativeDrag(board);
    board.querySelectorAll("[data-column]").forEach(function (column) {
      var list = column.querySelector("ol") || column;
      window.Sortable.create(list, {
        group: board.getAttribute("data-board"),
        draggable: "[data-task-card]",
        animation: 120,
        forceFallback: true,
        fallbackTolerance: 3,
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