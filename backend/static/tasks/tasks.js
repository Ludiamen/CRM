/* Задачи (срез 009): перетаскивание карточек досок. Каркас T-9008; полное поведение — T-9205.
 *
 * SortableJS подключается в _assets.html только для страниц /tasks/ и /settings/tasks/;
 * без JS и на телефоне работает выбор поля в карточке (FR-684).
 */
(function () {
  "use strict";

  function initBoard(board) {
    if (typeof window.Sortable !== "function") {
      return;
    }
    var moveUrl = board.getAttribute("data-move-url");
    if (!moveUrl) {
      return;
    }
    window.Sortable.create(board, {
      group: board.getAttribute("data-board"),
      draggable: "[data-task-card]",
      onEnd: function (event) {
        var card = event.item;
        var column = event.to.closest("[data-column]");
        if (!card || !column) {
          return;
        }
        var taskId = card.getAttribute("data-task-id");
        if (!taskId) {
          return;
        }
        var token = document.querySelector('input[name="csrfmiddlewaretoken"]');
        fetch(moveUrl.replace("{id}", taskId), {
          method: "POST",
          headers: { "X-CSRFToken": token ? token.value : "", "HX-Request": "true" },
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
            initBoard(next);
          }
        });
      }
    });
  }

  function init() {
    document.querySelectorAll("[data-board][data-move-url]").forEach(initBoard);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();