#!/bin/sh
# Роли базы портала (PLAN-001, «Роли базы данных»). Запускается образом postgres
# один раз, при создании пустого каталога данных, под суперпользователем.
# Пароли — только из окружения контейнера (CRM_OWNER_PASSWORD, CRM_APP_PASSWORD),
# в файле их нет и в командную строку они не попадают (psql \getenv).
#
#   crm_owner — владелец базы и всех её таблиц: под ним идут миграции;
#               может создавать базы (для тестовой базы pytest);
#   crm_app   — роль портала: ничем не владеет, на таблицы получает только
#               SELECT/INSERT/UPDATE/DELETE, на последовательности — USAGE
#               (через ALTER DEFAULT PRIVILEGES FOR ROLE crm_owner).
#
# Права по умолчанию задаются и в template1: тестовая база создаётся из него,
# и таблицы в ней тоже достаются crm_app по тем же правилам.
set -eu

: "${CRM_OWNER_PASSWORD:?не задан CRM_OWNER_PASSWORD}"
: "${CRM_APP_PASSWORD:?не задан CRM_APP_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv owner_pw CRM_OWNER_PASSWORD
\getenv app_pw CRM_APP_PASSWORD
\getenv dbname POSTGRES_DB

-- пароль подставляется как литерал через format(%L) и \gexec: значение не лежит в файле
SELECT format('CREATE ROLE crm_owner LOGIN CREATEDB PASSWORD %L', :'owner_pw') \gexec
SELECT format('CREATE ROLE crm_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_pw') \gexec

ALTER DATABASE :"dbname" OWNER TO crm_owner;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO crm_app;

\connect template1
ALTER DEFAULT PRIVILEGES FOR ROLE crm_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO crm_app;
ALTER DEFAULT PRIVILEGES FOR ROLE crm_owner IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO crm_app;

\connect :dbname
ALTER SCHEMA public OWNER TO crm_owner;
ALTER DEFAULT PRIVILEGES FOR ROLE crm_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO crm_app;
ALTER DEFAULT PRIVILEGES FOR ROLE crm_owner IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO crm_app;
SQL
