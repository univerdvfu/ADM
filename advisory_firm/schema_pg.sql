-- Внешний реляционный контур источника (PostgreSQL): справочники, брокеры, заказчики,
-- счета владельцев, поручения. Это ПЕРВИЧНЫЙ слой: аналитической фирме не выдаётся.

CREATE TABLE issuers (
    issuer_id BIGINT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    country_code CHAR(2) NOT NULL
);

CREATE TABLE instruments (
    instrument_id BIGINT PRIMARY KEY,
    issuer_id BIGINT REFERENCES issuers,
    instrument_type VARCHAR(20) NOT NULL CHECK (instrument_type IN ('stock','future','option')),
    nominal_value NUMERIC(20,8) NOT NULL CHECK (nominal_value > 0),
    currency CHAR(4) NOT NULL,
    contract_term VARCHAR(10) CHECK (contract_term IN ('fixed','perpetual')),
    exercise_style VARCHAR(10) CHECK (exercise_style IN ('american','european')),
    maturity_date DATE,
    CHECK ((instrument_type = 'future') = (contract_term IS NOT NULL)),
    CHECK ((instrument_type = 'option') = (exercise_style IS NOT NULL)),
    CHECK (contract_term IS DISTINCT FROM 'fixed' OR maturity_date IS NOT NULL),
    CHECK (contract_term IS DISTINCT FROM 'perpetual' OR maturity_date IS NULL),
    CHECK (instrument_type <> 'stock' OR maturity_date IS NULL)
);

-- ticker — объект-ссылка, а не строка внутри инструмента
CREATE TABLE tickers (
    ticker_id BIGINT PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments,
    ticker VARCHAR(20) NOT NULL UNIQUE
);

CREATE TABLE trading_sessions (
    session_id BIGINT PRIMARY KEY,
    session_date DATE NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL CHECK (end_time > start_time),
    venue VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL
);

-- инструменты зависят от сессии
CREATE TABLE session_instruments (
    session_id BIGINT REFERENCES trading_sessions,
    ticker_id BIGINT REFERENCES tickers,
    trading_status VARCHAR(20) NOT NULL,
    lot_size BIGINT NOT NULL CHECK (lot_size > 0),
    tick_size NUMERIC(20,8) NOT NULL CHECK (tick_size > 0),
    PRIMARY KEY (session_id, ticker_id)
);

CREATE TABLE brokers (
    broker_id BIGINT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    license_status VARCHAR(20) NOT NULL
);

-- заказчик работает только через брокера
CREATE TABLE customers (
    customer_id BIGINT PRIMARY KEY,
    broker_id BIGINT NOT NULL REFERENCES brokers,
    display_alias VARCHAR(80) NOT NULL,
    UNIQUE (customer_id, broker_id)
);

-- отдельный обязательный аккаунт владельца; ticker_id — ссылка на объект
CREATE TABLE owner_accounts (
    account_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    broker_id BIGINT NOT NULL REFERENCES brokers,
    ticker_id BIGINT NOT NULL REFERENCES tickers,
    FOREIGN KEY (customer_id, broker_id) REFERENCES customers (customer_id, broker_id)
);

CREATE TABLE client_requests (
    request_id BIGINT PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES owner_accounts,
    ticker_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('buy','sell')),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    limit_price NUMERIC(20,8),
    FOREIGN KEY (session_id, ticker_id) REFERENCES session_instruments
);

-- служебное: задания загрузки, карантин (только коды правил), пользователи, аудит
CREATE TABLE ingest_jobs (
    batch_id VARCHAR(80) PRIMARY KEY,
    source_id VARCHAR(40) NOT NULL,
    raw_object VARCHAR(255) NOT NULL,
    accepted BIGINT NOT NULL, duplicates BIGINT NOT NULL, rejected BIGINT NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE quarantine (
    batch_id VARCHAR(80) NOT NULL REFERENCES ingest_jobs,
    row_no BIGINT NOT NULL,
    rule VARCHAR(60) NOT NULL,
    PRIMARY KEY (batch_id, row_no)
);
