// Скрипты раздела «Списки»: таблица, карточки, настройка списка (срез 006).
// Без eval и без внедрения чужого HTML; обработчики навешены на document (переживают замену фрагментов HTMX).
// Разделы-метки: T-6214b (общие части: диалог подтверждения; поля; значения; права), T-6216 (таблица) — ниже.
(function () {
  "use strict";

  /* === T-6214b: общие части (И10) === */

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  // --- общий диалог подтверждения (15.5 пп. 1–2): текст — data-confirm-text кнопки, действие — action формы-источника
  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("form[data-lists-confirm-source] button[type=submit]") : null;
    if (!button) { return; }
    var dialog = document.querySelector("dialog[data-lists-confirm]");
    if (!dialog || typeof dialog.showModal !== "function" || button.disabled) { return; }
    var source = button.form;
    var form = dialog.querySelector("form[data-lists-confirm-form]");
    event.preventDefault();
    form.setAttribute("action", source.getAttribute("action") || "");
    dialog.querySelector("[data-lists-confirm-text]").textContent = button.getAttribute("data-confirm-text") || "Подтвердите действие.";
    // остальные поля формы-источника (например, отмеченные строки) уходят вместе с подтверждением
    Array.prototype.forEach.call(form.querySelectorAll("input[data-copied]"), function (old) { old.remove(); });
    Array.prototype.forEach.call(source.elements, function (item) {
      if (!item.name || item.name === "csrfmiddlewaretoken" || item.type === "submit" || item.type === "button" ||
          item.disabled || ((item.type === "checkbox" || item.type === "radio") && !item.checked)) { return; }
      var copy = document.createElement("input");
      copy.type = "hidden";
      copy.name = item.name;
      copy.value = item.value;
      copy.setAttribute("data-copied", "");
      form.appendChild(copy);
    });
    dialog.showModal();
  });

  document.addEventListener("click", function (event) {
    var cancel = event.target.closest ? event.target.closest("dialog[data-lists-confirm] button[data-action=cancel]") : null;
    if (cancel) { cancel.closest("dialog").close(); }
  });

  // --- вкладка «Поля»: перетаскивание порядка (ручка [data-lists-drag]); стрелки работают и без скрипта
  var drag = null;

  function fieldCodes(body) {
    return Array.prototype.map.call(body.querySelectorAll("tr[data-field-code]"), function (row) {
      return row.getAttribute("data-field-code");
    }).filter(function (code) { return code !== "title"; });
  }

  document.addEventListener("pointerdown", function (event) {
    var handle = event.target.closest ? event.target.closest("[data-lists-drag]") : null;
    if (!handle || (event.button !== undefined && event.button > 0)) { return; }
    var row = handle.closest("tr[data-field-code]");
    if (!row) { return; }
    event.preventDefault();
    drag = {row: row, body: row.parentNode, before: fieldCodes(row.parentNode)};
    row.classList.add("lists-dragging");
  });

  document.addEventListener("pointermove", function (event) {
    if (!drag) { return; }
    var under = document.elementFromPoint(event.clientX, event.clientY);
    var target = under && under.closest ? under.closest("tr[data-field-code]") : null;
    if (!target || target === drag.row || target.parentNode !== drag.body || target.getAttribute("data-field-code") === "title") { return; }
    var box = target.getBoundingClientRect();
    drag.body.insertBefore(drag.row, event.clientY > box.top + box.height / 2 ? target.nextSibling : target);
  });

  function saveOrder(table, codes) {
    var data = new URLSearchParams();
    codes.forEach(function (code) { data.append("codes", code); });
    fetch(table.getAttribute("data-order-url"), {
      method: "POST", credentials: "same-origin", body: data,
      headers: {"X-CSRFToken": csrfToken(), "HX-Request": "true", "Content-Type": "application/x-www-form-urlencoded"}
    }).then(function (response) {
      if (response.status !== 204) { window.location.reload(); }
    }).catch(function () { window.location.reload(); });
  }

  function endDrag(cancelled) {
    if (!drag) { return; }
    var state = drag, table = state.row.closest("[data-lists-fields-grid]");
    drag = null;
    state.row.classList.remove("lists-dragging");
    var codes = fieldCodes(state.body);
    if (cancelled || !table || codes.join("\n") === state.before.join("\n")) {
      if (cancelled) { window.location.reload(); }
      return;
    }
    saveOrder(table, codes);
  }

  document.addEventListener("pointerup", function () { endDrag(false); });
  document.addEventListener("pointercancel", function () { endDrag(true); });

  // --- форма поля: «30 и 7» подставляются только при первом включении «срока»
  document.addEventListener("change", function (event) {
    var box = event.target;
    if (!box.matches || !box.matches("input[data-lists-deadline]") || !box.checked) { return; }
    var form = box.closest("form");
    var holder = form ? form.querySelector("[data-prop=thresholds]") : null;
    if (!holder || holder.getAttribute("data-deadline-was") !== "false") { return; }
    var inputs = holder.querySelectorAll("input[name=thresholds]");
    var empty = Array.prototype.every.call(inputs, function (item) { return item.value.trim() === ""; });
    if (empty && inputs.length >= 2) {
      inputs[0].value = "30";
      inputs[1].value = "7";
    }
    holder.setAttribute("data-deadline-was", "true");
  });

  // --- значения списка значений: строки до общего сохранения формы
  function newChoiceRow(title) {
    var row = document.createElement("li");
    row.setAttribute("data-choice-id", "");
    var id = document.createElement("input");
    id.type = "hidden"; id.name = "id"; id.value = "";
    var text = document.createElement("input");
    text.type = "text"; text.name = "title"; text.value = title; text.className = "form-control";
    text.setAttribute("aria-label", "Название значения");
    row.appendChild(id); row.appendChild(text); row.appendChild(removeButton("choice-remove"));
    return row;
  }

  function removeButton(action) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-outline-secondary btn-sm";
    button.setAttribute("data-action", action);
    button.textContent = "Убрать";
    return button;
  }

  function addChoice(section) {
    var input = section.querySelector("[data-lists-choice-title]");
    var list = section.querySelector("[data-lists-choice-list]");
    var title = input ? input.value.trim() : "";
    if (!title || !list) { return; }
    list.appendChild(newChoiceRow(title));
    input.value = "";
    input.focus();
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-lists-choices] button[data-action]") : null;
    if (!button) { return; }
    var section = button.closest("[data-lists-choices]");
    var action = button.getAttribute("data-action");
    if (action === "choice-add") {
      addChoice(section);
    } else if (action === "choice-remove") {
      button.closest("li").remove();
    } else if (action === "choice-restore") {
      var row = button.closest("li");
      var list = section.querySelector("[data-lists-choice-list]");
      Array.prototype.forEach.call(row.querySelectorAll("input"), function (item) { item.disabled = false; });
      var title = row.querySelector("input[name=title]");
      title.type = "text"; title.className = "form-control";
      var label = row.querySelector("span");
      if (label) { label.remove(); }
      row.removeAttribute("data-archived");
      button.replaceWith(removeButton("choice-remove"));
      list.appendChild(row);
    }
  });

  document.addEventListener("keydown", function (event) {
    var input = event.target;
    if (event.key === "Enter" && input.matches && input.matches("input[data-lists-choice-title]")) {
      event.preventDefault();
      addChoice(input.closest("[data-lists-choices]"));
    }
  });

  // --- вкладка «Права»: добавить и убрать субъект, подсказка подразделений
  var FIELD_NAMES = {read: "readers", edit: "editors"};

  function addSubject(block, value, name) {
    var level = block.getAttribute("data-lists-access");
    var list = block.querySelector("[data-lists-subjects]");
    var exists = Array.prototype.some.call(list.querySelectorAll("li[data-subject]"), function (item) {
      return item.getAttribute("data-subject") === value;
    });
    if (exists) { return; }
    var row = document.createElement("li");
    row.setAttribute("data-subject", value);
    var label = document.createElement("span");
    label.setAttribute("data-field", "name");
    label.textContent = name;
    var hidden = document.createElement("input");
    hidden.type = "hidden"; hidden.name = FIELD_NAMES[level] || "readers"; hidden.value = value;
    row.appendChild(label); row.appendChild(hidden); row.appendChild(removeButton("access-remove"));
    list.appendChild(row);
  }

  function pickHolder(block) {
    var holder = block.querySelector("ul[data-lists-pick]");
    if (!holder) {
      holder = document.createElement("ul");
      holder.className = "list-unstyled lists-pick";
      holder.setAttribute("data-lists-pick", "");
      var anchor = block.querySelector(".lists-access-add");
      anchor.parentNode.insertBefore(holder, anchor.nextSibling);
    }
    return holder;
  }

  var pickTimer = null, pickSerial = 0;

  document.addEventListener("input", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("[data-lists-access] input[data-lists-picker=units]")) { return; }
    var block = input.closest("[data-lists-access]");
    var query = input.value.trim();
    window.clearTimeout(pickTimer);
    var serial = ++pickSerial;
    if (!query) { pickHolder(block).replaceChildren(); return; }
    pickTimer = window.setTimeout(function () {
      fetch(input.getAttribute("data-pick-url") + "?q=" + encodeURIComponent(query), {
        credentials: "same-origin", headers: {"HX-Request": "true"}
      }).then(function (response) { return response.ok ? response.text() : ""; }).then(function (html) {
        if (serial !== pickSerial) { return; }
        var items = new DOMParser().parseFromString(html, "text/html").querySelectorAll("li[data-pick-id]");
        pickHolder(block).replaceChildren.apply(pickHolder(block), Array.prototype.map.call(items, function (item) {
          return document.importNode(item, true);
        }));
      }).catch(function () {});
    }, 120);
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target.closest) { return; }
    var remove = target.closest("[data-lists-access] button[data-action=access-remove]");
    if (remove) { remove.closest("li").remove(); return; }
    var add = target.closest("[data-lists-access] button[data-action=access-add]");
    if (add) {
      var block = add.closest("[data-lists-access]");
      var select = block.querySelector("select[data-lists-role-select]");
      if (select && select.value) {
        addSubject(block, "role:" + select.value, select.options[select.selectedIndex].textContent.trim());
        select.value = "";
      }
      return;
    }
    var pick = target.closest("[data-lists-access] ul[data-lists-pick] li[data-pick-id]");
    if (pick) {
      var holderBlock = pick.closest("[data-lists-access]");
      var title = pick.querySelector(".lists-pick-title");
      addSubject(holderBlock, "unit:" + pick.getAttribute("data-pick-id"), (title || pick).textContent.trim());
      pickSerial++;
      pick.parentNode.replaceChildren();
      var field = holderBlock.querySelector("input[data-lists-picker=units]");
      if (field) { field.value = ""; }
    }
  });

  /* === T-6216: таблица записей (столбцы, отметка строк) === */
})();
