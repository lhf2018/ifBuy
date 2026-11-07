from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ErrorBody(BaseModel):
    code: str
    message: str


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    # base currency for display / return calc
    currency: str = Field(default="CNY", pattern="^(CNY|USD)$")
    base_currency: str | None = Field(default=None, pattern="^(CNY|USD)$")
    # multi-currency openings
    initial_cash_cny: float = Field(default=0, ge=0)
    initial_cash_usd: float = Field(default=0, ge=0)
    # legacy single field (still accepted)
    initial_cash: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _need_some_cash(self):
        if self.initial_cash is not None and self.initial_cash > 0:
            return self
        if self.initial_cash_cny > 0 or self.initial_cash_usd > 0:
            return self
        raise ValueError("至少提供一种货币的本金")


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern="^(active|archived)$")
    note: str | None = None


class CashFlowCreate(BaseModel):
    type: str = Field(pattern="^(deposit|withdraw)$")
    amount: float = Field(gt=0)
    currency: str | None = Field(default=None, pattern="^(CNY|USD)$")
    note: str | None = None


class FxExchangeCreate(BaseModel):
    from_currency: str = Field(pattern="^(CNY|USD)$")
    to_currency: str = Field(pattern="^(CNY|USD)$")
    from_amount: float = Field(gt=0)
    rate: float | None = Field(default=None, gt=0)
    note: str | None = None


class OrderCreate(BaseModel):
    client_order_id: str = Field(min_length=8, max_length=64)
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    qty: float = Field(gt=0)
    manual_price: float | None = Field(default=None, gt=0)
    expected_price: float | None = Field(default=None, gt=0)
    confirm_price_moved: bool = False
    note: str | None = None
    emotion_tag: str | None = None


class WatchlistCreate(BaseModel):
    symbol: str


class NoteCreate(BaseModel):
    account_id: int
    body: str
    kind: str = "review"
    order_id: int | None = None
    symbol: str | None = None
