-- Консультирование (PostgreSQL): клиенты фирмы, портфели, корпоративные события,
-- неизменяемый журнал рекомендаций. В ClickHouse клиенты не попадают.

CREATE TABLE advisory_clients (
    client_id BIGINT PRIMARY KEY,
    alias VARCHAR(80) NOT NULL UNIQUE,
    risk_profile VARCHAR(12) NOT NULL CHECK (risk_profile IN ('conservative','moderate','aggressive')),
    horizon_days INT NOT NULL CHECK (horizon_days > 0),
    max_position_pct NUMERIC(5,2) NOT NULL CHECK (max_position_pct > 0 AND max_position_pct <= 100),
    status VARCHAR(12) NOT NULL DEFAULT 'active'
);

CREATE TABLE positions (
    client_id BIGINT NOT NULL REFERENCES advisory_clients,
    ticker_id BIGINT NOT NULL REFERENCES tickers,
    quantity BIGINT NOT NULL CHECK (quantity >= 0),
    avg_price NUMERIC(20,8) NOT NULL CHECK (avg_price > 0),
    PRIMARY KEY (client_id, ticker_id)
);

CREATE TABLE corporate_events (
    event_id BIGINT PRIMARY KEY,
    ticker_id BIGINT NOT NULL REFERENCES tickers,
    event_type VARCHAR(10) NOT NULL CHECK (event_type IN ('dividend','split')),
    ex_date DATE NOT NULL,
    amount NUMERIC(20,8),
    split_ratio NUMERIC(10,4),
    CHECK ((event_type = 'dividend' AND COALESCE(amount > 0, false) AND split_ratio IS NULL)
        OR (event_type = 'split' AND COALESCE(split_ratio > 0, false) AND amount IS NULL))
);

CREATE TABLE recommendations (
    rec_id UUID PRIMARY KEY,
    client_id BIGINT NOT NULL REFERENCES advisory_clients,
    ticker_id BIGINT NOT NULL REFERENCES tickers,
    action VARCHAR(4) NOT NULL CHECK (action IN ('buy','sell','hold')),
    risk_class VARCHAR(6) NOT NULL CHECK (risk_class IN ('low','medium','high')),
    method_version VARCHAR(30) NOT NULL,
    data_cutoff DATE NOT NULL,
    rationale TEXT NOT NULL,
    risk_disclosure TEXT NOT NULL,
    author VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE recommendation_status_events (
    event_id BIGSERIAL PRIMARY KEY,
    rec_id UUID NOT NULL REFERENCES recommendations,
    status VARCHAR(10) NOT NULL CHECK (status IN ('draft','approved','rejected','published')),
    actor VARCHAR(80) NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME; END $$ LANGUAGE plpgsql;
CREATE TRIGGER recommendations_immutable BEFORE UPDATE OR DELETE ON recommendations
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER status_events_immutable BEFORE UPDATE OR DELETE ON recommendation_status_events
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
