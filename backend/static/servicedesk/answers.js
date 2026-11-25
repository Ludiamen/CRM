/* Срез 011 (T-11217): вставка частого ответа в форму ответа карточки заявки. */
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-answer-insert]");
    if (!button) return;
    var tools = button.closest("[data-answer-tools]");
    var select = tools && tools.querySelector("[data-answer-select]");
    var textarea = tools && tools.closest("form") && tools.closest("form").querySelector("textarea[name=text]");
    if (!select || !select.value || !textarea) return;
    var ticket = button.getAttribute("data-ticket") || "";
    var url = "/servicedesk/answers/" + select.value + "/insert/?ticket=" + encodeURIComponent(ticket);
    event.preventDefault();
    fetch(url, {credentials: "same-origin", headers: {"X-Requested-With": "XMLHttpRequest"}})
      .then(function (response) { return response.ok ? response.text() : ""; })
      .then(function (text) { if (text) textarea.value = textarea.value ? textarea.value + "\n" + text : text; });
  });
})();
