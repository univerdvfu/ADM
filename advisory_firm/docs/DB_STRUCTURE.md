# Структура БД: как на слайдах и как исправлено

Три хранилища из «Биржа (2).pptx», слайд 2: PostgreSQL, ClickHouse, MinIO. Оркестрация — Airflow (слайд 5).
Kafka не ставили (см. RECOMMENDATIONS.md).

## PostgreSQL (слайд 6) — реляционные данные

| Таблица | Слайд | Что изменено |
|---|---|---|
| `issuers` | да | без изменений по сути |
| `instruments` | да | `nominal_value NUMERIC(20,8)` (было 20,4); `currency CHAR(4)` (было 3); `contract_term` fixed/perpetual и `exercise_style` american/european вместо одного `instrument_type`; `CHECK` на дату погашения |
| `tickers` | нет | новый объект: `ticker_id` PK, `ticker` UNIQUE, ссылка на инструмент |
| `trading_sessions` | да | без изменений по сути |
| `session_instruments` | нет | M:N «инструмент допущен к сессии»: PK `(session_id, ticker_id)`, лот, шаг цены |
| `brokers` | да | оставлена как реляционная |
| `customers` | нет | заказчик только через брокера (`broker_id NOT NULL`) |
| `owner_accounts` | нет | отдельный обязательный аккаунт владельца, `ticker_id NOT NULL`; пара (заказчик, брокер) проверяется составным ключом |
| `client_requests` | вместо `orders` | поручение с ключом `(session_id, ticker_id)` на допуск |
| `ingest_jobs`, `quarantine` | сл. 2 | задания загрузки и карантин (только коды правил) |
| `advisory_clients` | нет | клиент фирмы: риск-профиль, горизонт, лимит доли позиции |
| `positions` | нет | портфель клиента |
| `corporate_events` | сл. 2 | дивиденды и сплиты |
| `recommendations` | нет | журнал рекомендаций, менять и удалять нельзя (триггер) |
| `recommendation_status_events` | нет | статусы draft → approved → published, только добавление |

Убрано как не относящееся к консультированию: `orders`, `surveillance_cases`, `system_users`.

## ClickHouse (слайд 7) — аналитика

| Таблица | Слайд | Что изменено |
|---|---|---|
| `ref_sessions`, `ref_session_instruments` | `dim_sessions`, `dim_instruments` | не реплика, а отдельная выгрузка по белому списку; номинал `Decimal(20,8)`, валюта `FixedString(4)` |
| `market_trades` | `fact_trades` | без `broker_id` и `order_id`; ключ `source_id + event_id`; ссылка `ticker_id + session_id` |
| `market_quotes` | `fact_quotes` | то же |
| `agg_ohlcv_1m` | да | ключ свечи `ticker_id + session_id + minute` |
| `daily_bars` | нет | дневные бары: основной ряд для консультирования |
| `signals`, `recommendations` | нет | прежняя версия; рекомендации теперь в PostgreSQL (кандидат на удаление) |
| `ingest_batches`, `ingest_rejects`, `audit_log` | сл. 2 | журналы |

Убрано: `dim_brokers`, `fact_order_events`, `fact_alerts`. ID участников, клиентов и брокеров в ClickHouse нет.

## MinIO (слайд 2)
Бакет `raw-market`: сырые ответы API Мосбиржи и пакеты сделок. Значения полей с ID участников заменяются на `***`.

## Airflow (слайд 5)
DAG `advisory_pipeline`, по будням в 19:00: `init → fetch → load → check → recommend`.
