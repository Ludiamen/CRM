# Портал ИТ-отдела

Собственная система для ИТ-отдела по образцу «1С-Битрикс: Корпоративный
портал» (коробочная версия): сервис-деск для заявок работников общества и
рабочее пространство отдела. Около 100 учётных записей сотрудников ИТ;
заявители пишут без учётной записи — письмом или через открытую форму.

Стек: Django 5 + HTMX, PostgreSQL 17, Redis + RQ, Channels, Docker Compose
(ADR-0001). Разработка ведётся по SDD (ADR-0002, docs/sdd-process.md).

## Где что лежит

| Путь | Что |
|---|---|
| docs/constitution.md | принципы проекта (из docs/constitution.json) |
| docs/sdd-process.md | процесс: статусы, ворота, идентификаторы, модели |
| docs/decisions/ | архитектурные решения (ADR) |
| docs/requirements/ | исходные условия и требования ИТ-отдела |
| docs/reference/ | эталон — разбор Битрикс КП со ссылками на источники |
| docs/target/ | to-be: архитектура и нефункциональные требования |
| specs/ | срезы: spec → plan → tasks |
| templates/ | шаблоны документов |
| tools/ | ворота SDD и проверка секретов |

## Команды

```
python3 tools/sdd.py проверить                      # все документы, конституция, код, трассировка
python3 tools/sdd.py статус                         # таблица статусов
python3 tools/sdd.py на-проверку docs/constitution.md
python3 tools/sdd.py подписать docs/constitution.md --кто Максим   # только человек
python3 tools/sdd.py собрать-конституцию            # после правки constitution.json
python3 -m unittest discover -s tools -p "test_*.py"
sh tools/setup_git_hooks.sh                         # pre-commit против секретов (в каждом клоне)
```
