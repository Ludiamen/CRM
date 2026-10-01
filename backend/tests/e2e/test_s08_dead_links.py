"""T-141: сценарий 8 — просроченная, использованная и выдуманная ссылка активации (FR-011, FR-012, FR-034)."""
import re
import secrets

from tests import factories
from tests.e2e import helpers


def _dead(page, link: str) -> str:
    """Открывает ссылку, ждёт ответ страницы; возвращает текст сообщения. Мастер не начался."""
    page.goto(link)
    page.wait_for_load_state("networkidle")
    assert "/activate/profile/" not in page.url, "мёртвая ссылка открыла мастер"
    return helpers.alert_text(page)


def test_s08_expired_used_wrong_links_same_message(admin_page, mailpit, new_context, portal_url):
    """Сценарий 8, п. 1-3: просроченная и выдуманная ссылки дают одно и то же сообщение («просрочена»,
    просьба к администратору); использованная — «уже использована» и предложение входа; мастер не
    открывается, пароль задать нельзя."""
    # просроченная: состарена в базе (72 часа в e2e не ждать)
    expired_email = factories.new_email("emp")
    helpers.create_employee(admin_page, expired_email)
    expired_link = helpers.link_in(helpers.wait_mail(mailpit, expired_email, "invitation"), "/activate/")
    helpers.age_activation_link(expired_email)
    expired = _dead(new_context().new_page(), expired_link)

    # выдуманная
    wrong = _dead(new_context().new_page(), f"{portal_url}activate/#{secrets.token_urlsafe(32)}")

    # использованная: активация завершена
    used_email = factories.new_email("emp")
    helpers.create_employee(admin_page, used_email)
    used_link = helpers.link_in(helpers.wait_mail(mailpit, used_email, "invitation"), "/activate/")
    helpers.walk_activation(new_context().new_page(), used_link, factories.new_password())
    page = new_context().new_page()
    used = _dead(page, used_link)

    assert "просроч" in expired.lower() and "администратор" in expired.lower()
    assert re.sub(r"\s+", " ", expired) == re.sub(r"\s+", " ", wrong), \
        "выдуманная ссылка говорит не то, что просроченная (подсказка о существовании записи)"
    assert "использован" in used.lower()
    assert page.locator('a[href="/login/"]').count(), "использованная ссылка не предлагает обычный вход"

    # пароль задать нельзя: страницы мастера без обмена кода закрыты
    after = new_context().new_page()
    after.goto("/activate/password/")
    assert "/activate/password/" not in after.url
