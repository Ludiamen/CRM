"""T-7260/R2: недоверенные ID только при восстановлении формы; bind policy не меняется."""
import pytest

from tests import support_feed as fd
from tests.support import HX
from tests.test_feed_edit import _plain_post, _saved, q, tree
from tests.test_feed_edit_upload_retry_regressions import _upload

pytestmark = pytest.mark.django_db

BAD_IDS = [
    pytest.param('²', id='superscript'),
    pytest.param('9' * 4301, id='conversion-limit'),
    pytest.param('9223372036854775808', id='bigint-overflow'),
]


def _assert_safe_refusal(response, uploaded, foreign, raw_text, kind):
    assert response.status_code == 200
    root = tree(response)
    form, = q(root, 'form', data_form='feed-post-edit')
    assert q(form, 'textarea', name='text')[0].text() == raw_text
    assert [node.attrs['value'] for node in q(form, 'input', name='files')] == [str(uploaded.pk)]
    pill, = q(form, data_feed_file=str(uploaded.pk))
    assert uploaded.name in pill.text()
    assert not q(form, data_feed_file=str(foreign.pk))
    assert foreign.name not in root.text()
    if kind == 'invalid':
        assert q(form, data_error='text', data_code='too_long')
    else:
        assert q(form, 'button', name='pdn_confirmed', value='1')
    uploaded.refresh_from_db()
    assert uploaded.post_id is None


@pytest.mark.parametrize('hx', [False, True])
@pytest.mark.parametrize('kind', ['invalid', 'pdn_boundary'])
@pytest.mark.parametrize('bad_id', BAD_IDS)
def test_restore_uploads_ignores_malformed_ids_without_losing_valid_file(
        protected_root, monkeypatch, hx, kind, bad_id):
    author, other, post = _plain_post()
    uploaded = _upload(author, post, 'Допустимое вложение.txt')
    other_post = fd.make_post(other.user, to=(other.user,), text='Другая запись')
    foreign = _upload(other, other_post, 'Чужое невидимое вложение.txt')
    raw_text = 'я' * 10001 if kind == 'invalid' else f'Свяжитесь: {fd.email_of()}'
    if kind == 'pdn_boundary':
        # Изоляция восстановления после PdnFound: существующий services.posts._int_ids
        # раньше ПДн падает на superscript/4301 цифрах. Этот чужой scope не исправляем.
        from apps.feed.services.errors import PdnFound
        from apps.feed.views import posts as views

        def pdn_refusal(*args, **kwargs):
            raise PdnFound([fd.email_of()])

        monkeypatch.setattr(views.posts, 'edit', pdn_refusal)
    response = author.client.post(f'/feed/{post.pk}/edit/', {
        'text': raw_text, 'to': _saved(post),
        'files': [bad_id, str(uploaded.pk), str(foreign.pk)],
    }, **(HX if hx else {}))
    _assert_safe_refusal(response, uploaded, foreign, raw_text, kind)
    assert bool(q(tree(response), 'html')) is (not hx)
    post.refresh_from_db()
    assert post.text == 'Старый текст'


@pytest.mark.parametrize('hx', [False, True])
def test_real_pdn_overflow_and_foreign_ids_do_not_leak_before_confirmation(protected_root, hx):
    author, other, post = _plain_post()
    uploaded = _upload(author, post, 'Допустимое вложение.txt')
    other_post = fd.make_post(other.user, to=(other.user,), text='Другая запись')
    foreign = _upload(other, other_post, 'Чужое невидимое вложение.txt')
    url = f'/feed/{post.pk}/edit/'
    raw_text = f'Свяжитесь: {fd.email_of()}'
    fields = {'text': raw_text, 'to': _saved(post),
              'files': [str(uploaded.pk), str(foreign.pk), '9223372036854775808']}
    response = author.client.post(url, fields, **(HX if hx else {}))
    _assert_safe_refusal(response, uploaded, foreign, raw_text, 'pdn')
    # Отдельный настоящий forged confirmation без overflow доходит до прежнего bind.
    fields['files'] = [str(uploaded.pk), str(foreign.pk)]
    fields['pdn_confirmed'] = '1'
    refused = author.client.post(url, fields, **(HX if hx else {}))
    assert refused.status_code == 200
    assert q(tree(refused), data_error='files', data_code='file_missing')
    assert foreign.name not in tree(refused).text()
    uploaded.refresh_from_db()
    post.refresh_from_db()
    assert uploaded.post_id is None
    assert post.text == 'Старый текст'


@pytest.mark.parametrize(('values', 'expected'), [
    pytest.param(['9223372036854775807', '9223372036854775808'], [9223372036854775807], id='bigint-range'),
    pytest.param(['0', '-1', '+1', '', ' '], [], id='positive-only'),
    pytest.param(['1', '01', ' 1 ', '2'], [1, 2], id='normalization'),
    pytest.param(['²', '١', '9' * 4301, '3'], [3], id='ascii-bounded'),
])
def test_restored_upload_id_parser_is_bounded_before_integer_conversion(values, expected):
    from apps.feed.views import posts as views

    assert views.FeedFile._meta.pk.get_internal_type() == 'BigAutoField'
    assert views._restored_upload_ids(values) == expected
