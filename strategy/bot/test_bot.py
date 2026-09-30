"""Offline unit tests: python3 -m pytest bot/test_bot.py  (or python3 bot/test_bot.py)"""
import hashlib, hmac, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logic
from delta_client import sign


def test_signature_format():
    ts, path, qs, body = "1700000000", "/v2/orders", "", '{"product_id":27,"size":1}'
    expected = hmac.new(b"secret", ("POST" + ts + path + qs + body).encode(), hashlib.sha256).hexdigest()
    assert sign("secret", "POST", ts, path, qs, body) == expected


def test_sizing_risk_and_leverage_cap():
    # $10k equity, 0.75% risk = $75; stop $60 away on ETH (0.01 ETH/contract) -> 1.25 ETH -> 125 contracts
    assert logic.contracts_for(10_000, 3000, 2940, 0.01, 0.0075, 3.0) == 125
    # very tight stop -> capped at 3x notional: 30k / 3000 / 0.01 = 1000 contracts
    assert logic.contracts_for(10_000, 3000, 2999.9, 0.01, 0.0075, 3.0) == 1000
    assert logic.contracts_for(10_000, 3000, 3000, 0.01, 0.0075, 3.0) == 0


def test_trailing_stop_only_ratchets():
    import numpy as np
    n = 1200
    c = np.linspace(100, 200, n)
    candles = [dict(time=i * 3600, open=x, high=x + 1, low=x - 1, close=x) for i, x in enumerate(c)]
    t, strat = logic.build(candles)
    s1 = logic.trailing_stop(strat, t, 1, t[-50], c[-50], c[-50] - 10)
    assert s1 >= c[-50] - 10 and s1 < c[-1]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
