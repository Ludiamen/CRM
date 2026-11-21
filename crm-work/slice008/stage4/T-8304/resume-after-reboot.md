# T-8304 — как продолжить после перезагрузки ноутбука

Состояние на 2026-11-21 09:26 (до перезагрузки):
- стенд наполнен для нагрузки: `messenger_chat` = 200, `messenger_message` = 50 000 (2 198 вложений);
- копия стенда до наполнения: `before-T8304-20261121-012255` (`crm-work/stand-backup/`);
- прогон нагрузки **остановлен** до остывания (решение владельца: порог 2,5 вместо 1,5); L1/L2 не выполнялись;
- `run-load-only.sh` не делает копию и сброс — только два круга нагрузки на готовом стенде.

После загрузки:
1. Проверить службы: `cd /home/gpgr/Документы/CRM && docker compose -p crm -f deploy/docker-compose.yml --profile dev ps`
   — `postgres`, `web`, `web-heavy`, `nginx`, `worker-notify` должны быть Up/healthy. Если нет —
   `docker compose -p crm -f deploy/docker-compose.yml --profile dev up -d`.
2. Проверить данные: `docker exec crm-postgres-1 psql -U postgres -d crm -tAc "select count(*) from messenger_message"` → 50000.
3. Запустить круги:
   `systemd-run --user --collect --unit=crm-T8304-load3-$(date +%Y%m%d-%H%M%S) --property=Type=oneshot --property=TimeoutStartSec=infinity --wait /home/gpgr/Документы/CRM/crm-work/slice008/stage4/T-8304/run-load-only.sh`
   (порог остывания 2,5 — решение владельца 2026-11-21; L1 `MessengerUser` 9 мин, L2 все классы 9 мин,
   `vmstat`/`mpstat`/`pidstat`, коды nginx, закрепление стенда на 0–2 и locust на 3).
4. Артефакты: `crm-work/slice008/stage4/T-8304/` (run-load.log, stats-L1/L2.txt, locust-L1/L2*.csv, codes-L1/L2.txt).

Если и с порогом 2,5 машина не остынет — прогон остановится (`exit 5`), стенд останется наполненным.