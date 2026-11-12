"""T-7260/R1: новые загрузки сохраняются при отказе правки, чужие файлы не раскрываются."""
from collections import defaultdict

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support, support_feed as fd
from tests.support import HX
from tests.test_feed_edit import _plain_post, _saved, q, tree

pytestmark = pytest.mark.django_db


def _upload(session, post, name):
    response = session.client.post('/feed/files/', {
        'scope': 'post', 'post': post.pk,
        'file': SimpleUploadedFile(name, b'Synthetic attachment\n', content_type='text/plain'),
    }, **HX)
    assert response.status_code == 200
    pill, = q(tree(response), data_feed_file=True)
    return support.model('feed.FeedFile').objects.get(pk=pill.attrs['data-feed-file'])


def _returned_form_data(form):
    """Успешные controls формы; submit-кнопку выбирает сам тест."""
    data = defaultdict(list)
    for node in q(form, 'input'):
        name = node.attrs.get('name')
        if not name or 'disabled' in node.attrs:
            continue
        kind = node.attrs.get('type', 'text')
        if kind in ('radio', 'checkbox') and 'checked' not in node.attrs:
            continue
        if kind not in ('submit', 'button', 'file'):
            data[name].append(node.attrs.get('value', ''))
    for node in q(form, 'textarea'):
        data[node.attrs['name']] = [node.text()]
    return dict(data)


@pytest.mark.parametrize('hx', [False, True])
@pytest.mark.parametrize('kind', ['invalid', 'pdn'])
def test_uploaded_file_survives_edit_refusal_and_returned_form_retry(protected_root, hx, kind):
    author, _, post = _plain_post()
    uploaded = _upload(author, post, 'Новая схема.txt')
    assert (protected_root / 'incoming' / str(uploaded.file_id)).is_file()
    url = f'/feed/{post.pk}/edit/'
    raw_text = 'я' * 10001 if kind == 'invalid' else f'Свяжитесь: {fd.email_of()}'
    response = author.client.post(url, {
        'text': raw_text, 'to': _saved(post), 'files': [str(uploaded.pk), str(uploaded.pk)],
    }, **(HX if hx else {}))
    assert response.status_code == 200
    root = tree(response)
    form, = q(root, 'form', data_form='feed-post-edit')
    assert bool(q(root, 'html')) is (not hx)
    assert q(form, 'textarea', name='text')[0].text() == raw_text
    pill, = q(form, data_feed_file=str(uploaded.pk))
    assert uploaded.name in pill.text()
    hidden, = q(pill, 'input', type='hidden', name='files', value=str(uploaded.pk))
    assert hidden
    assert q(pill, 'button', data_action='file-remove')
    if kind == 'invalid':
        assert q(form, data_error='text', data_code='too_long')
    else:
        assert q(form, 'button', name='pdn_confirmed', value='1')
    uploaded.refresh_from_db()
    post.refresh_from_db()
    assert uploaded.post_id is None
    assert post.text == 'Старый текст'
    data = _returned_form_data(form)
    if kind == 'invalid':
        data['text'] = ['Исправленный текст']
    else:
        data['pdn_confirmed'] = ['1']
    retry = author.client.post(url, data, **(HX if hx else {}))
    assert retry.status_code == (200 if hx else 302)
    if hx:
        assert q(tree(retry), 'article', id=f'feed-post-{post.pk}')
    else:
        assert retry['Location'] == f'/feed/{post.pk}/'
    uploaded.refresh_from_db()
    post.refresh_from_db()
    assert uploaded.post_id == post.pk
    assert uploaded.comment_id is None
    assert post.text == data['text'][0]


@pytest.mark.parametrize('hx', [False, True])
@pytest.mark.parametrize('bad_kind', ['foreign', 'attached_elsewhere', 'missing'])
def test_edit_refusal_restores_only_owned_unbound_files_and_keeps_bind_validation(
        protected_root, hx, bad_kind):
    author, other, post = _plain_post()
    uploaded = _upload(author, post, 'Допустимое вложение.txt')
    forbidden = None
    if bad_kind == 'foreign':
        other_post = fd.make_post(other.user, to=(other.user,), text='Другая запись')
        forbidden = _upload(other, other_post, 'Чужое закрытое вложение.txt')
    elif bad_kind == 'attached_elsewhere':
        other_post = fd.make_post(author.user, to=(author.user,), text='Другая запись')
        forbidden = _upload(author, other_post, 'Уже прикреплённое вложение.txt')
        bound = author.client.post(f'/feed/{other_post.pk}/edit/', {
            'text': other_post.text, 'to': _saved(other_post), 'files': [str(forbidden.pk)],
        })
        assert bound.status_code == 302
        forbidden.refresh_from_db()
        assert forbidden.post_id == other_post.pk
    bad_id = str(forbidden.pk) if forbidden else '999999999'
    url = f'/feed/{post.pk}/edit/'
    # И обычный, и подтверждённый POST обязаны пройти прежнюю server-side bind-проверку.
    for confirmed in [False, True]:
        response = author.client.post(url, {
            'text': 'Правка с подставленным файлом', 'to': _saved(post),
            'files': [str(uploaded.pk), bad_id], 'pdn_confirmed': '1' if confirmed else '',
        }, **(HX if hx else {}))
        assert response.status_code == 200
        root = tree(response)
        form, = q(root, 'form', data_form='feed-post-edit')
        assert q(form, data_error='files', data_code='file_missing')
        assert [node.attrs['value'] for node in q(form, 'input', name='files')] == [str(uploaded.pk)]
        assert not q(form, data_feed_file=bad_id)
        if forbidden:
            assert forbidden.name not in root.text()
        uploaded.refresh_from_db()
        post.refresh_from_db()
        assert uploaded.post_id is None
        assert post.text == 'Старый текст'
