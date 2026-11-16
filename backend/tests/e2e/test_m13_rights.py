"""T-8143: сценарий 13 — неприкосновенность переписки (FR-643, FR-668, FR-669).

SPEC-008, сценарий 13: администратор портала не читает чужие диалоги и не удаляет чужие сообщения — чужой чат для
него как несуществующий, ссылка на файл чужого чата не работает; уволенный в чатах не участвует. Пункты приёмки:
1. администратор открывает чужой личный диалог по прямому адресу — ответ как у несуществующего чата;
2. администратор ищет содержимое чужого диалога — в выдаче его нет;
3. посторонний открывает файл чужого чата — ответ как у несуществующего файла;
4. уволенный сотрудник пытается открыть чат — доступа нет, вход в портал закрыт.

Источники: CONTRACT-008.md § 6 (V1, V2, V3, V6, V8, V9, V13 — администратор проходит тот же `get_chat`; чужой
личный диалог — 404), § 9 (видимость в SQL поставщика поиска), § 10.1 («чужой, несуществующий и удалённый чат,
его сообщение, файл и эскиз отвечают одинаково — 404 обычной страницы „Не найдено“»; не вошедшему — 302 на
`/login/?next=<путь>`), § 10.2 (адреса беседы, истории, отправки, правки, удаления, оригинала и эскиза файла),
§ 12.1–12.6 (`[data-messenger-page]`, `#messenger-list [data-chat-id]`, `section[data-search-group="messenger"]`,
`[data-messenger-file]`), § 13.1 («Не найдено»), § 14.3 (помощники `helpers_messenger`); задачи — T-8143, T-8130;
план — «Права и неприкосновенность», «Проход в браузере».

Решения файла:
- «ответ как у несуществующего» проверяется сравнением в пределах одного клиента (`_like_missing_get`,
  `_like_missing_post`): тот же статус 404, тот же `<title>`, те же `<h1>`, что у `/messenger/chats/<MISSING>/…`
  и `/messenger/files/<MISSING>/…`, а не только код ответа: отказ не должен раскрывать ни чат, ни переписку;
- люди круга — `helpers_messenger.messenger_cast` один раз на круг браузера (фикстура `cast`; девять учёток через
  интерфейс на каждый тест — часы прохода). Чужие сообщения и файлы пишутся в личный диалог `writer` ↔ `peer`,
  администратор — `cast.admin` (роль «Администратор портала»), посторонний у файла — тот же администратор
  (FR-669: правило одно для всех, V13);
- п. 4 не может опереться на `cast.dismissed`: он создан без активации, и его отказ во входе объяснялся бы
  непринятым приглашением, а не увольнением. Поэтому тест заводит своего сотрудника (`employee`), даёт ему сессию
  и личный диалог, а затем увольняет из карточки и проверяет закрытие сессии и отказ входа (правило
  `test_f01_publish`: увольняющий тест заводит своих людей и общий круг не меняет); увольнение — локальный
  `_dismiss` (образец `test_o07_dismiss`), потому что в `helpers_messenger` он приватный;
- тексты сообщений — уникальное слово из латинских букв на тест (`_word()`), поэтому «слова нет в выдаче» и
  «слова нет в ответе 404» проверяются по нему; данные стенда между тестами не сбрасываются;
- ожидания — `expect`; прямые запросы — `helpers_org.direct_get`/`direct_post` (статус без перехода по редиректам,
  CSRF/Origin как у формы); п. 3 ждёт «чистый» файл `helpers_messenger.wait_clean` (ClamAV стенда настоящий,
  NFR-704);
- пропусков (`skip`/`xfail`) в файле нет: единственный допустимый skip круга — прежний в `tests/e2e/conftest.py`
  (Edge или Яндекс Браузер не установлен). ПДн нет, секретов нет; почта и пароли — из `helpers` (`Account`).
"""
import re
import secrets
from urllib.parse import urlencode

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_messenger, helpers_notify, helpers_org

MISSING = 987_654_321                       # заведомо несуществующий чат, сообщение и файл
MISSING_TEXT = "Не найдено"                 # 404 обычной страницы (10.1, 13.1)
SEARCH_GROUP = 'section[data-search-group="messenger"]'
MISSING_FILE = f"/messenger/files/{MISSING}/"
MISSING_CHAT = f"/messenger/chats/{MISSING}/"
LOGIN_NEXT = re.compile(r"/login/\?next=")

_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_TAGS = re.compile(r"<[^>]+>")

_CASTS: dict = {}


# --- Люди круга (14.3) ----------------------------------------------------------------------------------------------

@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Люди и узлы сценариев (`helpers_messenger.messenger_cast`), один раз на круг браузера (образец m04, m07)."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        found = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
        _CASTS[stand_admin.email] = found
    return found


# --- Общие приёмы файла --------------------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово из латинских букв: цифры и русские окончания поиск разобрал бы иначе."""
    return "".join(secrets.choice("bcdfghklmnprstvz") for _ in range(10))


def _uid() -> str:
    return secrets.token_hex(3)


def _plain(html: str) -> str:
    """Текст ответа без разметки: в нём ищется «Не найдено» и текст переписки."""
    return " ".join(_TAGS.sub(" ", html).split())


def _title(html: str) -> str:
    found = _TITLE.search(html)
    return _plain(found.group(1)) if found else ""


def _headings(html: str) -> list:
    return [_plain(value) for value in _H1.findall(html)]


def _same_missing(path: str, got, other) -> None:
    """Ответ `got` не отличим от ответа того же вида у несуществующего адреса `other` (10.1: тот же 404)."""
    assert got.status == other.status == 404, (
        f"{path}: ответ {got.status}, у несуществующего адреса {other.status}")
    got_html, other_html = got.text(), other.text()
    assert _title(got_html) == _title(other_html), f"{path}: заголовок страницы отличается от несуществующего"
    assert _headings(got_html) == _headings(other_html), (
        f"{path}: содержимое отличается от ответа несуществующего адреса")
    assert MISSING_TEXT in _plain(got_html), f"{path}: ответ не страница «{MISSING_TEXT}»"


def _like_missing_get(page, real: str, missing: str) -> None:
    """GET чужого адреса отвечает как GET несуществующего."""
    _same_missing(real, helpers_org.direct_get(page, real), helpers_org.direct_get(page, missing))


def _like_missing_post(page, real: str, missing: str, data=None) -> None:
    """POST чужого адреса отвечает как POST несуществующего (пустая форма — тоже POST)."""
    _same_missing(real, helpers_org.direct_post(page, real, data), helpers_org.direct_post(page, missing, data))


def _list(context, account):
    """Страница списка `/messenger/` (12.1): `live=False` — «Общий чат» мог быть выключен соседним сценарием."""
    return helpers_messenger.open_messenger(context, account, live=False)


def _dialog(context, author, other) -> int:
    """Личный диалог `author` ↔ `other` (существующий или новый): `start_dialog` шлёт первое сообщение и оставляет
    страницу в беседе. Возвращает номер чата."""
    return helpers_messenger.start_dialog(_list(context, author), other)


def _search(context, account, word: str):
    """Страница результатов `/search/?q=<word>` (`[data-search-page]`, раздел 9): вкладка сотрудника."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto("/search/?" + urlencode({"q": word}))
    expect(page.locator("[data-search-page]")).to_be_visible()
    return page


def _dismiss(page, user_id) -> None:
    """Увольняет из карточки `/staff/<id>/` (образец `test_o07_dismiss`): диалог → подтверждение → отметка."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    expect(card).to_be_visible()
    card.locator('[data-action="dismiss"]').first.click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


# --- Тесты (по пунктам приёмки сценария 13) -----------------------------------------------------------------------

def test_m13_admin_gets_404_on_foreign_personal_dialog_like_missing(cast, new_context):
    """П. 1 (FR-669, V13): администратор портала не видит чужой личный диалог в списке и получает на него тот же
    ответ, что на несуществующий чат: беседа, история, отправка, правка и удаление чужого сообщения — 404; текст
    переписки не раскрыт, в чате ничего не изменилось, а свой диалог администратора открывается (контроль)."""
    c = cast
    word = _word()
    chat = _dialog(new_context(), c.writer, c.peer)
    author = helpers_messenger.open_chat(new_context(), c.writer, chat)
    message_id = helpers_messenger.write(author, f"Личное сообщение {word}")

    admin = _list(new_context(), c.admin)
    expect(admin.locator(f'#messenger-list [data-chat-id="{chat}"]')).to_have_count(0)

    # п. 1: беседа и история отвечают как у несуществующего чата (V2, V3)
    _like_missing_get(admin, f"/messenger/chats/{chat}/", MISSING_CHAT)
    _like_missing_get(admin, f"/messenger/chats/{chat}/messages/", f"{MISSING_CHAT}messages/")
    # п. 1: отправка, правка и удаление чужого сообщения — тот же ответ (V6; «не удаляет чужие сообщения»)
    _like_missing_post(admin, f"/messenger/chats/{chat}/messages/", f"{MISSING_CHAT}messages/",
                       {"text": f"Чужое сообщение {word}"})
    _like_missing_post(admin, f"/messenger/messages/{message_id}/edit/",
                       f"/messenger/messages/{MISSING}/edit/", {"text": f"Правка администратора {word}"})
    _like_missing_post(admin, f"/messenger/messages/{message_id}/delete/",
                       f"/messenger/messages/{MISSING}/delete/", {})

    # ответ 404 не раскрывает переписку, а чужое сообщение не изменилось и не удалилось
    assert word not in helpers_org.direct_get(admin, f"/messenger/chats/{chat}/").text(), (
        "ответ 404 раскрыл текст чужого диалога")
    html = helpers_org.direct_get(author, f"/messenger/chats/{chat}/").text()
    assert word in html and f'data-message-id="{message_id}"' in html, "чужое сообщение исчезло или изменилось"
    assert f"Чужое сообщение {word}" not in html, "администратор отправил сообщение в чужой чат"
    assert f"Правка администратора {word}" not in html, "администратор изменил чужое сообщение"

    # контроль: тот же фильтр не закрыл администратору его собственный диалог
    own = _dialog(new_context(), c.admin, c.writer)
    assert helpers_org.direct_get(admin, f"/messenger/chats/{own}/").status == 200, (
        "свой диалог администратора закрыт тем же правилом")


def test_m13_admin_does_not_find_foreign_dialog_content_by_search(cast, new_context):
    """П. 2 (FR-669, FR-668, V9): слово из чужого личного диалога участник находит (контроль), а администратор не
    находит ни в сквозном поиске (нет строки, нет слова в группе «Мессенджер»), ни поиском по списку чатов."""
    c = cast
    word = _word()
    chat = _dialog(new_context(), c.writer, c.peer)
    author = helpers_messenger.open_chat(new_context(), c.writer, chat)
    message_id = helpers_messenger.write(author, f"Тайна диалога {word}")

    # контроль: слово проиндексировано — участник находит своё сообщение строкой группы «Мессенджер»
    mine = _search(new_context(), c.writer, word)
    expect(mine.locator(f'{SEARCH_GROUP} a[href="/messenger/chats/{chat}/#m{message_id}"]')).to_be_visible()

    # п. 2: администратору чужой диалог в выдаче не показывается — ни строкой, ни текстом
    admin = _search(new_context(), c.admin, word)
    expect(admin.locator(f'[data-search-page] a[href*="/messenger/chats/{chat}/"]')).to_have_count(0)
    group = admin.locator(SEARCH_GROUP)
    if group.count():
        assert word not in group.inner_text(), "слово чужого диалога попало в группу «Мессенджер»"
    assert word not in admin.locator("[data-search-page]").inner_text(), "слово чужого диалога есть в выдаче"

    # п. 2: поиск по списку чатов по фамилии собеседника тоже не показывает чужой диалог администратору
    listed = _list(new_context(), c.admin)
    listed.goto("/messenger/list/?" + urlencode({"q": c.peer.full_name.split()[0]}))
    listed.wait_for_load_state()
    expect(listed.locator(f'#messenger-list [data-chat-id="{chat}"]')).to_have_count(0)


def test_m13_file_of_foreign_chat_answers_like_missing(cast, new_context, tmp_path):
    """П. 3 (FR-669, V8): файл из чужого чата участнику выдаётся (контроль), а постороннему оригинал и эскиз
    отвечают как несуществующий файл — 404 страницы «Не найдено», без `X-Accel-Redirect` и без имени файла."""
    c = cast
    chat = _dialog(new_context(), c.writer, c.peer)
    author = helpers_messenger.open_chat(new_context(), c.writer, chat)
    name = f"схема{_uid()}.png"
    path = tmp_path / name
    path.write_bytes(helpers.make_png(640, 480))
    file_id = helpers_messenger.upload(author, path)
    helpers_messenger.write(author, f"Файл диалога {_word()}")
    helpers_messenger.wait_clean(author, file_id)

    # контроль: участник чата получает свой файл (иначе 404 ниже ничего не доказывал бы)
    peer = helpers_messenger.open_chat(new_context(), c.peer, chat)
    got = helpers_org.direct_get(peer, f"/messenger/files/{file_id}/")
    assert got.status == 200, f"участник чата не получил файл своего чата: {got.status}"

    # п. 3: посторонний — как у несуществующего файла; ни выдачи, ни имени файла
    admin = _list(new_context(), c.admin)
    for suffix in ("", "thumb/"):
        response = helpers_org.direct_get(admin, f"/messenger/files/{file_id}/{suffix}")
        _same_missing(f"/messenger/files/{file_id}/{suffix}", response,
                      helpers_org.direct_get(admin, f"{MISSING_FILE}{suffix}"))
        assert "x-accel-redirect" not in response.headers, f"постороннему выдан файл чужого чата (/{suffix})"
        assert name not in response.text(), "ответ 404 раскрыл имя файла чужого чата"


def test_m13_dismissed_employee_cannot_enter_portal_or_open_chat(cast, admin_page, employee, new_context):
    """П. 4 (FR-643): пока сотрудник работает, его личный диалог открывается; после увольнения сессия закрыта —
    прямой адрес беседы ведёт на вход с `next`, а вход по верным данным отклонён без шага кода: уволенный в чаты
    не входит."""
    c = cast
    acc = employee()
    page = acc.page
    page.goto("/messenger/")
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    chat = helpers_messenger.start_dialog(page, c.peer)
    helpers_messenger.write(page, f"До увольнения {_word()}")
    # контроль: сотрудник работает — его беседа открывается
    assert helpers_org.direct_get(page, f"/messenger/chats/{chat}/").status == 200, (
        "беседа сотрудника не открывается ещё до увольнения")

    _dismiss(admin_page, acc.id)

    # п. 4: увольнение закрыло сессию — прямой адрес беседы отправляет на вход с next (10.1)
    refused = helpers_org.direct_get(page, f"/messenger/chats/{chat}/")
    assert refused.status == 302, f"уволенный остался в беседе: {refused.status}"
    location = refused.headers.get("location", "")
    assert "/login/" in location and "next=" in location, (
        f"уволенного отправили не на вход: {location!r}")

    # п. 4: вход в портал закрыт — пароль не пускает даже ко второму шагу
    fresh = new_context().new_page()
    helpers.fill_login(fresh, acc.email, acc.password)
    assert "/login/" in fresh.url, f"уволенного пустили в портал: {fresh.url}"
    assert fresh.locator("input[name=code]").count() == 0, "уволенного пустили к шагу кода"
    assert fresh.locator("#top-bar").count() == 0, "у уволенного открыт портал"
    assert helpers.alert_text(fresh).strip(), "у отказа во входе нет причины"

    # п. 4: и чат по-прежнему недоступен — без входа тот же адрес ведёт на вход
    fresh.goto(f"/messenger/chats/{chat}/")
    expect(fresh).to_have_url(LOGIN_NEXT)