-- Аналитический контур фирмы (ClickHouse). Ни одной таблицы с ID участников.
-- Связи логические: ссылочную целостность и уникальность проверяет загрузчик.

CREATE TABLE IF NOT EXISTS ref_sessions (
    session_id UInt64,
    session_date Date,
    start_at DateTime64(3),
    end_at DateTime64(3),
    venue String,
    status String
) ENGINE = ReplacingMergeTree ORDER BY session_id;

-- Допуски инструментов к сессии: nominal_value Decimal(20,8), currency FixedString(4)
CREATE TABLE IF NOT EXISTS ref_session_instruments (
    session_id UInt64,
    ticker_id UInt64,
    instrument_id UInt64,
    ticker String,
    instrument_type String,
    nominal_value Decimal(20, 8),
    currency FixedString(4),
    contract_term String,        -- '', fixed, perpetual (фьючерсы)
    exercise_style String,       -- '', american, european (опционы)
    maturity_date Nullable(Date),
    lot_size UInt64,
    tick_size Decimal(20, 8),
    trading_status String
) ENGINE = ReplacingMergeTree ORDER BY (session_id, ticker_id);

CREATE TABLE IF NOT EXISTS market_trades (
    source_id String,
    event_id String,
    ticker_id UInt64,
    session_id UInt64,
    event_time DateTime64(6),
    price Decimal(20, 8),
    quantity UInt64
) ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (session_id, ticker_id, event_time, source_id, event_id);

CREATE TABLE IF NOT EXISTS market_quotes (
    source_id String,
    event_id String,
    ticker_id UInt64,
    session_id UInt64,
    event_time DateTime64(6),
    bid Nullable(Decimal(20, 8)),
    ask Nullable(Decimal(20, 8)),
    bid_qty UInt64,
    ask_qty UInt64
) ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (session_id, ticker_id, event_time, source_id, event_id);

CREATE TABLE IF NOT EXISTS agg_ohlcv_1m (
    ticker_id UInt64,
    session_id UInt64,
    minute DateTime,
    open Decimal(20, 8),
    high Decimal(20, 8),
    low Decimal(20, 8),
    close Decimal(20, 8),
    volume UInt64,
    trade_count UInt64,
    turnover Decimal(30, 8),
    computed_at DateTime64(3)
) ENGINE = ReplacingMergeTree(computed_at) ORDER BY (ticker_id, session_id, minute);

CREATE TABLE IF NOT EXISTS signals (
    ticker_id UInt64,
    session_id UInt64,
    method_version String,
    signal String,               -- up / down / flat / insufficient_data
    score Float64,
    ret Float64,
    turnover Decimal(30, 8),
    trade_count UInt64,
    as_of DateTime64(3)
) ENGINE = ReplacingMergeTree(as_of) ORDER BY (ticker_id, session_id, method_version);

CREATE TABLE IF NOT EXISTS recommendations (
    rec_id String,
    ticker_id UInt64,
    session_id UInt64,
    method_version String,
    action String,               -- buy / sell / hold
    horizon String,
    rationale String,
    author String,
    reviewer String,
    review_status String,        -- draft / approved / rejected / published
    published_at Nullable(DateTime64(3)),
    version DateTime64(6)
) ENGINE = ReplacingMergeTree(version) ORDER BY rec_id;

-- Служебные таблицы: журнал пакетов, отбракованные записи (без копии полей), аудит.
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id String,
    source_id String,
    accepted UInt64,
    duplicates UInt64,
    rejected UInt64,
    loaded_at DateTime64(3)
) ENGINE = MergeTree ORDER BY batch_id;

CREATE TABLE IF NOT EXISTS ingest_rejects (
    batch_id String,
    row_no UInt64,
    rule String,
    logged_at DateTime64(3)
) ENGINE = MergeTree ORDER BY (batch_id, row_no);

CREATE TABLE IF NOT EXISTS audit_log (
    ts DateTime64(3),
    actor String,
    role String,
    action String,
    object String
) ENGINE = MergeTree ORDER BY ts;

-- Дневные бары (для консультирования достаточно сессии, а не тика)
CREATE TABLE IF NOT EXISTS daily_bars (
    source_id String,
    ticker_id UInt64,
    session_id UInt64,
    trade_date Date,
    open Decimal(20, 8),
    high Decimal(20, 8),
    low Decimal(20, 8),
    close Decimal(20, 8),
    volume UInt64,
    turnover Decimal(30, 8),
    num_trades UInt64,
    loaded_at DateTime64(3)
) ENGINE = ReplacingMergeTree(loaded_at) ORDER BY (ticker_id, session_id);
