/* Вставка частого ответа в поле ответа карточки заявки. */
(function () {
  function setup(root) {
    (root || document).querySelectorAll("[data-answer-tools]").forEach(function (tools) {
      var select = tools.querySelector("[data-answer-select]");
      var button = tools.querySelector("[data-answer-insert]");
      if (!select || !button || button.dataset.answerReady) return;
      button.dataset.answerReady = "1";
      select.addEventListener("change", function () {
        var id = select.value || "0";
        button.setAttribute("hx-get", "/servicedesk/answers/" + id + "/insert/?ticket=" + tools.dataset.ticket);
        if (window.htmx) window.htmx.process(button);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () { setup(document); });
  document.addEventListener("htmx:afterSwap", function (event) {
    setup(event.target);
    var tools = event.target.closest && event.target.closest("[data-answer-tools]");
    if (!tools) return;
    var result = tools.querySelector("[data-answer-result]");
    var textarea = tools.closest("form").querySelector('textarea[name="text"]');
    if (result && textarea && result.textContent) textarea.value = result.textContent;
  });
})();
