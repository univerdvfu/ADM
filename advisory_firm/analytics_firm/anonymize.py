"""Задача обезличивания (H2): работает на стороне источника ДО выдачи данных фирме.
Это отдельная задача с белым списком, а не репликация таблиц. Таблица соответствий
псевдонимов и секрет остаются у источника и этой функцией не возвращаются."""
import hashlib
import hmac

from .contract import FORBIDDEN_FIELDS, TRADE_FIELDS

PSEUDONYMIZED = {"participant_id": "participant_alias"}


def pseudonym(secret: bytes, value) -> str:
    """HMAC-SHA256 с секретом; обычный хеш ID перебирается за секунды."""
    return hmac.new(secret, str(value).encode(), hashlib.sha256).hexdigest()[:16]


def export_market_slice(source_rows, secret: bytes, keep_alias=False):
    out = []
    for row in source_rows:
        clean = {k: v for k, v in row.items() if k in TRADE_FIELDS}   # белый список
        if keep_alias and "participant_id" in row:
            clean["participant_alias"] = pseudonym(secret, row["participant_id"])
        assert not set(clean) & FORBIDDEN_FIELDS
        out.append(clean)
    return out
