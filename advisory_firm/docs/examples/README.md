# Примеры JSON для `POST /api/ingest`

Файлы можно отправлять как есть. Сделки идут в отдельную торговую сессию 20990103 (SBER, 10:00–18:50), реальные данные не затрагиваются.
Те же записи при повторной отправке будут **дублями**: это защита от повторов, а не ошибка. Чтобы начать заново: `POST /api/ingest/reset`.

| Файл | Что показывает |
|---|---|
| `1_clean.json` | 8 нормальных сделок: все принимаются |
| `2_forbidden_ids.json` | записи с `user_id`, `account_id`, `broker_id` и лишним полем: отклоняются |
| `3_outside_hours.json` | сделки до открытия, на границах 10:00 и 18:50, после окончания и ночью |
| `4_duplicates.json` | повторы одного `event_id` |
| `5_bad_values.json` | отрицательная и нулевая цена, текст вместо числа, лишние знаки, нулевое и дробное количество, мусорное время |
| `6_unknown.json` | неизвестные тикер, сессия, источник |
| `7_iss_format.json` | таблица `trades` в формате ISS Мосбиржи (поле `BUYSELL` не переносится) |

```bash
# без записи в базу: только как загрузчик разберёт пакет
curl -u advisory:ПАРОЛЬ -X POST -d @docs/examples/3_outside_hours.json "http://10.50.16.246/api/ingest?dry=1"

# записать в базу и пересчитать свечи; в ответе: вердикт по каждой записи, что изменилось в базах, карантин, свечи
curl -u advisory:ПАРОЛЬ -X POST -d @docs/examples/1_clean.json "http://10.50.16.246/api/ingest?candles=1"

# закрыть сессию (дальше все сделки отклоняются: session_closed) и открыть заново
curl -u advisory:ПАРОЛЬ -X POST "http://10.50.16.246/api/ingest/session?status=closed"
curl -u advisory:ПАРОЛЬ -X POST "http://10.50.16.246/api/ingest/session?status=open"

# очистить сделки и свечи этой сессии
curl -u advisory:ПАРОЛЬ -X POST "http://10.50.16.246/api/ingest/reset"
```
