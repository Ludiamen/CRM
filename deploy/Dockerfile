# Образы портала ИТ-отдела (PLAN-001, «Где живёт код», «Запуск»).
# Контекст сборки — корень репозитория (compose: context "..").
#
#   app    — web, worker и scheduler: один образ, роль задаёт команда compose;
#   nginx  — nginx портала со статикой, собранной в образе app.
#
# Секретов в образе нет: всё читается из окружения при запуске (deploy/.env).

FROM python:3.12-slim-bookworm AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10

# Код живёт в /app/backend: настройки считают STATIC_ROOT, MEDIA_ROOT от BASE_DIR.parent
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin portal \
    && mkdir -p /app/backend /app/staticfiles /app/media /app/protected \
    && chown portal:portal /app/media /app/protected
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY deploy/entrypoint.sh deploy/healthcheck.py /app/
RUN chmod 755 /app/entrypoint.sh

# collectstatic при сборке (staticfiles лежит в образе и копируется в образ nginx).
# Значения ниже — только чтобы настройки поднялись при сборке; в запущенный
# контейнер они не попадают, настоящие приходят из окружения.
RUN DJANGO_SECRET_KEY=collectstatic-only \
    FIELD_ENCRYPTION_KEYS=collectstatic-only \
    BACKUP_CODE_PEPPER=collectstatic-only \
    PORTAL_URL=https://127.0.0.1 \
    DATABASE_URL=postgresql://none@none/none \
    VALKEY_URL=redis://none:6379/0 \
    SMTP_HOST=none SMTP_PORT=25 SMTP_FROM=none@none \
    python manage.py collectstatic --noinput \
    && chmod -R a+rX /app/staticfiles

USER portal
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# web: ASGI-сервер gunicorn с классом из пакета uvicorn-worker; управляющий сокет gunicornc
# (gunicorn 25.1+, по умолчанию $HOME/.gunicorn) не нужен — выключен
CMD ["gunicorn", "config.asgi:application", "--bind", "0.0.0.0:8000", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--workers", "4", "--timeout", "60", "--graceful-timeout", "30", \
     "--keep-alive", "30", "--error-logfile", "-", "--no-control-socket"]


FROM nginx:1.27-alpine AS nginx
# Статику отдаёт nginx (location /static/); конфигурация и сертификаты монтируются
COPY --from=app /app/staticfiles /srv/static
