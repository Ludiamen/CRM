/* Разделы администратора (T-244, T-248): копирование ссылки приглашения и согласование формы фильтра с
   результатом, который подгрузил HTMX. Inline-кода на страницах нет (CSP): логика — здесь и в Alpine.data(). */
document.addEventListener('alpine:init', function () {
  Alpine.data('copyLink', function () {
    return {
      copied: false,
      failed: false,
      copy: function () {
        var self = this;
        var text = this.$refs.link.textContent.trim();
        var done = function () {
          self.copied = true;
          self.failed = false;
          window.setTimeout(function () { self.copied = false; }, 2500);
        };
        var fail = function () {
          /* без доступа к буферу обмена: выделяем ссылку, чтобы её можно было скопировать вручную */
          self.failed = true;
          var range = document.createRange();
          range.selectNodeContents(self.$refs.link);
          var selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, fail);
        } else {
          fail();
        }
      },
      get label() {
        if (this.failed) {
          return 'Ссылка выделена: нажмите Ctrl+C';
        }
        return this.copied ? 'Скопировано' : 'Копировать ссылку';
      }
    };
  });
});

/* После подгрузки сетки сервер сообщает, какие условия применены (`data-sync` — JSON): выпадающие списки и
   скрытые поля формы фильтра приводятся к ним, чтобы форма и таблица не расходились. Сама форма не заменяется. */
document.addEventListener('htmx:afterSwap', function (event) {
  var holder = event.detail && event.detail.target && event.detail.target.querySelector('[data-sync-form]');
  if (!holder) {
    return;
  }
  var form = document.getElementById(holder.getAttribute('data-sync-form'));
  var values;
  try {
    values = JSON.parse(holder.getAttribute('data-sync') || '{}');
  } catch (error) {
    return;
  }
  if (!form) {
    return;
  }
  Object.keys(values).forEach(function (name) {
    var field = form.elements[name];
    if (field && field.value !== String(values[name])) {
      field.value = values[name];
    }
  });
});
