"""Контракт входных данных: белый список полей и проверка типов (уровни 2-3)."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

FORBIDDEN_FIELDS = {"user_id", "owner_id", "account_id", "customer_id",
                    "broker_id", "participant_id", "client_id"}
TRADE_FIELDS = ("source_id", "event_id", "ticker_id", "session_id",
                "event_time", "price", "quantity")
MAX_UINT64 = 2 ** 64 - 1


class Reject(Exception):
    def __init__(self, rule):
        super().__init__(rule)
        self.rule = rule


def to_decimal_20_8(value, rule="bad_decimal"):
    """Decimal(20,8): до 12 цифр целой части и до 8 после запятой."""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise Reject(rule)
    if not d.is_finite() or d <= 0:
        raise Reject(rule)
    sign, digits, exp = d.as_tuple()
    frac = -exp if exp < 0 else 0
    whole = len(digits) + exp if exp < 0 else len(digits) + exp
    if frac > 8 or whole > 12:
        raise Reject(rule)
    return d


def to_uint(value, rule="bad_integer", positive=True):
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        raise Reject(rule)
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise Reject(rule)
    if n < (1 if positive else 0) or n > MAX_UINT64:
        raise Reject(rule)
    return n


def parse_time(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        raise Reject("bad_time")


def validate_trade(raw):
    """Возвращает нормализованную запись или бросает Reject(rule)."""
    keys = set(raw)
    if keys & FORBIDDEN_FIELDS:
        raise Reject("forbidden_field")
    if keys - set(TRADE_FIELDS):
        raise Reject("unknown_field")
    if keys != set(TRADE_FIELDS):
        raise Reject("missing_field")
    source_id, event_id = str(raw["source_id"]).strip(), str(raw["event_id"]).strip()
    if not source_id or not event_id:
        raise Reject("empty_key")
    return {
        "source_id": source_id,
        "event_id": event_id,
        "ticker_id": to_uint(raw["ticker_id"], "bad_ticker_id"),
        "session_id": to_uint(raw["session_id"], "bad_session_id"),
        "event_time": parse_time(raw["event_time"]),
        "price": to_decimal_20_8(raw["price"], "bad_price"),
        "quantity": to_uint(raw["quantity"], "bad_quantity"),
    }


BAR_FIELDS = ("source_id", "ticker_id", "session_id", "trade_date", "open", "high", "low", "close",
              "volume", "turnover", "num_trades")


def _turnover(value):
    """Decimal(30,8), не отрицательный: до 22 цифр целой части и 8 дробных."""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise Reject("bad_turnover")
    if not d.is_finite() or d < 0:
        raise Reject("bad_turnover")
    _, digits, exp = d.as_tuple()
    frac = -exp if exp < 0 else 0
    if frac > 8 or len(digits) + exp > 22:
        raise Reject("bad_turnover")
    return d


def validate_bar(raw):
    """Дневной бар: те же правила, что у сделок (белый список, запрет ID, Decimal(20,8)),
    плюс согласованность цен внутри бара. Возвращает запись или бросает Reject(rule)."""
    keys = set(raw)
    if keys & FORBIDDEN_FIELDS:
        raise Reject("forbidden_field")
    if keys - set(BAR_FIELDS):
        raise Reject("unknown_field")
    if keys != set(BAR_FIELDS):
        raise Reject("missing_field")
    source_id = str(raw["source_id"]).strip()
    if not source_id:
        raise Reject("empty_key")
    day = raw["trade_date"]
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            raise Reject("bad_date")
    if not isinstance(day, date):
        raise Reject("bad_date")
    op, hi, lo, cl = (to_decimal_20_8(raw[k], "bad_price") for k in ("open", "high", "low", "close"))
    if hi < lo:
        raise Reject("high_below_low")
    if not (lo <= op <= hi) or not (lo <= cl <= hi):
        raise Reject("price_outside_range")
    return {"source_id": source_id,
            "ticker_id": to_uint(raw["ticker_id"], "bad_ticker_id"),
            "session_id": to_uint(raw["session_id"], "bad_session_id"),
            "trade_date": day, "open": op, "high": hi, "low": lo, "close": cl,
            "volume": to_uint(raw["volume"], "bad_volume", positive=False),
            "turnover": _turnover(raw["turnover"]),
            "num_trades": to_uint(raw["num_trades"], "bad_count", positive=False)}
