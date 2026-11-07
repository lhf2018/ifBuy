"""Integer money helpers.

- money_cents: 1 currency unit = 100 (CNY fen / USD cents)
- price_e4: 1 currency unit = 10_000
- qty_micros: 1 share = 1_000_000
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


MONEY_SCALE = Decimal(100)
PRICE_SCALE = Decimal(10_000)
QTY_SCALE = Decimal(1_000_000)


def d(value: str | int | float | Decimal) -> Decimal:
    return Decimal(str(value))


def money_to_cents(amount: Decimal | str | float) -> int:
    return int((d(amount) * MONEY_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_money(cents: int) -> Decimal:
    return (Decimal(cents) / MONEY_SCALE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_to_e4(price: Decimal | str | float) -> int:
    return int((d(price) * PRICE_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def e4_to_price(price_e4: int, places: int = 4) -> Decimal:
    q = Decimal("0.01") if places <= 2 else Decimal("0.0001")
    return (Decimal(price_e4) / PRICE_SCALE).quantize(q, rounding=ROUND_HALF_UP)


def qty_to_micros(qty: Decimal | str | float | int) -> int:
    return int((d(qty) * QTY_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def micros_to_qty(qty_micros: int) -> Decimal:
    return (Decimal(qty_micros) / QTY_SCALE).normalize()


def notional_cents(price_e4: int, qty_micros: int) -> int:
    """price * qty in cents: (p/1e4)*(q/1e6)*100 = p*q / 1e8"""
    return int((Decimal(price_e4) * Decimal(qty_micros) / Decimal(100_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
