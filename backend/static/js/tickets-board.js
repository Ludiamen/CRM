/* Доска заявок (срез 013): перенос карточки и меню статуса. Без JS работает меню в карточке. */
(function () {
  "use strict";

  function token() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function payload(card, column) {
    return new URLSearchParams({
      number: card.getAttribute("data-number"),
      expected: card.getAttribute("data-expected") || "",
      status: column.getAttribute("data-column"),
      query: window.location.search.replace(/^\?/, "")
    });
  }

  function replaceBoard(html) {
    var board = document.querySelector("[data-ticket-board]");
    if (!board) return;
    var box = document.createElement("div");
    box.innerHTML = html;
    var next = box.querySelector("[data-ticket-board]");
    if (next) {
      board.replaceWith(next);
      bind(next);
    }
  }

  function move(card, column) {
    var board = document.querySelector("[data-ticket-board]");
    if (!board || !card || !column) return;
    fetch(board.getAttribute("data-move-url"), {
      method: "POST",
      headers: {"X-CSRFToken": token(), "HX-Request": "true"},
      body: payload(card, column)
    }).then(function (response) {
      if (!response.ok) {
        return response.json().then(function (data) {
          window.alert(data.error || "Не удалось перенести заявку");
          window.location.reload();
        });
      }
      return response.text().then(replaceBoard);
    });
  }

  function bind(board) {
    if (board.dataset.dnd === "1") return;
    board.dataset.dnd = "1";
    board.addEventListener("dragstart", function (event) {
      var card = event.target.closest("[data-ticket-card]");
      if (card && event.dataTransfer) {
        event.dataTransfer.setData("text/plain", card.getAttribute("data-number"));
      }
    });
    board.addEventListener("dragover", function (event) {
      var list = event.target.closest("[data-drop]");
      if (list) event.preventDefault();
    });
    board.addEventListener("drop", function (event) {
      var list = event.target.closest("[data-drop]");
      var card = event.target.closest("[data-ticket-card]");
      if (!list) return;
      event.preventDefault();
      var dragged = board.querySelector("[data-ticket-card][data-dragging='1']");
      if (!dragged) {
        var number = event.dataTransfer ? event.dataTransfer.getData("text/plain") : "";
        dragged = number ? board.querySelector("[data-ticket-card][data-number='" + number + "']") : null;
      }
      if (dragged) move(dragged, list);
    });
    board.addEventListener("dragstart", function (event) {
      var card = event.target.closest("[data-ticket-card]");
      if (card) card.setAttribute("data-dragging", "1");
    });
    board.addEventListener("dragend", function (event) {
      var card = event.target.closest("[data-ticket-card]");
      if (card) card.removeAttribute("data-dragging");
    });
  }

  document.querySelectorAll("[data-ticket-board]").forEach(bind);
})();
