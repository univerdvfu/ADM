"""Без БД: контракт полей, типы 20,8 и валюта из 4 знаков, атрибуты производных."""
import pytest

from analytics_firm.contract import Reject, to_decimal_20_8, validate_trade
from analytics_firm.reference import pad_currency, validate_instrument
from conftest import instrument, trade


@pytest.mark.parametrize("field", ["user_id", "owner_id", "account_id", "customer_id",
                                   "broker_id"])
def test_participant_ids_are_rejected(field):
    with pytest.raises(Reject) as e:
        validate_trade(trade(1, "300.5", **{field: 7}))
    assert e.value.rule == "forbidden_field"


def test_unknown_and_missing_fields():
    with pytest.raises(Reject) as e:
        validate_trade(trade(1, "300.5", note="x"))
    assert e.value.rule == "unknown_field"
    row = trade(1, "300.5")
    del row["price"]
    with pytest.raises(Reject) as e:
        validate_trade(row)
    assert e.value.rule == "missing_field"


@pytest.mark.parametrize("price", [0, -1, "abc", "1.123456789", "1" + "0" * 12, "nan"])
def test_bad_prices(price):
    with pytest.raises(Reject):
        to_decimal_20_8(price)


def test_decimal_20_8_boundaries():
    assert str(to_decimal_20_8("20.8")) == "20.8"
    assert to_decimal_20_8("999999999999.12345678")


@pytest.mark.parametrize("q", [0, -5, 1.5, "x", True])
def test_bad_quantity(q):
    with pytest.raises(Reject):
        validate_trade(trade(1, "10", qty=q))


def test_currency_width_four():
    assert pad_currency("sur") == "SUR "
    assert pad_currency("RUB") == "RUB "
    assert len(pad_currency("USDT")) == 4
    for bad in ["", "RUBLE", "R1B", None]:
        with pytest.raises(Reject):
            pad_currency(bad)


def test_stock_cannot_have_derivative_attributes():
    with pytest.raises(Reject):
        validate_instrument(instrument(1, "X", contract_term="fixed"))


def test_future_fixed_needs_maturity_perpetual_forbids_it():
    ok = instrument(3, "SiZ6", instrument_type="future", contract_term="fixed",
                    maturity_date="2026-12-15")
    assert validate_instrument(ok)["contract_term"] == "fixed"
    with pytest.raises(Reject) as e:
        validate_instrument(instrument(3, "SiZ6", instrument_type="future",
                                       contract_term="fixed"))
    assert e.value.rule == "maturity_required"
    perp = instrument(4, "BTCP", instrument_type="future", contract_term="perpetual")
    assert validate_instrument(perp)["maturity_date"] is None
    with pytest.raises(Reject) as e:
        validate_instrument(dict(perp, maturity_date="2026-12-15"))
    assert e.value.rule == "maturity_forbidden"


def test_exercise_style_is_option_only():
    opt = instrument(5, "OPT", instrument_type="option", exercise_style="european")
    assert validate_instrument(opt)["exercise_style"] == "european"
    with pytest.raises(Reject):
        validate_instrument(dict(opt, exercise_style="bermudan"))
    with pytest.raises(Reject):
        validate_instrument(instrument(6, "F", instrument_type="future",
                                       contract_term="perpetual", exercise_style="american"))


def test_instrument_with_owner_id_rejected():
    with pytest.raises(Reject):
        validate_instrument(instrument(1, "X", owner_id=1))
