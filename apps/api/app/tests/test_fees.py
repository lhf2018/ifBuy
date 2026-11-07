from app.models import Instrument
from app.services.fees import calc_fee_cents, _default_rule


class _DummyDB:
    def query(self, *_a, **_k):
        return self

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return None


def test_cn_equity_buy_min_commission():
    inst = Instrument(
        symbol="600519.SH",
        ticker="600519",
        name="贵州茅台",
        instrument_type="equity",
        asset_class="equity_cn",
        market="CN",
        currency="CNY",
        lot_size=100,
        tick_size_e4=100,
    )
    # small notional -> min commission 5 yuan = 500 cents
    fee = calc_fee_cents(_DummyDB(), inst, "buy", notional_cents=10000)  # 100 yuan
    assert fee >= 500


def test_cn_etf_no_stamp_on_sell():
    rule = _default_rule("CN", "etf")
    assert rule.sell_stamp_tax_rate == "0"
