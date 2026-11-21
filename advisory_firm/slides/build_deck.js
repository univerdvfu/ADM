// Сборка презентации: npm install pptxgenjs && node build_deck.js [выходной.pptx]
const pptxgen = require("pptxgenjs");
const out = process.argv[2] || "Консультирование_Мосбиржа.pptx";

const NAVY = "10243E", INK = "1E293B", MUTED = "5B6B7F", PAPER = "F4F6F9", WHITE = "FFFFFF";
const TEAL = "1F7A7A", GOLD = "D99A2B", LINE = "D5DCE6", SOFT = "E6EEF5";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.title = "Инвестиционное консультирование на данных Мосбиржи";
pres.author = "Учебный проект";

function base(dark) {
  const s = pres.addSlide();
  s.background = { color: dark ? NAVY : PAPER };
  return s;
}
function title(s, text, dark) {
  s.addText(text, { x: 0.6, y: 0.35, w: 12.1, h: 0.8, fontFace: "Cambria", fontSize: 32,
    bold: true, color: dark ? WHITE : NAVY, margin: 0, valign: "middle", isTextBox: true });
}
function footer(s, dark) {
  s.addText("Инвестиционное консультирование · данные Мосбиржи", { x: 0.6, y: 7.0, w: 8, h: 0.3,
    fontFace: "Calibri", fontSize: 10, color: dark ? "9FB0C5" : MUTED, margin: 0, isTextBox: true });
}
function card(s, x, y, w, h, fill) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.12,
    fill: { color: fill || WHITE }, line: { color: LINE, width: 0.75 },
    shadow: { type: "outer", color: "000000", opacity: 0.12, blur: 6, offset: 2, angle: 90 } });
}
function bullets(items, size) {
  return items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1,
    paraSpaceAfter: 8, fontSize: size || 16 } }));
}
function tableRows(rows, widths) {
  return rows.map((r, i) => r.map((c, j) => ({ text: c, options: {
    bold: i === 0 || j === 0, color: i === 0 ? WHITE : INK, fontSize: i === 0 ? 14 : 14,
    fill: { color: i === 0 ? NAVY : (i % 2 ? WHITE : SOFT) }, valign: "middle",
    fontFace: "Calibri", margin: [0.05, 0.12, 0.05, 0.12] } })));
}

const KEYCOL = { PK: GOLD, "PK/FK": GOLD, FK: TEAL, KEY: GOLD, REF: TEAL };
const RH = 0.235, HH = 0.34;
const boxH = (n) => HH + n * RH;

// ER-карточка: заголовок + строки [ключ, поле, тип]. Возвращает рамку для стрелок.
function er(s, x, y, w, name, rows, head) {
  const h = boxH(rows.length);
  s.addShape(pres.ShapeType.rect, { x, y, w, h, fill: { color: WHITE }, line: { color: LINE, width: 0.75 },
    shadow: { type: "outer", color: "000000", opacity: 0.1, blur: 4, offset: 1, angle: 90 } });
  s.addShape(pres.ShapeType.rect, { x, y, w, h: HH, fill: { color: head || NAVY }, line: { color: head || NAVY, width: 0 } });
  s.addText(name, { x: x + 0.08, y, w: w - 0.16, h: HH, fontFace: "Calibri", fontSize: 12, bold: true, color: WHITE,
    margin: 0, valign: "middle", isTextBox: true });
  const kw = 0.52, tw = w * 0.4;
  s.addTable(rows.map((r, i) => [
    { text: r[0], options: { bold: true, color: KEYCOL[r[0]] || INK, fontSize: 10 } },
    { text: r[1], options: { color: INK, fontSize: 10.5 } },
    { text: r[2] || "", options: { color: MUTED, fontSize: 10 } }].map(c => ({ text: c.text, options: Object.assign({
      fontFace: "Calibri", margin: [0, 0.05, 0, 0.06], valign: "middle",
      fill: { color: i % 2 ? WHITE : "F3F6FA" } }, c.options) }))),
    { x, y: y + HH, w, colW: [kw, w - kw - tw, tw], rowH: RH, border: { type: "none" } });
  return { x, y, w, h };
}
function arrow(s, x1, y1, x2, y2, label, lx, ly) {
  s.addShape(pres.ShapeType.line, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: x2 < x1, flipV: y2 < y1, line: { color: GOLD, width: 1.5, endArrowType: "triangle" } });
  if (label) s.addText(label, { x: lx !== undefined ? lx : (x1 + x2) / 2 - 0.4, y: ly !== undefined ? ly : (y1 + y2) / 2 - 0.3,
    w: 0.8, h: 0.25, fontFace: "Calibri", fontSize: 10, bold: true, color: GOLD, align: "center", margin: 0, isTextBox: true });
}
function note(s, x, y, w, h, text, size) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: SOFT }, line: { color: LINE, width: 0.75 } });
  s.addText(text, { x: x + 0.15, y, w: w - 0.3, h, fontFace: "Calibri", fontSize: size || 12, color: INK, margin: 0, valign: "middle", isTextBox: true });
}

// 1. Титул
{
  const s = base(true);
  s.addText("Инвестиционное консультирование на данных Мосбиржи", { x: 0.8, y: 1.9, w: 10.5, h: 2.0,
    fontFace: "Cambria", fontSize: 44, bold: true, color: WHITE, margin: 0, valign: "top", isTextBox: true });
  s.addText("Учебный прототип: эмуляция базы предметной области и тесты на сложные задачи БД",
    { x: 0.8, y: 4.1, w: 10, h: 0.9, fontFace: "Calibri", fontSize: 20, color: "C9D6E6", margin: 0, isTextBox: true });
  s.addText("PostgreSQL · ClickHouse · MinIO · Airflow", { x: 0.8, y: 5.5, w: 10, h: 0.5,
    fontFace: "Calibri", fontSize: 18, bold: true, color: GOLD, margin: 0, isTextBox: true });
  s.addNotes("Область проекта: инвестиционное консультирование. Фирма получает рыночные данные биржи, считает показатели и готовит проверенные рекомендации клиентам. Это не биржа и не торговая система.");
}

// 2. Область
{
  const s = base(false); title(s, "Область проекта");
  card(s, 0.6, 1.5, 5.9, 4.9);
  s.addText("Реализуем", { x: 0.9, y: 1.7, w: 5.3, h: 0.5, fontFace: "Cambria", fontSize: 22, bold: true, color: TEAL, margin: 0, isTextBox: true });
  s.addText(bullets(["Загрузка дневных данных Мосбиржи", "Справочники: эмитенты, тикеры, сессии",
    "Доходность, волатильность, просадка", "Клиенты, портфели, корпоративные события",
    "15 тестов на сложные задачи БД"]), { x: 0.9, y: 2.3, w: 5.3, h: 3.9, fontFace: "Calibri", color: INK, margin: 0, valign: "top", isTextBox: true });
  card(s, 6.8, 1.5, 5.9, 4.9);
  s.addText("Не входит", { x: 7.1, y: 1.7, w: 5.3, h: 0.5, fontFace: "Cambria", fontSize: 22, bold: true, color: GOLD, margin: 0, isTextBox: true });
  s.addText(bullets(["Торговый движок и клиринг", "Надзор и расследования биржи",
    "Первичный слой биржи и заявки", "Kafka и поток тиков", "Настоящая инвестиционная методика"]),
    { x: 7.1, y: 2.3, w: 5.3, h: 3.9, fontFace: "Calibri", color: INK, margin: 0, valign: "top", isTextBox: true });
  footer(s);
  s.addNotes("Область сужена по замечанию преподавателя: фирма-аналитик, а не биржа. Правила рекомендаций учебные.");
}

// 3. Стек
{
  const s = base(false); title(s, "Стек и роли компонентов");
  s.addTable(tableRows([
    ["Компонент", "Тип", "Что хранит и делает"],
    ["PostgreSQL", "Реляционная БД", "Справочники, клиенты, портфели, журнал рекомендаций, карантин"],
    ["ClickHouse", "Колоночная БД", "Дневные бары, свечи, сигналы, журналы загрузки"],
    ["MinIO", "Объектное хранилище", "Сырые ответы API биржи, пакеты данных, отчёты"],
    ["Airflow", "Оркестратор", "Расписание: загрузка, проверка качества, пересчёт"]]),
    { x: 0.6, y: 1.5, w: 12.1, colW: [2.2, 3.0, 6.9], rowH: 0.7, border: { type: "solid", color: LINE, pt: 0.75 } });
  footer(s);
  s.addNotes("Стек взят из исходной презентации (слайд 2). Kafka относится к приёму потока на стороне биржи; для аналитической фирмы достаточно пакетной загрузки.");
}

// sources
{
  const s = base(false); title(s, "Источники и шлюз");
  const cols = [["Источники", ["API Мосбиржи (ISS): история и карточки бумаг", "Эмитенты: корпоративные события (вводятся вручную)", "Сохранённые ответы биржи для автономного показа"]],
    ["Передаём", ["Дневные бары: цены, объём, оборот", "Справочники: бумаги, лоты, шаг цены", "Сделки и котировки, если источник их отдаёт"]],
    ["Шлюз", ["Задача fetch в Airflow, по будням в 19:00", "Сырьё сохраняется в MinIO как есть", "ID участников в сырьё не попадают"]]];
  cols.forEach((c, i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.5, 3.9, 4.3);
    s.addText(c[0], { x: x + 0.25, y: 1.7, w: 3.4, h: 0.5, fontFace: "Cambria", fontSize: 22, bold: true, color: i === 2 ? GOLD : TEAL, margin: 0, isTextBox: true });
    s.addText(bullets(c[1], 15), { x: x + 0.25, y: 2.35, w: 3.4, h: 3.3, fontFace: "Calibri", color: INK, margin: 0, valign: "top", isTextBox: true });
    if (i < 2) s.addText("›", { x: x + 3.9, y: 3.2, w: 0.2, h: 0.6, fontFace: "Calibri", fontSize: 28, bold: true, color: GOLD, align: "center", margin: 0, isTextBox: true });
  });
  note(s, 0.6, 6.05, 12.1, 0.75, "Шлюз изолирует хранилище от особенностей источника: в базы попадает только то, что прошло проверку контракта.", 15);
  footer(s);
  s.addNotes("Аналог программы-шлюза из исходной схемы. Вместо Windows-службы и FIX здесь пакетная задача Airflow, потому что консультанту не нужен поток тиков.");
}

// 4. Поток данных
{
  const s = base(false); title(s, "Поток данных");
  const steps = [["API Мосбиржи", "дневные бары, справочники"], ["MinIO", "сырьё как есть"],
    ["Загрузка", "проверка контракта"], ["PostgreSQL ClickHouse", "справочники и ряды"],
    ["Проверка качества", "high ≥ low, без пропусков"], ["Рекомендации", "черновики по клиентам"],
    ["Отчёт клиенту", "только опубликованное"]];
  const w = 1.5, gap = 0.267;
  steps.forEach((st, i) => {
    const x = 0.6 + i * (w + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.7, w, h: 1.3, rectRadius: 0.1, fill: { color: i === 3 ? TEAL : NAVY }, line: { color: NAVY, width: 0 } });
    s.addText(st[0], { x, y: 1.7, w, h: 1.3, fontFace: "Calibri", fontSize: 14, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0.06, isTextBox: true });
    s.addText(st[1], { x, y: 3.1, w, h: 0.8, fontFace: "Calibri", fontSize: 12, color: MUTED, align: "center", valign: "top", margin: 0, isTextBox: true });
    if (i < steps.length - 1) s.addText("›", { x: x + w, y: 2.05, w: gap, h: 0.6, fontFace: "Calibri", fontSize: 28, bold: true, color: GOLD, align: "center", valign: "middle", margin: 0, isTextBox: true });
  });
  card(s, 0.6, 4.3, 12.1, 1.0, SOFT);
  s.addText("Airflow · DAG advisory_pipeline · по будням в 19:00 · две попытки при сбое",
    { x: 0.9, y: 4.3, w: 11.5, h: 1.0, fontFace: "Calibri", fontSize: 18, bold: true, color: NAVY, margin: 0, valign: "middle", isTextBox: true });
  s.addText("Повторный запуск безопасен: бары схлопываются по ключу (ticker_id, session_id), черновики рекомендаций не дублируются, пакет сделок пропускается по batch_id.",
    { x: 0.6, y: 5.6, w: 12.1, h: 0.9, fontFace: "Calibri", fontSize: 16, color: INK, margin: 0, valign: "top", isTextBox: true });
  footer(s);
  s.addNotes("Пять задач DAG: init, fetch, load, check, recommend. Каждая прогнана вживую против API Мосбиржи.");
}

// 4a. Блок-схема
{
  const s = base(false); title(s, "Блок-схема: как работает система");
  const h = 5.55, w = h * 1280 / 800;
  s.addImage({ path: require("path").join(__dirname, "..", "docs", "block_scheme.png"), x: (13.333 - w) / 2, y: 1.3, w, h,
    altText: "Блок-схема: API Мосбиржи, Airflow, MinIO, загрузчик, PostgreSQL, ClickHouse, потребители" });
  footer(s);
  s.addNotes("Пошаговая анимация этой схемы лежит в docs/how_it_works.gif (8 шагов): запуск DAG в 19:00, запрос к API, сырьё в MinIO, выгрузка справочников, проверка загрузчиком, контроль качества, закрытие сессии, результат. Пересобрать: python docs/make_animation.py.");
}

// er_pg_a
{
  const s = base(false); title(s, "ER-диаграмма · PostgreSQL: справочники и участники");
  const W = 2.7, X = [0.6, 3.73, 6.86, 9.99];
  const issuers = er(s, X[0], 1.45, W, "issuers · эмитенты", [["PK", "issuer_id", "BIGINT"], ["", "name", "VARCHAR(255)"], ["", "country_code", "CHAR(2)"]]);
  const instr = er(s, X[0], 2.85, W, "instruments · инструменты", [["PK", "instrument_id", "BIGINT"], ["FK", "issuer_id", "BIGINT"], ["", "instrument_type", "VARCHAR(20)"],
    ["", "nominal_value", "NUMERIC(20,8)"], ["", "currency", "CHAR(4)"], ["", "contract_term", "VARCHAR(10) NULL"], ["", "exercise_style", "VARCHAR(10) NULL"], ["", "maturity_date", "DATE NULL"]]);
  const tick = er(s, X[1], 3.44, W, "tickers · тикеры", [["PK", "ticker_id", "BIGINT"], ["FK", "instrument_id", "BIGINT"], ["", "ticker", "VARCHAR(20) UQ"]], TEAL);
  const si = er(s, X[1], 4.85, W, "session_instruments · допуски", [["PK/FK", "session_id", "BIGINT"], ["PK/FK", "ticker_id", "BIGINT"], ["", "trading_status", "VARCHAR(20)"], ["", "lot_size", "BIGINT"], ["", "tick_size", "NUMERIC(20,8)"]], TEAL);
  const ts = er(s, X[2], 4.735, W, "trading_sessions · сессии", [["PK", "session_id", "BIGINT"], ["", "session_date", "DATE"], ["", "start_time", "TIMESTAMPTZ"], ["", "end_time", "TIMESTAMPTZ"], ["", "venue", "VARCHAR(40)"], ["", "status", "VARCHAR(20)"]]);
  const req = er(s, X[2], 1.45, W, "client_requests · поручения", [["PK", "request_id", "BIGINT"], ["FK", "account_id", "BIGINT"], ["FK", "ticker_id", "BIGINT"], ["FK", "session_id", "BIGINT"], ["", "side", "VARCHAR(4)"], ["", "quantity", "BIGINT"], ["", "limit_price", "NUMERIC(20,8) NULL"]], "6B7B8F");
  const acc = er(s, X[3], 1.8, W, "owner_accounts · аккаунты", [["PK", "account_id", "BIGINT"], ["FK", "customer_id", "BIGINT"], ["FK", "broker_id", "BIGINT"], ["FK", "ticker_id", "BIGINT NOT NULL"]], "6B7B8F");
  const cust = er(s, X[3], 3.43, W, "customers · заказчики", [["PK", "customer_id", "BIGINT"], ["FK", "broker_id", "BIGINT"], ["", "display_alias", "VARCHAR(80)"]], "6B7B8F");
  const brk = er(s, X[3], 4.83, W, "brokers · брокеры", [["PK", "broker_id", "BIGINT"], ["", "name", "VARCHAR(255)"], ["", "license_status", "VARCHAR(20)"]], "6B7B8F");
  arrow(s, X[0] + W / 2, 1.45 + boxH(3), X[0] + W / 2, 2.85, "1 : N", X[0] + W / 2 + 0.05, 2.45);
  arrow(s, X[0] + W, 2.85 + boxH(8) / 2, X[1], 3.44 + boxH(3) / 2, "1 : N", X[0] + W - 0.18, 2.85 + boxH(8) / 2 - 0.32);
  arrow(s, X[1] + W / 2, 3.44 + boxH(3), X[1] + W / 2, 4.85, "1 : N", X[1] + W / 2 + 0.05, 4.5);
  arrow(s, X[2], 4.735 + boxH(6) / 2, X[1] + W, 4.85 + boxH(5) / 2, "1 : N", X[1] + W - 0.2, 4.735 + boxH(6) / 2 - 0.3);
  arrow(s, X[3] + W / 2, 4.83, X[3] + W / 2, 3.43 + boxH(3), "1 : N", X[3] + W / 2 + 0.05, 4.45);
  arrow(s, X[3] + W / 2, 3.43, X[3] + W / 2, 1.8 + boxH(4), "1 : N", X[3] + W / 2 + 0.05, 3.08);
  arrow(s, X[3], 1.8 + boxH(4) / 2, X[2] + W, 1.8 + boxH(4) / 2, "1 : N", X[2] + W - 0.2, 1.8 + boxH(4) / 2 - 0.3);
  note(s, X[0], 5.45, W, 1.3, "Служебные: ingest_jobs, quarantine. Серые таблицы — внешний контур источника, в аналитику не выгружаются.", 11);
  note(s, X[2], 3.9, W, 0.65, "Поручение: пара (session_id, ticker_id) → session_instruments", 10.5);
  footer(s);
  s.addNotes("Основа взята из исходной ER-диаграммы PostgreSQL. Изменено: номинал 20,8, валюта 4 знака, тикер как объект, допуск инструмента к сессии, срок и стиль контракта, заказчик через брокера, обязательный аккаунт владельца. Вместо orders — client_requests; surveillance_cases и system_users убраны.");
}

// er_pg_b
{
  const s = base(false); title(s, "ER-диаграмма · PostgreSQL: консультирование");
  const W = 3.5, X = [0.6, 4.9, 9.2];
  const cl = er(s, X[0], 1.45, W, "advisory_clients · клиенты фирмы", [["PK", "client_id", "BIGINT"], ["", "alias", "VARCHAR(80) UQ"], ["", "risk_profile", "VARCHAR(12)"], ["", "horizon_days", "INT"], ["", "max_position_pct", "NUMERIC(5,2)"], ["", "status", "VARCHAR(12)"]]);
  const pos = er(s, X[0], 3.5, W, "positions · портфель", [["PK/FK", "client_id", "BIGINT"], ["PK/FK", "ticker_id", "BIGINT"], ["", "quantity", "BIGINT"], ["", "avg_price", "NUMERIC(20,8)"]]);
  const rec = er(s, X[1], 1.45, W, "recommendations · журнал (неизменяем)", [["PK", "rec_id", "UUID"], ["FK", "client_id", "BIGINT"], ["FK", "ticker_id", "BIGINT"], ["", "action", "buy / sell / hold"], ["", "risk_class", "low / medium / high"],
    ["", "method_version", "VARCHAR(30)"], ["", "data_cutoff", "DATE"], ["", "rationale", "TEXT"], ["", "risk_disclosure", "TEXT NOT NULL"], ["", "author, created_at", "VARCHAR / TIMESTAMPTZ"]], TEAL);
  const st = er(s, X[1], 4.6, W, "recommendation_status_events", [["PK", "event_id", "BIGSERIAL"], ["FK", "rec_id", "UUID"], ["", "status", "draft / approved / …"], ["", "actor", "VARCHAR(80)"], ["", "ts", "TIMESTAMPTZ"]], TEAL);
  const tk = er(s, X[2], 1.45, W, "tickers · справочник", [["PK", "ticker_id", "BIGINT"], ["", "ticker", "VARCHAR(20) UQ"]]);
  const ce = er(s, X[2], 2.6, W, "corporate_events · события", [["PK", "event_id", "BIGINT"], ["FK", "ticker_id", "BIGINT"], ["", "event_type", "dividend / split"], ["", "ex_date", "DATE"], ["", "amount", "NUMERIC(20,8) NULL"], ["", "split_ratio", "NUMERIC(10,4) NULL"]]);
  arrow(s, X[0] + W, 1.45 + boxH(6) / 2, X[1], 1.45 + boxH(6) / 2, "1 : N", X[0] + W + 0.05, 1.45 + boxH(6) / 2 - 0.3);
  arrow(s, X[0] + W / 2, 1.45 + boxH(6), X[0] + W / 2, 3.5, "1 : N", X[0] + W / 2 + 0.05, 3.2);
  arrow(s, X[1] + W / 2, 1.45 + boxH(10), X[1] + W / 2, 4.6, "1 : N", X[1] + W / 2 + 0.05, 4.2);
  arrow(s, X[2], 1.45 + boxH(2) / 2 + 0.1, X[1] + W, 1.45 + boxH(2) / 2 + 0.1, "1 : N", X[1] + W + 0.05, 1.45 + boxH(2) / 2 - 0.2);
  arrow(s, X[2] + W / 2, 1.45 + boxH(2), X[2] + W / 2, 2.6, "1 : N", X[2] + W / 2 + 0.05, 2.35);
  note(s, X[0], 5.2, W, 1.5, "Клиенты и портфели живут только в PostgreSQL. В ClickHouse они не выгружаются.", 12);
  note(s, X[2], 4.75, W, 1.95, "Журнал неизменяем: триггеры запрещают UPDATE и DELETE. Статус рекомендации — новая строка в status_events, автор не проверяет свою рекомендацию.", 12);
  footer(s);
  s.addNotes("Эти таблицы отсутствуют в исходной схеме и появились из-за области «инвестиционное консультирование»: клиент с риск-профилем, портфель, корпоративные события, журнал рекомендаций.");
}

// er_ch
{
  const s = base(false); title(s, "ER-диаграмма · ClickHouse: аналитика");
  const W = 3.6, X = [0.6, 4.85, 9.1];
  [["СПРАВОЧНИКИ (из PostgreSQL по белому списку)", X[0], TEAL], ["ФАКТЫ И РЫНОЧНЫЕ СОБЫТИЯ", X[1], "1E8A4C"], ["АГРЕГАТЫ", X[2], "B9770E"]].forEach(h =>
    s.addText(h[0], { x: h[1], y: 1.15, w: W, h: 0.3, fontFace: "Calibri", fontSize: 12, bold: true, color: h[2], margin: 0, isTextBox: true }));
  const rs = er(s, X[0], 1.55, W, "ref_sessions · сессии", [["KEY", "session_id", "UInt64"], ["", "session_date", "Date"], ["", "start_at", "DateTime64(3)"], ["", "end_at", "DateTime64(3)"], ["", "venue", "String"], ["", "status", "String"]]);
  const rsi = er(s, X[0], 3.7, W, "ref_session_instruments", [["KEY", "session_id", "UInt64"], ["KEY", "ticker_id", "UInt64"], ["REF", "instrument_id", "UInt64"], ["", "ticker", "String"], ["", "nominal_value", "Decimal(20,8)"],
    ["", "currency", "FixedString(4)"], ["", "contract_term", "String"], ["", "exercise_style", "String"], ["", "… ещё 5 полей", ""]]);
  const tr = er(s, X[1], 1.55, W, "market_trades · сделки", [["KEY", "source_id", "String"], ["KEY", "event_id", "String"], ["REF", "ticker_id", "UInt64"], ["REF", "session_id", "UInt64"], ["", "event_time", "DateTime64(6)"], ["", "price", "Decimal(20,8)"], ["", "quantity", "UInt64"]], "1E8A4C");
  const qt = er(s, X[1], 3.95, W, "market_quotes · котировки", [["KEY", "source_id", "String"], ["KEY", "event_id", "String"], ["REF", "ticker_id", "UInt64"], ["REF", "session_id", "UInt64"], ["", "event_time", "DateTime64(6)"], ["", "bid, ask, bid_qty, ask_qty", "Decimal / UInt64"]], "1E8A4C");
  const ag = er(s, X[2], 1.55, W, "agg_ohlcv_1m · минутные свечи", [["KEY", "ticker_id", "UInt64"], ["KEY", "session_id", "UInt64"], ["KEY", "minute", "DateTime"], ["", "open, high, low, close", "Decimal(20,8)"], ["", "volume", "UInt64"], ["", "trade_count", "UInt64"], ["", "turnover", "Decimal(30,8)"]], "B9770E");
  const db = er(s, X[2], 3.95, W, "daily_bars · дневные бары", [["KEY", "ticker_id", "UInt64"], ["KEY", "session_id", "UInt64"], ["", "trade_date", "Date"], ["", "open, high, low, close", "Decimal(20,8)"], ["", "volume, num_trades", "UInt64"], ["", "turnover", "Decimal(30,8)"], ["", "source_id", "String"]], "B9770E");
  arrow(s, X[0] + W, 1.55 + boxH(6) / 2, X[1], 1.55 + boxH(6) / 2, "session_id", X[0] + W - 0.05, 1.55 + boxH(6) / 2 - 0.3);
  arrow(s, X[0] + W, 3.7 + boxH(9) / 2, X[1], 3.7 + boxH(9) / 2, "ticker_id", X[0] + W - 0.05, 3.7 + boxH(9) / 2 - 0.3);
  arrow(s, X[1] + W, 1.55 + boxH(7) / 2, X[2], 1.55 + boxH(7) / 2, "агрегация", X[1] + W - 0.08, 1.55 + boxH(7) / 2 - 0.3);
  note(s, X[1], 5.95, W, 0.85, "Связи логические: ClickHouse не проверяет ключи, это делает загрузчик.", 11);
  note(s, X[2], 5.95, W, 0.85, "Нет: dim_brokers, fact_order_events, fact_alerts, ID участников.", 11);
  footer(s);
  s.addNotes("KEY — логический идентификатор, REF — логическая ссылка, как в исходной диаграмме. Таблицы signals и recommendations в ClickHouse остались от прежней версии и дублируют журнал PostgreSQL.");
}

// 7. Типы
{
  const s = base(false); title(s, "Типы и правила данных");
  s.addTable(tableRows([
    ["Правило", "Было на слайдах", "Стало"],
    ["Номинал", "NUMERIC(20,4)", "NUMERIC(20,8) / Decimal(20,8)"],
    ["Валюта", "CHAR(3)", "CHAR(4) / FixedString(4)"],
    ["Тикер", "строка внутри instruments", "объект tickers, ссылка ticker_id"],
    ["Инструмент и сессия", "связи нет", "session_instruments, связь M : N"],
    ["Фьючерс и опцион", "один тип-строка", "срок fixed / perpetual, стиль american / european"],
    ["Владелец и заказчик", "нет", "заказчик через брокера, аккаунт владельца обязателен"]]),
    { x: 0.6, y: 1.5, w: 12.1, colW: [2.8, 3.9, 5.4], rowH: 0.7, border: { type: "solid", color: LINE, pt: 0.75 } });
  footer(s);
  s.addNotes("Исправления по замечаниям преподавателя. Для фьючерса срочный требует даты погашения, бессрочный её запрещает; стиль исполнения применим только к опционам.");
}

// 8. Безопасность
{
  const s = base(false); title(s, "Пять уровней защиты и обезличивание");
  const lv = [["Источник", "первичный слой биржи закрыт"], ["Выдача", "отдельная задача по белому списку полей"],
    ["Вход", "проверка схемы, запрет user_id, owner_id, account_id"], ["Хранение", "клиенты только в PostgreSQL, минимум прав"],
    ["Публикация", "проверка вторым человеком и журнал"]];
  lv.forEach((l, i) => {
    const y = 1.5 + i * 1.0;
    s.addShape(pres.ShapeType.ellipse, { x: 0.6, y: y + 0.12, w: 0.6, h: 0.6, fill: { color: NAVY }, line: { color: NAVY, width: 0 } });
    s.addText(String(i + 1), { x: 0.6, y: y + 0.12, w: 0.6, h: 0.6, fontFace: "Calibri", fontSize: 18, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([{ text: l[0] + ". ", options: { bold: true, color: NAVY } }, { text: l[1], options: { color: INK } }],
      { x: 1.45, y, w: 6.3, h: 0.84, fontFace: "Calibri", fontSize: 16, margin: 0, valign: "middle", isTextBox: true });
  });
  card(s, 8.2, 1.5, 4.5, 4.85, SOFT);
  s.addText("Обезличивание — отдельная задача", { x: 8.5, y: 1.65, w: 3.9, h: 0.8, fontFace: "Cambria", fontSize: 18, bold: true, color: NAVY, margin: 0, valign: "top", isTextBox: true });
  s.addText(bullets(["Белый список полей, а не репликация таблиц", "Псевдоним — HMAC с секретом, а не простой хеш",
    "Ключ и таблица соответствий остаются у источника", "В аналитике нет брокеров и клиентов"], 14),
    { x: 8.5, y: 2.6, w: 3.9, h: 3.6, fontFace: "Calibri", color: INK, margin: 0, valign: "top", isTextBox: true });
  footer(s);
  s.addNotes("Реальная биржа потребует больше мер; пять уровней — целевая учебная схема. Уровни 1 и 2 — обязанности источника.");
}

// 10. Данные
{
  const s = base(false); title(s, "Реальные данные Мосбиржи");
  [["5", "бумаг"], ["65", "торговых сессий"], ["325", "дневных баров"], ["0", "ошибок качества"]].forEach((k, i) => {
    const x = 0.6 + i * 3.1;
    card(s, x, 1.5, 2.9, 2.0);
    s.addText(k[0], { x, y: 1.6, w: 2.9, h: 1.2, fontFace: "Cambria", fontSize: 54, bold: true, color: NAVY, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(k[1], { x, y: 2.8, w: 2.9, h: 0.5, fontFace: "Calibri", fontSize: 16, color: MUTED, align: "center", margin: 0, isTextBox: true });
  });
  card(s, 0.6, 3.9, 5.95, 2.5);
  s.addText("Источник", { x: 0.9, y: 4.05, w: 5.4, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: TEAL, margin: 0, isTextBox: true });
  s.addText("Публичный API Мосбиржи (ISS): SBER, GAZP, LKOH, ROSN, GMKN. Реальные цены, объёмы и справочники; запуск 29.10.2026.",
    { x: 0.9, y: 4.6, w: 5.4, h: 1.7, fontFace: "Calibri", fontSize: 15, color: INK, margin: 0, valign: "top", isTextBox: true });
  card(s, 6.75, 3.9, 5.95, 2.5);
  s.addText("Ограничения", { x: 7.05, y: 4.05, w: 5.4, h: 0.45, fontFace: "Cambria", fontSize: 20, bold: true, color: GOLD, margin: 0, isTextBox: true });
  s.addText(bullets(["Сделки публичный API отдаёт пустыми", "Дивиденды из API не получены", "Условия лицензии на данные нужно проверить"], 14),
    { x: 7.05, y: 4.6, w: 5.4, h: 1.7, fontFace: "Calibri", color: INK, margin: 0, valign: "top", isTextBox: true });
  footer(s);
  s.addNotes("Реальные только дневные бары и справочники. Тесты по сделкам используют записи в формате ответа ISS, собранные вручную.");
}

// consumers
{
  const s = base(false); title(s, "Потребители данных");
  s.addTable(tableRows([
    ["Потребитель", "Что получает", "Как"],
    ["Руководство", "Сводка качества загрузки и результатов", "demo/report.html, проверки DAG"],
    ["Аналитик", "Бары, свечи, показатели, черновики", "SQL к ClickHouse и PostgreSQL"],
    ["Проверяющий", "Черновики рекомендаций на проверку", "статусы в журнале PostgreSQL"],
    ["Клиент", "Только опубликованные рекомендации", "client_report, без внутренних ID"],
    ["Администратор ИБ", "Журнал действий", "audit_log и status_events"]]),
    { x: 0.6, y: 1.5, w: 12.1, colW: [2.8, 4.8, 4.5], rowH: 0.72, border: { type: "solid", color: LINE, pt: 0.75 } });
  note(s, 0.6, 6.1, 12.1, 0.7, "В исходной схеме были ещё торговые системы, СМИ и ML-модели с выгрузкой Parquet. Здесь они не реализованы.", 14);
  footer(s);
  s.addNotes("Аналог матрицы потребителей из исходной презентации, сокращённый до того, что есть в прототипе.");
}

// roles
{
  const s = base(false); title(s, "Роли и права");
  s.addTable(tableRows([
    ["Роль", "Может загружать и менять", "Может смотреть"],
    ["Инженер данных", "Пакеты данных, повтор загрузки", "Разрешённый вход, журналы без ПДн"],
    ["Аналитик", "Черновики рекомендаций", "Факты рынка и витрины"],
    ["Проверяющий", "Статусы: согласовать, отклонить, опубликовать", "Рекомендации и методику"],
    ["Администратор ИБ", "Роли и доступы", "Аудит; права аналитика автоматически не получает"],
    ["Клиент", "Ничего", "Только опубликованные рекомендации"]]),
    { x: 0.6, y: 1.5, w: 12.1, colW: [2.8, 4.9, 4.4], rowH: 0.72, border: { type: "solid", color: LINE, pt: 0.75 } });
  note(s, 0.6, 6.1, 12.1, 0.7, "Принцип наименьших привилегий. Сейчас права проверяются в коде приложения, а не ролями СУБД.", 14);
  footer(s);
  s.addNotes("Роли сокращены относительно исходных слайдов (стюард, комплаенс, внешние системы брокеров убраны). Слабое место: права не заданы на уровне БД.");
}

// h1
{
  const s = base(false); title(s, "Процессы H1–H8: загрузка и расчёт");
  s.addTable(tableRows([
    ["Код · инициатор", "Что делает", "Когда запускается"],
    ["H1 · Airflow", "Запускает DAG advisory_pipeline", "Будни, 19:00, после закрытия"],
    ["H2 · Задача fetch", "Скачивает историю и карточки бумаг, кладёт сырьё в MinIO", "Начало DAG"],
    ["H3 · Выгрузка справочников", "Копирует справочники из PostgreSQL по белому списку", "Перед загрузкой фактов"],
    ["H4 · Загрузчик", "Проверяет схему, часы торгов, допуск, дубли; пишет в ClickHouse", "Пришёл пакет"],
    ["H5 · Карантин", "Фиксирует код нарушенного правила, без копии полей", "Ошибка в H4"],
    ["H6 · Закрытие сессии", "Ставит статус closed, считает свечи и сигналы", "Торги окончены"],
    ["H7 · Контроль качества", "Проверяет, что high ≥ low, нет пустых серий", "После загрузки"],
    ["H8 · Задача recommend", "Считает метрики, фильтрует по риску, создаёт черновики", "После H7"]]),
    { x: 0.6, y: 1.45, w: 12.1, colW: [2.9, 6.2, 3.0], rowH: 0.58, border: { type: "solid", color: LINE, pt: 0.75 } });
  footer(s);
  s.addNotes("Адаптация процессов H1–H16 из исходной презентации под реализованный DAG. Первые пять задач DAG — init, fetch, load, check, recommend.");
}

// h2
{
  const s = base(false); title(s, "Процессы H9–H16: проверка и сопровождение");
  s.addTable(tableRows([
    ["Код · инициатор", "Что делает", "Когда запускается"],
    ["H9 · Проверяющий", "Согласует или отклоняет черновик, автор не может проверить своё", "Есть черновик"],
    ["H10 · Публикация", "Переводит согласованную рекомендацию в «опубликована»", "После H9"],
    ["H11 · Клиент", "Получает отчёт только по опубликованному", "По запросу"],
    ["H12 · Сотрудник", "Вносит дивиденды и сплиты в corporate_events", "По мере раскрытия"],
    ["H13 · Инженер данных", "Повторяет пакет и пересчитывает свечи без дублей", "Сбой или исправление"],
    ["H14 · Администратор ИБ", "Назначает роли и читает журнал доступа", "Запрос доступа"],
    ["H15 · Обезличивание (источник)", "Отбирает поля по белому списку, выдаёт псевдонимы HMAC", "До выдачи данных фирме"],
    ["H16 · Контроль", "Проверяет пропуски, повторы, отсутствие ID участников", "Каждый запуск"]]),
    { x: 0.6, y: 1.45, w: 12.1, colW: [3.2, 6.1, 2.8], rowH: 0.58, border: { type: "solid", color: LINE, pt: 0.75 } });
  footer(s);
  s.addNotes("H15 выполняется на стороне источника, у фирмы только проверка контракта на входе. В коде реализованы функция обезличивания и тесты к ней.");
}

// 11a. Сложные задачи БД
{
  const s = base(false); title(s, "15 тестов на сложные задачи БД");
  const R = [["PostgreSQL", "Портфель по эмитентам: GROUPING SETS, итоги по клиенту и общий"],
    ["PostgreSQL", "Откат транзакции: сбой на третьей вставке отменяет две первые"],
    ["PostgreSQL", "8 параллельных вставок одного тикера: выигрывает ровно одна"],
    ["PostgreSQL", "Внешние ключи не дают удалить брокера, тикер, сессию, эмитента"],
    ["PostgreSQL", "Последний статус каждой рекомендации: DISTINCT ON"],
    ["PostgreSQL", "Оконные функции по дивидендам: накопление, рост, последнее"],
    ["PostgreSQL", "100 000 позиций: индекс используется, сумма сходится"],
    ["ClickHouse", "Скользящее среднее и дневная доходность по реальным барам"],
    ["ClickHouse", "Рейтинг бумаг по доходности за 20 сессий (rank)"],
    ["ClickHouse", "ASOF JOIN: к каждой сделке последняя котировка"],
    ["ClickHouse", "200 000 сделок вперемешку: свечи совпадают с эталоном"],
    ["ClickHouse", "Исправленный бар заменяет старый, OPTIMIZE сжимает версии"],
    ["ClickHouse", "Месячные партиции: запрос читает 1 из 3"],
    ["PG ↔ CH", "Справочники идентичны в обеих БД, у каждого бара есть допуск"],
    ["PG ↔ CH", "Сделки сверяются со свечами: перемешивание, дубли, опоздавшие"]];
  const rows = [[{ text: "№", options: { bold: true, color: WHITE, fill: { color: NAVY } } }, { text: "БД", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
    { text: "Что проверяем", options: { bold: true, color: WHITE, fill: { color: NAVY } } }]]
    .concat(R.map((r, i) => [i + 1, r[0], r[1]].map((t, j) => ({ text: String(t), options: { bold: j < 2, color: INK, fill: { color: i % 2 ? SOFT : WHITE } } }))));
  s.addTable(rows.map(r => r.map(c => ({ text: c.text, options: Object.assign({ fontFace: "Calibri", fontSize: 12, valign: "middle", margin: [0.02, 0.1, 0.02, 0.1] }, c.options) }))),
    { x: 0.6, y: 1.3, w: 12.1, colW: [0.6, 1.6, 9.9], rowH: 0.34, border: { type: "solid", color: LINE, pt: 0.75 } });
  footer(s);
  s.addNotes("Файл tests/test_db_complex.py. Все 15 прошли на настоящих PostgreSQL 16 и ClickHouse 26. Проверяются именно возможности БД: агрегаты, транзакции, конкурентность, ссылочная целостность, оконные функции, объём, версии строк, партиции и согласованность двух хранилищ.");
}

// 11b. Подробные описания тестов
const TESTS = [["PostgreSQL", "test_01", "Портфель по эмитентам: GROUPING SETS", "Один запрос считает стоимость портфеля по клиенту и эмитенту, итог по клиенту и общий итог.", "2 клиента, 5 позиций; JOIN позиций, тикеров, инструментов и эмитентов; сверка с ручным расчётом.", "Клиент a — 31 000, клиент b — 54 300, всего 85 300. Разбивка по эмитентам совпала."], ["PostgreSQL", "test_02", "Откат транзакции при сбое", "Либо все изменения сохраняются, либо ни одно: частичных данных в БД не остаётся.", "Вставка заказчика, аккаунта и поручения; поручение с несуществующей сессией вызывает ошибку.", "Ошибка внешнего ключа; после отката в customers и owner_accounts 0 строк."], ["PostgreSQL", "test_03", "Параллельные вставки одного тикера", "Уникальность тикера держится даже при одновременной записи из разных соединений.", "8 потоков с барьером одновременно вставляют тикер NEWT под разными номерами.", "1 вставка успешна, 7 получили UniqueViolation; в таблице одна строка NEWT."], ["PostgreSQL", "test_04", "Ссылочная целостность при удалении", "Нельзя удалить то, на что ссылаются другие таблицы: ключи защищают справочники.", "Удаляем занятого брокера, тикер, сессию и эмитента; затем брокера без ссылок.", "Четыре удаления отклонены (ForeignKeyViolation), свободный брокер удалён, остался 1."], ["PostgreSQL", "test_05", "Последний статус записи: DISTINCT ON", "Журнал только дополняется; текущее состояние — последняя строка по каждой записи.", "3 рекомендации, статусы вставлены вперемешку: draft → approved → published, draft → rejected, draft.", "Запрос вернул published, rejected и draft ровно для своих записей."], ["PostgreSQL", "test_06", "Оконные функции по корпоративным событиям", "Накопление, рост к прошлой выплате и последняя выплата по каждой бумаге — за один запрос.", "5 дивидендов по 2 бумагам; SUM OVER, LAG и ROW_NUMBER с PARTITION BY.", "Накопление 10, 22, 37 и 5, 12; рост +20 % и +25 %; последние выплаты 15 и 7."], ["PostgreSQL", "test_07", "100 000 позиций: индекс и сумма", "На большом объёме поиск по клиенту идёт по индексу, а агрегат даёт точный результат.", "generate_series: 20 000 клиентов × 5 бумаг; EXPLAIN поиска клиента; сумма против формулы в Python.", "План с Index Scan, без Seq Scan; сумма 520 150 000 совпала; тест 1,5 с."], ["ClickHouse", "test_08", "Окна по реальным барам Мосбиржи", "Скользящее среднее и дневная доходность считаются внутри БД, а не в приложении.", "Бары SBER из API: avg OVER 5 строк и lagInFrame; сверка с Python на 4 днях.", "Более 60 сессий; значения совпали, у первого дня доходность 0."], ["ClickHouse", "test_09", "Рейтинг бумаг по доходности: rank", "Ранжирование бумаг за последние 20 сессий одним запросом с подзапросом и окном.", "row_number по убыванию даты, argMax и argMin цены, rank по доходности; порядок против Python.", "Порядок 5 бумаг и значения доходности совпали с независимым расчётом."], ["ClickHouse", "test_10", "ASOF JOIN: сделка и последняя котировка", "К каждой сделке подставляется котировка, действовавшая на её момент.", "3 котировки (в 0, 10, 20 с) и 5 сделок: до первой котировки, три внутри, одна по другому тикеру.", "Пусто, 99/101, 100/102, 101/103, пусто: все пять ответов совпали."], ["ClickHouse", "test_11", "200 000 сделок вперемешку → свечи", "Свечи верны на большом объёме независимо от порядка поступления.", "4 пачки по 50 000, порядок перемешан; сверка open, close, high, low, count, turnover на 40 минутах.", "480 свечей, объём 5 000 043, оборот 1 474 987 322,77 совпали; весь тест 2,6 с."], ["ClickHouse", "test_12", "Версии строк: исправленный бар", "Поправленные данные заменяют старые без удаления, а OPTIMIZE убирает лишние версии.", "Вставляем бар SBER с close + 1 и более поздним loaded_at; считаем строки с FINAL и без.", "321 строка физически, 320 через FINAL, close + 1; после OPTIMIZE — 320."], ["ClickHouse", "test_13", "Месячные партиции", "Запрос за один месяц читает только его партицию, а не всю таблицу.", "3 пачки по 1000 сделок (янв., февр., март); сумма за февраль; EXPLAIN indexes = 1.", "Партиции 202601, 202602, 202603; сумма 1000; в плане Parts 1/3."], ["PG ↔ CH", "test_14", "Справочники в двух БД одинаковы", "PostgreSQL и ClickHouse хранят одни и те же допуски; расхождение означало бы ошибку выгрузки.", "Сравниваем (сессия, тикер) → номинал, валюта, лот в обеих БД и с барами.", "320 пар совпали; у каждого бара есть допуск в PostgreSQL."], ["PG ↔ CH", "test_15", "Сверка сделок и свечей", "После перемешивания, дублей и опоздавших записей объём в свечах равен объёму сделок.", "3 сессии по 1000 сделок; повтор 900 штук и 2 вне часов торгов; сверка по каждой сессии.", "Принято 3000; повтор: 900 дублей, 2 отклонено, 0 принято; суммы совпали во всех сессиях."]];
for (let p = 0; p < TESTS.length; p += 3) {
  const s = base(false);
  title(s, `Тесты БД ${p + 1}–${p + 3}: суть и результат`);
  TESTS.slice(p, p + 3).forEach((t, k) => {
    const y = 1.3 + k * 1.8;
    card(s, 0.6, y, 12.1, 1.7);
    s.addText(String(p + k + 1), { x: 0.75, y: y + 0.15, w: 1.2, h: 0.8, fontFace: "Cambria", fontSize: 40, bold: true, color: NAVY, margin: 0, valign: "middle", isTextBox: true });
    s.addText(t[0], { x: 0.75, y: y + 1.0, w: 1.4, h: 0.4, fontFace: "Calibri", fontSize: 12, bold: true, color: t[0] === "ClickHouse" ? GOLD : TEAL, margin: 0, isTextBox: true });
    s.addText(t[2], { x: 2.3, y: y + 0.08, w: 10.2, h: 0.36, fontFace: "Calibri", fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle", isTextBox: true });
    [["СУТЬ", t[3]], ["КАК ПРОВЕРЯЕМ", t[4]], ["РЕЗУЛЬТАТ", t[5]]].forEach((c, j) => {
      const x = 2.3 + j * 3.5;
      s.addText(c[0], { x, y: y + 0.5, w: 3.3, h: 0.22, fontFace: "Calibri", fontSize: 10, bold: true, color: j === 2 ? "1E8A4C" : MUTED, margin: 0, isTextBox: true });
      s.addText(c[1], { x, y: y + 0.74, w: 3.3, h: 0.9, fontFace: "Calibri", fontSize: 12, color: INK, margin: 0, valign: "top", isTextBox: true });
    });
  });
  footer(s);
  s.addNotes(TESTS.slice(p, p + 3).map((t, k) => `Тест ${p + k + 1} (${t[1]} в tests/test_db_complex.py): ${t[2]}. Суть: ${t[3]} Проверка: ${t[4]} Результат: ${t[5]}`).join("\n\n"));
}

// 11. Тесты
{
  const s = base(false); title(s, "Тесты: 15 из 15 проходят");
  s.addChart(pres.charts.BAR, [{ name: "Тестов", labels: ["PostgreSQL", "ClickHouse", "PostgreSQL ↔ ClickHouse"], values: [7, 6, 2] }],
    { x: 0.6, y: 1.5, w: 7.8, h: 4.9, barDir: "bar", chartColors: [TEAL], showLegend: false, showValue: true, dataLabelPosition: "outEnd",
      dataLabelColor: INK, dataLabelFontSize: 12, catAxisLabelColor: INK, catAxisLabelFontSize: 13, valAxisLabelColor: MUTED, valAxisLabelFontSize: 11,
      valGridLine: { color: LINE, size: 0.5 }, catGridLine: { style: "none" }, catAxisOrientation: "maxMin", valAxisHidden: true });
  card(s, 8.8, 1.5, 3.9, 4.9, SOFT);
  s.addText("15", { x: 8.8, y: 1.7, w: 3.9, h: 1.3, fontFace: "Cambria", fontSize: 66, bold: true, color: NAVY, align: "center", valign: "middle", margin: 0, isTextBox: true });
  s.addText("тестов прошли на настоящих PostgreSQL 16 и ClickHouse 26", { x: 9.1, y: 3.1, w: 3.3, h: 0.9, fontFace: "Calibri", fontSize: 15, color: INK, align: "center", margin: 0, valign: "top", isTextBox: true });
  s.addText("Самые тяжёлые: 200 000 сделок за 2,5 с и 100 000 позиций за 1,4 с.", { x: 9.1, y: 4.2, w: 3.3, h: 1.6, fontFace: "Calibri", fontSize: 13, color: MUTED, align: "center", margin: 0, valign: "top", isTextBox: true });
  footer(s);
  s.addNotes("Файл tests/test_db_complex.py. Тесты нашли ошибку в схеме: проверка CHECK пропускала дивиденд без суммы из-за NULL. Исправлено.");
}

pres.writeFile({ fileName: out }).then(f => console.log("written", f));
