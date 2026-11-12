"""Проверки изоляции форм упоминаний и устойчивости цели sync живой ленты."""

import re
import secrets
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect

from tests.e2e.helpers_feed import (
    POST_ALL, make_role, open_card, open_feed, pick_mention, publish, publish_request, wait_banner,
)


# Только наблюдение событий HTMX; соединение и ответы остаются настоящими.
_OBSERVE = r"""(() => {
  const state = window.__r3 = {acks: 0, errors: 0, wrapper: null};
  document.addEventListener('htmx:wsOpen', event => {
    if (event.target && event.target.id === 'feed-live' && event.detail.socketWrapper) {
      state.wrapper = event.detail.socketWrapper;
    }
  }, true);
  document.addEventListener('htmx:wsAfterMessage', event => {
    if (!event.target || event.target.id !== 'feed-live' ||
        !event.detail || typeof event.detail.message !== 'string') return;
    const parsed = new DOMParser().parseFromString(event.detail.message, 'text/html');
    if (parsed.getElementById('feed-synced')) state.acks++;
  }, true);
  for (const name of ['htmx:oobErrorNoTarget', 'htmx:targetError']) {
    document.addEventListener(name, () => { state.errors++; }, true);
  }
})()"""


def _context(new_context):
    context = new_context()
    context.add_init_script(_OBSERVE)
    return context


def _people(admin_page, employee):
    tag = secrets.token_hex(4)
    writer = employee(role=make_role(admin_page, [POST_ALL]), full_name=f"Автор{tag} Иван Иванович")
    first = employee(full_name=f"Первый{tag} Иван Иванович")
    second = employee(full_name=f"Второй{tag} Иван Иванович")
    return writer, first, second


def _form(page, post_id):
    return page.locator(f'#feed-post-{post_id} form[data-feed-comment-form]')


def _choose(page, form, person, prefix):
    area = form.locator('textarea[name="text"]')
    area.fill(prefix)
    area.press('End')
    pick_mention(page, area, person.full_name.split()[0], person.full_name)
    return prefix + '@' + person.full_name


def _same_text(form, text):
    # Булево сравнение не выводит содержимое поля при отказе.
    assert form.locator('textarea[name="text"]').evaluate('(el, value) => el.value === value', text), (
        'текст формы изменился или не соответствует выбранному упоминанию')


def _submit_comment(page, post_id, expected_id, other_id):
    form = _form(page, post_id)
    original = form.element_handle()
    assert original is not None, 'форма комментария отсутствует'
    path = f'/feed/{post_id}/comments/'
    with page.expect_response(lambda response: response.request.method == 'POST' and
                              urlsplit(response.url).path == path) as pending:
        form.locator('button[type="submit"]').click()
    response = pending.value
    assert response.status == 200, 'отправка комментария не вернула HTTP 200'
    fields = parse_qs(response.request.post_data or '', keep_blank_values=True)
    values = fields.get('text', [])
    assert len(values) == 1, 'в запросе ожидалось одно поле text'
    markers = re.findall(r'@\[([1-9]\d*)\]', values[0])
    assert markers == [str(expected_id)] and str(other_id) not in markers, (
        'неверное соответствие числовых маркеров в поле text')
    match = re.search(r'data-comment-id="([1-9]\d*)"', response.text())
    assert match is not None, 'ответ не содержит созданный комментарий'
    comment_id = int(match.group(1))
    page.wait_for_function('node => !node.isConnected', arg=original, timeout=15_000)
    expect(_form(page, post_id)).to_have_count(1)
    comment = page.locator(f'#c{comment_id}')
    expect(comment).to_be_visible()
    expect(comment.locator(f'[data-mention="{expected_id}"]')).to_have_count(1)
    expect(comment.locator(f'[data-mention="{other_id}"]')).to_have_count(0)
    return comment_id


def _initial_sync(page):
    expect(page.locator('#feed-live')).to_have_attribute('data-ws', 'open', timeout=20_000)
    page.wait_for_function('() => window.__r3 && window.__r3.acks >= 1 && window.__r3.wrapper', timeout=20_000)
    _targets(page)


def _targets(page):
    expect(page.locator('#feed-synced')).to_have_count(1)
    assert page.evaluate("""() => {
      const live = document.getElementById('feed-live');
      const target = document.getElementById('feed-synced');
      return !!live && !!target && !live.contains(target) && window.__r3.errors === 0;
    }"""), 'цель sync отсутствует, находится внутри feed-live или есть ошибка цели HTMX'


def _repeat_sync(page):
    before = page.evaluate('() => window.__r3.acks')
    page.evaluate("""() => {
      const live = document.getElementById('feed-live');
      const ids = Array.from(document.querySelectorAll('article[data-post-id]'))
        .map(node => Number(node.dataset.postId)).filter(Number.isSafeInteger);
      window.__r3.wrapper.send(JSON.stringify({sync: {ids, since: new Date().toISOString()}}));
    }""")
    page.wait_for_function('before => window.__r3.acks > before', arg=before, timeout=20_000)
    expect(page.locator('#feed-live')).to_have_attribute('data-ws', 'open')
    _targets(page)


def test_comment_mentions_are_independent_and_reinitialize_after_htmx_submit(admin_page, employee, new_context):
    writer, first, second = _people(admin_page, employee)
    page = open_feed(_context(new_context), writer)
    post1 = publish(page, 'Первая запись для проверки форм')
    post2 = publish(page, 'Вторая запись для проверки форм')
    form1, form2 = _form(page, post1), _form(page, post2)
    expect(form1).to_have_count(1)
    expect(form2).to_have_count(1)
    text1 = _choose(page, form1, first, 'Первый комментарий ')
    text2 = _choose(page, form2, second, 'Второй комментарий ')
    _same_text(form1, text1)
    _same_text(form2, text2)
    _submit_comment(page, post1, first.id, second.id)
    _same_text(_form(page, post2), text2)
    # После outerHTML новая форма инициализируется продуктом, а не тестом.
    _choose(page, _form(page, post1), first, 'Повторный комментарий ')
    _same_text(_form(page, post2), text2)
    _submit_comment(page, post1, first.id, second.id)
    _same_text(_form(page, post2), text2)
    _submit_comment(page, post2, second.id, first.id)
    print('r3 comment: forms=2 payloads=3 expected_markers=3 foreign_markers=0')


def test_home_sync_target_survives_repeated_ack_and_page_reload(admin_page, employee, new_context):
    writer, reader, _ = _people(admin_page, employee)
    page = open_feed(_context(new_context), reader)
    _initial_sync(page)
    _repeat_sync(page)
    writer_page = open_feed(new_context(), writer, live=False)
    ids = [publish_request(writer_page, kind='post', text=f'Проверка живой ленты {i}', to='all')
           for i in range(51)]
    assert len(set(ids)) == 51, 'ожидалось 51 различных опубликованных записей'
    wait_banner(page, 51, timeout=20_000)
    with page.expect_response(lambda response: response.request.method == 'GET' and
                              urlsplit(response.url).path == '/feed/new/') as pending:
        page.locator('[data-feed-new-load]').click()
    assert pending.value.status == 200, 'загрузка плашки не вернула HTTP 200'
    reload_link = page.locator('[data-feed-reload]')
    expect(reload_link).to_have_count(1, timeout=20_000)
    href = reload_link.get_attribute('href')
    assert href and urlsplit(href).path == '/', 'неверный адрес перезагрузки ленты'
    for attribute in ('hx-get', 'hx-target', 'hx-swap'):
        assert reload_link.get_attribute(attribute) is None, 'перезагрузка перехвачена HTMX'
    _targets(page)
    with page.expect_navigation(wait_until='domcontentloaded') as navigated:
        reload_link.click()
    response = navigated.value
    assert response is not None and response.status == 200, 'перезагрузка не вернула HTTP 200'
    assert response.request.is_navigation_request(), 'не выполнена навигация документа'
    assert response.request.all_headers().get('hx-request', '').lower() != 'true', 'получен HTMX-фрагмент'
    assert urlsplit(response.url).path == '/', 'открыта не главная лента'
    assert parse_qs(urlsplit(response.url).query) == parse_qs(urlsplit(href).query), 'фильтры не сохранены'
    expect(page.locator('[data-feed-page="home"]')).to_have_count(1)
    expect(page.locator('#feed-live')).to_have_count(1)
    expect(page.locator('[ws-connect]')).to_have_count(2)
    _initial_sync(page)
    _repeat_sync(page)
    print('r3 home: publications=51 document_reload=1 live_nodes=1 targets=1 ws_nodes=2 target_errors=0 new_page_sync_acks>=2')


def test_card_sync_target_survives_repeated_ack(admin_page, employee, new_context):
    writer, reader, _ = _people(admin_page, employee)
    writer_page = open_feed(new_context(), writer)
    post_id = publish(writer_page, 'Запись для проверки карточки')
    page = open_card(_context(new_context), reader, post_id)
    _initial_sync(page)
    _repeat_sync(page)
    print('r3 card: targets=1 target_errors=0 sync_acks>=2')
