// Сервис-воркер Web Push портала: показ уведомления по нагрузке и открытие ссылки того же источника.
self.addEventListener("push", function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = {};
  }
  var title = data.title || "Уведомление";
  event.waitUntil(self.registration.showNotification(title, {tag: data.tag || "", data: {url: data.url || "/"}}));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = "/";
  try {
    var url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
    if (url.origin === self.location.origin) {
      target = url.pathname + url.search + url.hash;
    }
  } catch (error) {
    target = "/";
  }
  event.waitUntil(self.clients.openWindow(target));
});
