"""T-3130: хранение писем без заявки и чистка файлов письма (FR-221, FR-290, NFR-211). Сценарии спеки среза 003.

Имена кода среза 003 (`apps.servicedesk…`) импортируются внутри тестов: сбор проходит до появления кода.
Правила — tests/CONTRACT-003.md (§ 2.2 `InboundMail`, 3.4 `backdate`, 6.1 `Batch`, 6.15, 6.16, 6.24, 7.1–7.3,
12.6, 13.8, 14.3). Файл письма — `PROTECTED_ROOT/inbound/<id>.eml` (том во временной папке, фикстура
`protected_root`); возраст файла для чистки сирот задаётся `os.utime`, а не часами хоста (решение Opus B2-12).
Всё, что стирается после фиксации, идёт внутри `django_capture_on_commit_callbacks(execute=True)`.
"""
import os
import time
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.utils import timezone

from tests import support, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
DASH = "—"


# --- помощники только этого файла -------------------------------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        parts = [kid if isinstance(kid, str) else kid.text() for kid in self.kids]
        return " ".join(" ".join(parts).split())


class _Dom(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.cur = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def _inbound_row(dom: _Dom, inbound) -> _El:
    rows = [el for el in dom.root.walk()
            if el.tag == "tr" and "data-inbound" in el.attrs and el.attrs.get("data-id") == str(inbound.pk)]
    assert len(rows) == 1, f"строка письма #{inbound.pk} на странице: {len(rows)}"
    return rows[0]


def _cell(row: _El, name: str) -> str:
    cells = [el for el in row.walk() if el.attrs.get("data-cell") == name]
    assert len(cells) == 1, f"ячейка {name}: {len(cells)}"
    return cells[0].text()


def _raw_path(inbound) -> Path:
    from django.conf import settings
    return Path(settings.PROTECTED_ROOT) / "inbound" / f"{inbound.pk}.eml"


def _put_raw(inbound) -> Path:
    path = _raw_path(inbound)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Subject: test\r\n\r\ntext\r\n")
    return path


def _old(days: int, *, with_file: bool = True, **over):
    """Письмо без заявки, полученное `days` суток назад; файл письма — на диске (если нужен)."""
    over.setdefault("subject", "Тема письма")
    inbound = sd.make_inbound(**over)
    sd.backdate(inbound, "received_at", days=days)
    if with_file:
        _put_raw(inbound)
    return inbound


def _fresh(inbound):
    return model("servicedesk.InboundMail").objects.get(pk=inbound.pk)


def _age_file(path: Path, *, hours: int) -> None:
    moment = time.time() - hours * 3600
    os.utime(path, (moment, moment))


def _put_orphan(name: str, *, hours: int = 0) -> Path:
    """Файл в каталоге писем под данным именем; `hours` — сколько часов назад его изменили."""
    from django.conf import settings
    path = Path(settings.PROTECTED_ROOT) / "inbound" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"orphan")
    if hours:
        _age_file(path, hours=hours)
    return path


def _jobs(func: str):
    import django_rq
    return [job for job in django_rq.get_queue("maintenance").jobs if job.func_name == f"apps.servicedesk.tasks.{func}"]


def _manage_client():
    return support.logged_in(support.make_with_permissions("servicedesk.manage"))


# --- письма без заявки: чистка по сроку (FR-221) -----------------------------------------------------

def test_purge_inbound_rejected_auto_waiting_error_mail_cleared(protected_root, django_capture_on_commit_callbacks):
    """FR-221: письма без заявки с любым итогом (отклонённое, автоматическое, ждущее настройки, с ошибкой разбора) старше срока очищаются, итог остаётся, файлы стёрты."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    cases = [
        (Inbound.Outcome.REJECTED_DOMAIN, Inbound.Status.PROCESSED),
        (Inbound.Outcome.REJECTED_SELF, Inbound.Status.PROCESSED),
        (Inbound.Outcome.AUTO, Inbound.Status.PROCESSED),
        (Inbound.Outcome.WAITING_SETUP, Inbound.Status.WAITING_SETUP),
        (Inbound.Outcome.PARSE_ERROR, Inbound.Status.ERROR),
    ]
    mails = [_old(40, outcome=outcome, status=status) for outcome, status in cases]
    paths = [_raw_path(mail) for mail in mails]
    assert all(path.exists() for path in paths)

    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.purge_inbound()

    assert batch.done == len(cases)
    for mail, (outcome, _) in zip(mails, cases):
        row = _fresh(mail)
        assert row.raw_deleted is True, outcome
        assert (row.from_email, row.subject, row.message_id) == ("", "", ""), outcome
        assert row.outcome == outcome
    assert not any(path.exists() for path in paths)


def test_purge_inbound_file_sender_subject_message_id_cleared_result_kept(protected_root,
                                                                          django_capture_on_commit_callbacks):
    """FR-221: у очищенного письма пусты `from_email`, `subject`, `message_id`, `raw_deleted=True`, строка и итог остаются; файл стирается после фиксации, не раньше."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    mail = _old(35, outcome=Inbound.Outcome.REJECTED_DOMAIN, status=Inbound.Status.PROCESSED,
                from_email="sender.one@client.test", message_id="<one@client.test>")
    path = _raw_path(mail)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        retention.purge_inbound()
        assert path.exists(), "файл письма стёрт до фиксации транзакции"
    for callback in callbacks:
        callback()

    assert not path.exists()
    row = _fresh(mail)
    assert row.raw_deleted is True
    assert row.from_email == ""
    assert row.subject == ""
    assert row.message_id == ""
    assert row.outcome == Inbound.Outcome.REJECTED_DOMAIN
    assert row.ticket_id is None
    assert Inbound.objects.filter(pk=mail.pk).count() == 1


def test_purge_inbound_not_before_inbound_retention_days(protected_root, django_capture_on_commit_callbacks):
    """FR-221: письмо моложе срока `inbound_retention_days` не трогается; срок читается из настроек при каждом вызове."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    young = _old(29, outcome=Inbound.Outcome.AUTO, status=Inbound.Status.PROCESSED, from_email="young@client.test")
    older = _old(31, outcome=Inbound.Outcome.AUTO, status=Inbound.Status.PROCESSED, from_email="older@client.test")

    with django_capture_on_commit_callbacks(execute=True):
        first = retention.purge_inbound()

    assert first.done == 1
    assert _fresh(older).raw_deleted is True and _fresh(older).from_email == ""
    kept = _fresh(young)
    assert kept.raw_deleted is False and kept.from_email == "young@client.test" and kept.subject == "Тема письма"
    assert _raw_path(young).exists()
    assert not _raw_path(older).exists()

    sd.configure_servicedesk(inbound_retention_days=10)
    with django_capture_on_commit_callbacks(execute=True):
        second = retention.purge_inbound()

    assert second.done == 1
    assert _fresh(young).raw_deleted is True and _fresh(young).from_email == ""
    assert not _raw_path(young).exists()


def test_purge_inbound_mail_with_ticket_not_touched(protected_root, django_capture_on_commit_callbacks):
    """FR-221: письмо, по которому создана заявка или которое дописано в неё, не трогается (его срок — срок заявки, FR-290); письмо без заявки рядом очищено."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    ticket = sd.make_ticket()
    with_ticket = _old(60, outcome=Inbound.Outcome.CREATED, status=Inbound.Status.PROCESSED,
                       from_email="owner@client.test", ticket=ticket)
    without = _old(60, outcome=Inbound.Outcome.AUTO, status=Inbound.Status.PROCESSED, from_email="auto@client.test")

    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.purge_inbound()

    assert batch.done == 1
    row = _fresh(with_ticket)
    assert row.raw_deleted is False
    assert row.from_email == "owner@client.test"
    assert row.subject == "Тема письма"
    assert row.message_id == with_ticket.message_id
    assert row.ticket_id == ticket.pk
    assert _raw_path(with_ticket).exists()
    assert _fresh(without).raw_deleted is True and not _raw_path(without).exists()


def test_purge_inbound_batches_of_50(protected_root, django_capture_on_commit_callbacks):
    """FR-221: порция — 50 писем по возрастанию (`received_at`, `id`); задание `purge_inbound` ставит следующую в `maintenance` с `after` последнего письма, пока порция полная."""
    from apps.servicedesk import tasks
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    base = timezone.now() - timedelta(days=60)
    mails = [sd.make_inbound(outcome=Inbound.Outcome.AUTO, status=Inbound.Status.PROCESSED,
                             received_at=base + timedelta(seconds=n)) for n in range(101)]

    # Служба: полная порция — more=True, курсор — последнее письмо порции.
    with django_capture_on_commit_callbacks(execute=True):
        direct = retention.purge_inbound()
    assert direct.done == 50
    assert direct.more is True
    assert tuple(direct.last) == (mails[49].received_at, mails[49].pk)
    assert Inbound.objects.filter(raw_deleted=True).count() == 50
    assert not Inbound.objects.filter(pk__in=[mail.pk for mail in mails[:50]], raw_deleted=False).exists()

    # Задание: берёт следующие 50 (первые уже очищены) и ставит порцию с курсором.
    with django_capture_on_commit_callbacks(execute=True):
        tasks.purge_inbound()
    jobs = _jobs("purge_inbound")
    assert len(jobs) == 1
    assert tuple(jobs[0].kwargs["after"]) == (mails[99].received_at, mails[99].pk)
    assert jobs[0].timeout == 600
    assert Inbound.objects.filter(raw_deleted=True).count() == 100
    assert _fresh(mails[100]).raw_deleted is False

    with django_capture_on_commit_callbacks(execute=True):
        jobs[0].perform()
    assert Inbound.objects.filter(raw_deleted=True).count() == 101
    assert len(_jobs("purge_inbound")) == 1  # последняя порция неполная: новой нет


def test_waiting_mail_with_erased_file_not_parsed_again(protected_root, django_capture_on_commit_callbacks):
    """FR-221: ждущее настройки письмо со стёртым файлом разбору больше не подлежит: после настройки очереди заявка из него не создаётся, итог остаётся."""
    from apps.servicedesk.services import intake, retention
    Inbound = model("servicedesk.InboundMail")
    Ticket = model("servicedesk.Ticket")
    mail = _old(45, outcome=Inbound.Outcome.WAITING_SETUP, status=Inbound.Status.WAITING_SETUP,
                from_email="late@client.test")

    with django_capture_on_commit_callbacks(execute=True):
        retention.purge_inbound()
    assert not _raw_path(mail).exists()

    sd.configure_servicedesk(domains=["client.test"], default_queue=sd.make_queue())
    with django_capture_on_commit_callbacks(execute=True):
        result = intake.process(mail.pk)

    assert result is None
    assert Ticket.objects.count() == 0
    row = _fresh(mail)
    assert row.raw_deleted is True
    assert row.ticket_id is None
    assert row.outcome == Inbound.Outcome.WAITING_SETUP
    assert row.status == Inbound.Status.WAITING_SETUP


def test_inbound_list_shows_dash_for_erased_sender_and_subject(protected_root, django_capture_on_commit_callbacks):
    """FR-221: в списке «Входящие письма» у письма со стёртыми данными в ячейках отправителя и темы «—», итог виден; у нетронутого письма адрес и тема на месте."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    erased = _old(50, outcome=Inbound.Outcome.REJECTED_DOMAIN, status=Inbound.Status.PROCESSED,
                  from_email="gone@client.test", subject="Секретная тема")
    kept = sd.make_inbound(outcome=Inbound.Outcome.REJECTED_DOMAIN, status=Inbound.Status.PROCESSED,
                           from_email="stay@client.test", subject="Видимая тема")
    with django_capture_on_commit_callbacks(execute=True):
        retention.purge_inbound()

    response = _manage_client().get("/servicedesk/inbound/")

    assert response.status_code == 200
    dom = _Dom(response.content.decode())
    row = _inbound_row(dom, erased)
    assert row.attrs["data-outcome"] == Inbound.Outcome.REJECTED_DOMAIN
    assert _cell(row, "sender") == DASH
    assert _cell(row, "subject") == DASH
    assert "отклонено: чужой домен" in _cell(row, "outcome")
    other = _inbound_row(dom, kept)
    assert "stay@client.test" in _cell(other, "sender")
    assert "Видимая тема" in _cell(other, "subject")
    html = response.content.decode()
    assert "gone@client.test" not in html and "Секретная тема" not in html


# --- файлы писем без строки (FR-290) -----------------------------------------------------------------

def test_purge_orphan_files_without_row_erased(protected_root, django_capture_on_commit_callbacks):
    """FR-290: файл `<id>.eml` без строки `InboundMail` старше часа (по времени изменения файла) стирается; свежая сирота (моложе часа) остаётся (решение B2-12)."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    top = (Inbound.objects.order_by("-pk").values_list("pk", flat=True).first() or 0) + 1000
    old_orphan = _put_orphan(f"{top + 1}.eml", hours=2)
    fresh_orphan = _put_orphan(f"{top + 2}.eml")
    assert not Inbound.objects.filter(pk__in=[top + 1, top + 2]).exists()

    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.purge_orphan_files()

    assert batch.done == 1
    assert not old_orphan.exists()
    assert fresh_orphan.exists()

    # сирот больше `size`: порция, курсор `after` (имя последнего просмотренного), `more`/`last` (§ 6.24, решение Opus R-6-a-4)
    from django.conf import settings
    inbound_dir = Path(settings.PROTECTED_ROOT) / "inbound"

    def names():
        return sorted(p.name for p in inbound_dir.iterdir())

    for i in range(51):
        _put_orphan(f"{top + 100 + i}.eml", hours=2)
    listed = names()
    assert len(listed) == 52  # свежая сирота и 51 старая
    with django_capture_on_commit_callbacks(execute=True):
        first = retention.purge_orphan_files(size=50)
    assert first.more is True and first.last == listed[49]
    assert first.done == len([n for n in listed[:50] if n != fresh_orphan.name])
    with django_capture_on_commit_callbacks(execute=True):
        second = retention.purge_orphan_files(size=50, after=first.last)
    assert second.more is False and second.last == listed[51]
    assert second.done == len([n for n in listed[50:] if n != fresh_orphan.name])
    assert names() == [fresh_orphan.name]

    # задание ставит следующую порцию в `maintenance` с курсором `after` (§ 7.1)
    import django_rq
    from apps.servicedesk import tasks
    for i in range(51):
        _put_orphan(f"{top + 300 + i}.eml", hours=2)
    listed = names()
    assert len(listed) == 52
    queue = django_rq.get_queue("maintenance")
    before = len([j for j in queue.jobs if j.func_name == "apps.servicedesk.tasks.purge_orphan_files"])
    with django_capture_on_commit_callbacks(execute=True):
        tasks.purge_orphan_files()
    jobs = [j for j in queue.jobs if j.func_name == "apps.servicedesk.tasks.purge_orphan_files"]
    assert len(jobs) == before + 1
    assert jobs[-1].kwargs == {"after": listed[49]}
    with django_capture_on_commit_callbacks(execute=True):
        jobs[-1].perform()
    assert names() == [fresh_orphan.name]
    assert len([j for j in queue.jobs if j.func_name == "apps.servicedesk.tasks.purge_orphan_files"]) == before + 1


def test_purge_orphan_files_of_raw_deleted_rows_erased(protected_root, django_capture_on_commit_callbacks):
    """FR-290: файл письма, у строки которого `raw_deleted=True`, стирается, если он старше часа; строка остаётся."""
    from apps.servicedesk.services import retention
    Inbound = model("servicedesk.InboundMail")
    mail = sd.make_inbound(raw_deleted=True, from_email="", subject="", message_id="",
                           outcome=Inbound.Outcome.AUTO, status=Inbound.Status.PROCESSED)
    leftover = _put_raw(mail)
    _age_file(leftover, hours=2)

    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.purge_orphan_files()

    assert batch.done == 1
    assert not leftover.exists()
    assert Inbound.objects.filter(pk=mail.pk).exists()


def test_purge_orphan_files_keeps_files_with_row(protected_root, django_capture_on_commit_callbacks):
    """FR-290: файл письма с живой строкой (`raw_deleted=False`) и файлы с прочими именами не трогаются, даже старые."""
    from apps.servicedesk.services import retention
    live = sd.make_inbound()
    live_path = _put_raw(live)
    _age_file(live_path, hours=5)
    other = _put_orphan("notes.txt", hours=5)

    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.purge_orphan_files()

    assert batch.done == 0
    assert live_path.read_bytes() == b"Subject: test\r\n\r\ntext\r\n"
    assert other.exists()


# --- запись заявителя (NFR-211) ----------------------------------------------------------------------

def test_requester_record_stores_only_address_name_unit():
    """NFR-211: запись заявителя хранит только адрес, ФИО и подразделение (плюс номер, отметку происхождения и служебные отметки времени); других полей с данными нет."""
    Requester = model("servicedesk.Requester")
    names = {field.name for field in Requester._meta.concrete_fields}
    assert {"email", "full_name", "client_unit"} <= names
    assert names <= {"id", "email", "full_name", "client_unit", "origin", "created_at", "updated_at"}, names
    assert not [field.name for field in Requester._meta.get_fields() if field.many_to_many]
