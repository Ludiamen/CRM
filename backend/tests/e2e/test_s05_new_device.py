"""T-142: сценарий 5 — вход с нового устройства: письмо (FR-040, FR-041, FR-052)."""
import re
import time


from tests.e2e import helpers


def test_s05_new_browser_context_triggers_mail_first_login_does_not(employee, mailpit, new_context):
    """Сценарий 5, п. 1-4: первый вход (активация) письма не даёт; вход из нового контекста — это новое
    устройство, письмо приходит за минуту, с браузером, платформой, адресом и без ссылок; повторный
    вход из того же контекста письма не даёт, а запись в истории появляется."""
    acc = employee()
    # п. 3: после активации письма о новом устройстве нет
    assert helpers.no_mail(mailpit, acc.email, "new_device", wait=2.0)

    # п. 1: новый контекст = новое устройство
    seen = helpers.mail_ids(mailpit, acc.email)
    other = new_context().new_page()
    started = time.monotonic()
    helpers.sign_in(other, acc)
    mail = helpers.wait_mail(mailpit, acc.email, "new_device", seen=seen, timeout=60)
    assert time.monotonic() - started < 60, "письмо о новом устройстве позже минуты"
    text = mail["Text"]
    assert re.search(r"[А-Яа-я]", mail["Subject"] + text)
    assert re.search(r"\d{2}:\d{2}", text), "в письме нет времени входа"
    assert re.search(r"\d{1,3}(\.\d{1,3}){3}|[0-9a-f:]{3,}", text), "в письме нет адреса"
    assert "http://" not in text and "https://" not in text, "в письме о новом устройстве есть ссылка"
    other.goto("/me/security/devices/")
    assert other.locator("[data-device-id]").count() == 2

    # п. 2: тот же контекст, выход и вход — письма нет, в истории запись есть
    seen = helpers.mail_ids(mailpit, acc.email)
    helpers.sign_out(other)
    helpers.sign_in(other, acc)
    assert helpers.no_mail(mailpit, acc.email, "new_device", seen=seen, wait=4.0)
    other.goto("/me/security/history/")
    assert other.locator("[data-history-row][data-result=success]").count() >= 2
