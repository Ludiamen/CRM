/* Доска «Стадии»: перенос карточки и «показать ещё» (срез 015). */
(function () {
  "use strict";

  function token() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function replaceBoard(html) {
    var board = document.querySelector("[data-lists-board]");
    if (!board) return;
    var box = document.createElement("div");
    box.innerHTML = html;
    var next = box.querySelector("[data-lists-board]");
    if (next) board.replaceWith(next);
  }

  function move(card, column) {
    var board = document.querySelector("[data-lists-board]");
    if (!board || !card || !column) return;
    fetch(board.getAttribute("data-move-url"), {
      method: "POST",
      headers: {"X-CSRFToken": token(), "HX-Request": "true", "Accept": "text/html"},
      body: new URLSearchParams({
        number: card.getAttribute("data-number"),
        base_version: card.getAttribute("data-version") || "0",
        stage: column.getAttribute("data-column")
      })
    }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (html) {
          if (html && html.indexOf("data-lists-board") >= 0) replaceBoard(html);
          else window.alert("Не удалось перенести запись");
        });
      }
      return response.text().then(replaceBoard);
    });
  }

  document.addEventListener("dragstart", function (event) {
    var card = event.target.closest("[data-card]");
    if (card && event.dataTransfer) event.dataTransfer.setData("text/plain", card.getAttribute("data-number"));
  });
  document.addEventListener("dragover", function (event) {
    if (event.target.closest("[data-drop]")) event.preventDefault();
  });
  document.addEventListener("drop", function (event) {
    var column = event.target.closest("[data-drop]");
    if (!column) return;
    event.preventDefault();
    var number = event.dataTransfer ? event.dataTransfer.getData("text/plain") : "";
    var card = number ? document.querySelector('[data-card="' + number + '"]') : null;
    if (card) move(card, column);
  });
})();
