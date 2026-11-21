"""Описание API сервиса в формате OpenAPI 3 (для Swagger UI на /docs)."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parent.parent / "docs" / "examples"


def _example(name):
    try:
        return json.loads((EX / name).read_text(encoding="utf-8"))
    except Exception:
        return None


def _ex(summary, name):
    v = _example(name)
    return {"summary": summary, "value": v} if v is not None else None


def spec():
    ingest_examples = {k: v for k, v in {
        "clean": _ex("Чистый пакет: все сделки принимаются", "1_clean.json"),
        "forbidden_ids": _ex("Записи с user_id, account_id, broker_id: отклоняются", "2_forbidden_ids.json"),
        "outside_hours": _ex("Сделки вне часов торгов 10:00–18:50", "3_outside_hours.json"),
        "duplicates": _ex("Повторы одного event_id", "4_duplicates.json"),
        "bad_values": _ex("Плохие цены, количества и время", "5_bad_values.json"),
        "unknown": _ex("Неизвестные тикер, сессия, источник", "6_unknown.json"),
        "iss": _ex("Таблица trades в формате ISS Мосбиржи", "7_iss_format.json"),
    }.items() if v}
    err = {"description": "Ошибка", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    ok = lambda ref, d="Успешно": {"description": d, "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}}}
    id_param = lambda name: {"name": name, "in": "path", "required": True, "schema": {"type": "string"}, "description": "Идентификатор из ответа запуска"}
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Консультирование на данных Мосбиржи: API",
            "version": "1.0.0",
            "description": (
                "API сервиса просмотра баз и загрузки данных.\n\n"
                "**Как устроена загрузка.** Сделки принимает загрузчик (`POST /api/ingest`): он проверяет каждую запись "
                "(белый список полей, запрет ID участников, цена `Decimal(20,8)`, допуск бумаги к сессии, часы торгов 10:00–18:50, "
                "дубли) и возвращает вердикт по каждой строке. Принятые сделки уходят в ClickHouse, сырой пакет в MinIO, "
                "задание и карантин в PostgreSQL. Дневные бары загружает DAG Airflow, а не этот API.\n\n"
                "Сделки из `/api/ingest` попадают в отдельную сессию-песочницу `20990103` (SBER, 10:00–18:50): реальные данные не затрагиваются.\n\n"
                "**Доступ.** Все запросы идут через nginx с базовой авторизацией (логин `advisory`)."),
        },
        "servers": [{"url": "./", "description": "Тот же адрес, с которого открыта эта страница"}],
        "security": [{"basicAuth": []}],
        "tags": [
            {"name": "Загрузка сделок", "description": "Подать свой JSON и посмотреть реакцию системы"},
            {"name": "Данные", "description": "Просмотр таблиц PostgreSQL, ClickHouse и файлов MinIO"},
            {"name": "Рыночная аналитика", "description": "Исторические аналоги и вклад крупных сделок в VWAP"},
            {"name": "Тесты", "description": "15 тестов на сложные задачи БД"},
            {"name": "Служебное", "description": "Состояние служб, наполнение и очистка баз"},
        ],
        "paths": {
            "/api/ingest": {"post": {
                "tags": ["Загрузка сделок"], "summary": "Отправить пакет сделок",
                "description": "Тело запроса — сам JSON: список записей или таблица `trades` в формате ISS. "
                               "С `dry=1` пакет только разбирается, в базы ничего не пишется.",
                "parameters": [
                    {"name": "dry", "in": "query", "schema": {"type": "string", "enum": ["1"]},
                     "description": "`1` — разбор без записи в базы"},
                    {"name": "candles", "in": "query", "schema": {"type": "string", "enum": ["1"]},
                     "description": "`1` — после записи пересчитать минутные свечи сессии"}],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"oneOf": [{"type": "array", "items": {"$ref": "#/components/schemas/Trade"}, "maxItems": 5000},
                                         {"$ref": "#/components/schemas/IssTrades"}]},
                    "examples": ingest_examples}}},
                "responses": {"200": {"description": "Вердикт по каждой записи. Без `dry=1` в ответе ещё карантин, счётчики до и после и свечи",
                                      "content": {"application/json": {"schema": {"$ref": "#/components/schemas/IngestResult"}}}},
                              "401": {"description": "Нужен логин и пароль"}, "500": err}}},
            "/api/ingest/session": {"post": {
                "tags": ["Загрузка сделок"], "summary": "Закрыть или открыть сессию-песочницу",
                "description": "Меняет только статус. После закрытия загрузчик отклоняет все сделки сессии (`session_closed`). "
                               "Свечи при этом не пересчитываются: их считает `/api/ingest?candles=1`.",
                "parameters": [{"name": "status", "in": "query", "required": True, "schema": {"type": "string", "enum": ["open", "closed"]}}],
                "responses": {"200": ok("SessionStatus")}}},
            "/api/ingest/reset": {"post": {
                "tags": ["Загрузка сделок"], "summary": "Очистить сделки и свечи песочницы и открыть сессию",
                "responses": {"200": ok("SessionStatus")}}},
            "/api/status": {"get": {"tags": ["Служебное"], "summary": "Состояние ClickHouse, PostgreSQL и MinIO",
                                    "responses": {"200": ok("ServiceStatus")}}},
            "/api/tables": {"get": {"tags": ["Данные"], "summary": "Список таблиц с числом строк",
                                    "responses": {"200": ok("Tables")}}},
            "/api/table": {"get": {
                "tags": ["Данные"], "summary": "Содержимое таблицы (по 30 строк)",
                "parameters": [
                    {"name": "db", "in": "query", "required": True, "schema": {"type": "string", "enum": ["pg", "ch"]}, "description": "`pg` — PostgreSQL, `ch` — ClickHouse"},
                    {"name": "name", "in": "query", "required": True, "schema": {"type": "string"}, "example": "daily_bars"},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200}},
                    {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0, "minimum": 0}}],
                "responses": {"200": ok("TablePage"), "404": err}}},
            "/api/market/sessions": {"get": {
                "tags": ["Рыночная аналитика"], "summary": "Сессии с минутными свечами и числом сделок",
                "parameters": [{"name": "ticker_id", "in": "query", "schema": {"type": "integer"}, "example": 1}],
                "responses": {"200": {"description": "Список сессий"}, "400": err}}},
            "/api/market/twins": {"get": {
                "tags": ["Рыночная аналитика"], "summary": "Найти исторические двойники участка графика",
                "description": "Сравнивает непрерывные окна 15–30 минут по нормированной цене, относительному объёму и диапазону свечей. Возвращает до 10 непересекающихся аналогов, их графики и фактическое продолжение. Это исследование истории, не прогноз.",
                "parameters": [
                    {"name": "ticker_id", "in": "query", "required": True, "schema": {"type": "integer"}, "example": 1},
                    {"name": "session_id", "in": "query", "required": True, "schema": {"type": "integer"}, "example": 290020261029},
                    {"name": "end", "in": "query", "schema": {"type": "string", "format": "date-time"}, "description": "Конец эталонного участка; по умолчанию последняя свеча сессии"},
                    {"name": "length", "in": "query", "schema": {"type": "integer", "minimum": 15, "maximum": 30, "default": 20}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}],
                "responses": {"200": {"description": "Эталон, оценки сходства, графики и доходность после аналогов"}, "400": err}}},
            "/api/market/butterfly": {"get": {
                "tags": ["Рыночная аналитика"], "summary": "Эффект бабочки: VWAP без доли крупнейших сделок",
                "description": "Ранжирует сделки по обороту и пересчитывает VWAP без выбранной доли крупнейших. Показывает вклад в статистику, а не модель рынка без сделок.",
                "parameters": [
                    {"name": "ticker_id", "in": "query", "required": True, "schema": {"type": "integer"}, "example": 1},
                    {"name": "session_id", "in": "query", "required": True, "schema": {"type": "integer"}, "example": 290020261029},
                    {"name": "start", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                    {"name": "end", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                    {"name": "top_percent", "in": "query", "schema": {"type": "number", "exclusiveMinimum": 0, "maximum": 50, "default": 1}}],
                "responses": {"200": {"description": "VWAP, VWAP без крупных сделок, разница и доля оборота"}, "400": err}}},
            "/api/minio": {"get": {"tags": ["Данные"], "summary": "Объекты в бакете raw-market (сырьё)",
                                   "responses": {"200": {"description": "Список объектов", "content": {"application/json": {"schema": {
                                       "type": "array", "items": {"type": "object", "properties": {"key": {"type": "string"}, "size": {"type": "integer"}}}}}}}}}},
            "/api/minio/object": {"get": {
                "tags": ["Данные"], "summary": "Первые 4000 байт объекта MinIO",
                "parameters": [{"name": "key", "in": "query", "required": True, "schema": {"type": "string"}, "example": "demo-batch-1.jsonl"}],
                "responses": {"200": {"description": "Текст", "content": {"application/json": {"schema": {"type": "object", "properties": {"text": {"type": "string"}}}}}}, "404": err}}},
            "/api/tests": {"get": {"tags": ["Тесты"], "summary": "Описание 15 тестов: суть, как проверяем, результат, код",
                                   "responses": {"200": {"description": "Список тестов", "content": {"application/json": {"schema": {
                                       "type": "array", "items": {"$ref": "#/components/schemas/TestInfo"}}}}}}}},
            "/api/run": {"post": {
                "tags": ["Тесты"], "summary": "Запустить тесты",
                "description": "Без тела запускает все 15. Можно передать список имён.",
                "requestBody": {"required": False, "content": {"application/json": {"schema": {
                    "type": "object", "properties": {"tests": {"type": "array", "items": {"type": "string"}, "example": ["test_01_portfolio_by_issuer_with_grouping_sets"]}}}}}},
                "responses": {"200": {"description": "Идентификатор запуска", "content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}}},
            "/api/run/{id}": {"get": {
                "tags": ["Тесты"], "summary": "Ход запуска: статусы тестов, запросы к БД, вывод pytest",
                "parameters": [id_param("id")], "responses": {"200": ok("RunView"), "404": err}}},
            "/api/run/{id}/stop": {"post": {
                "tags": ["Тесты"], "summary": "Остановить запуск", "parameters": [id_param("id")],
                "responses": {"200": {"description": "Остановлен", "content": {"application/json": {"schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}}}}}},
            "/api/seed": {"post": {
                "tags": ["Служебное"], "summary": "Наполнить базы данными Мосбиржи",
                "description": "Сырьё в MinIO, справочники в PostgreSQL, бары в ClickHouse; с `day=true` ещё демонстрация торгового дня и демо-данные.",
                "requestBody": {"required": False, "content": {"application/json": {"schema": {
                    "type": "object", "properties": {"live": {"type": "boolean", "default": False, "description": "`true` — живой API Мосбиржи, иначе сохранённые ответы"},
                                                     "day": {"type": "boolean", "default": True}}}}}},
                "responses": {"200": {"description": "Идентификатор задания", "content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}}},
            "/api/job/{id}": {"get": {"tags": ["Служебное"], "summary": "Ход задания наполнения или очистки", "parameters": [id_param("id")],
                                      "responses": {"200": ok("Job"), "404": err}}},
            "/api/reset": {"post": {"tags": ["Служебное"], "summary": "Очистить базы service и сырьё в MinIO",
                                    "description": "Удаляет данные. Пересоздаёт пустые схемы.",
                                    "responses": {"200": {"description": "Идентификатор задания", "content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}}},
        },
        "components": {
            "securitySchemes": {"basicAuth": {"type": "http", "scheme": "basic", "description": "Логин `advisory` и пароль веб-сервиса"}},
            "schemas": {
                "Error": {"type": "object", "properties": {"error": {"type": "string"}}},
                "Trade": {"type": "object", "additionalProperties": False,
                          "required": ["source_id", "event_id", "ticker_id", "session_id", "event_time", "price", "quantity"],
                          "properties": {
                              "source_id": {"type": "string", "example": "MOEX-ISS", "description": "Источник; должен совпадать с источником пакета"},
                              "event_id": {"type": "string", "example": "1001", "description": "Номер сделки; вместе с source_id задаёт уникальность"},
                              "ticker_id": {"type": "integer", "example": 1, "description": "1 = SBER"},
                              "session_id": {"type": "integer", "example": 20990103, "description": "Сессия-песочница"},
                              "event_time": {"type": "string", "example": "2026-10-29T10:15:00", "description": "Московское время; торги 10:00–18:50"},
                              "price": {"type": "string", "example": "298.50", "description": "Положительное, до 12 знаков до запятой и до 8 после (Decimal(20,8))"},
                              "quantity": {"type": "integer", "example": 10, "minimum": 1}},
                          "description": "Поля с ID участников (`user_id`, `owner_id`, `account_id`, `customer_id`, `broker_id`, `participant_id`, `client_id`) запрещены: запись отклоняется."},
                "IssTrades": {"type": "object", "required": ["trades"], "description": "Таблица сделок в формате ISS Мосбиржи; поле BUYSELL не переносится",
                              "properties": {"trades": {"type": "object", "properties": {
                                  "columns": {"type": "array", "items": {"type": "string"}, "example": ["TRADENO", "TRADETIME", "SECID", "PRICE", "QUANTITY", "TRADEDATE"]},
                                  "data": {"type": "array", "items": {"type": "array", "items": {}}}}}}},
                "VerdictRow": {"type": "object", "properties": {
                    "n": {"type": "integer", "description": "Номер записи в пакете с единицы"},
                    "verdict": {"type": "string", "enum": ["accepted", "duplicate", "rejected"]},
                    "rule": {"type": "string", "nullable": True, "example": "outside_session_hours", "description": "Код правила, по которому отклонена запись"},
                    "why": {"type": "string", "description": "Объяснение по-русски"},
                    "event_id": {"type": "string"}, "time": {"type": "string"}, "price": {"type": "string"}, "qty": {"type": "string"}}},
                "Summary": {"type": "object", "properties": {"accepted": {"type": "integer"}, "duplicate": {"type": "integer"}, "rejected": {"type": "integer"}}},
                "IngestResult": {"type": "object", "properties": {
                    "rows": {"type": "array", "items": {"$ref": "#/components/schemas/VerdictRow"}},
                    "summary": {"$ref": "#/components/schemas/Summary"},
                    "batch": {"type": "string", "description": "Только без dry: идентификатор пакета"},
                    "quarantine": {"type": "array", "items": {"type": "object", "properties": {"row": {"type": "integer"}, "rule": {"type": "string"}}},
                                   "description": "Только без dry: что попало в карантин PostgreSQL (номер строки и код, без копии записи)"},
                    "before": {"type": "object", "additionalProperties": {"type": "integer"}, "description": "Только без dry: число строк в таблицах до"},
                    "after": {"type": "object", "additionalProperties": {"type": "integer"}, "description": "Только без dry: после"},
                    "candles": {"type": "object", "nullable": True, "description": "Только с candles=1: свечи сессии"}}},
                "SessionStatus": {"type": "object", "properties": {"session_id": {"type": "integer"}, "status": {"type": "string", "enum": ["open", "closed"]}, "window": {"type": "string"}}},
                "ServiceStatus": {"type": "object", "additionalProperties": {"type": "object", "properties": {"ok": {"type": "boolean"}, "info": {"type": "string"}}}},
                "Tables": {"type": "object", "properties": {k: {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "rows": {"type": "integer"}}}} for k in ("pg", "ch")}},
                "TablePage": {"type": "object", "properties": {
                    "columns": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}}},
                    "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                    "total": {"type": "integer"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}},
                "TestInfo": {"type": "object", "properties": {"id": {"type": "string"}, "num": {"type": "string"}, "db": {"type": "string"}, "title": {"type": "string"},
                                                              "essence": {"type": "string"}, "how": {"type": "string"}, "expected": {"type": "string"}, "code": {"type": "string"}}},
                "RunView": {"type": "object", "properties": {
                    "id": {"type": "string"}, "status": {"type": "string", "enum": ["running", "done"]}, "rc": {"type": "integer", "nullable": True},
                    "elapsed": {"type": "number"}, "lines": {"type": "array", "items": {"type": "string"}},
                    "tests": {"type": "object", "description": "Имя теста → статус, время, запросы к БД и ошибка", "additionalProperties": {"type": "object", "properties": {
                        "status": {"type": "string", "enum": ["pending", "running", "passed", "failed", "error", "skipped"]}, "duration": {"type": "number", "nullable": True},
                        "sql": {"type": "array", "items": {"type": "object"}}, "error": {"type": "string"}}}}}},
                "Job": {"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string", "enum": ["running", "done", "error"]}, "lines": {"type": "array", "items": {"type": "string"}}}},
            },
        },
    }


DOCS_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>API · Swagger</title>
<link rel="stylesheet" href="static/swagger-ui.css">
<style>body{margin:0}</style></head>
<body><div id="ui"></div>
<script src="static/swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle({url: "openapi.json", dom_id: "#ui", deepLinking: true, docExpansion: "list",
  defaultModelsExpandDepth: 0, tryItOutEnabled: true, persistAuthorization: false});
</script></body></html>
"""
