"""Improved strategy components.

TrendBreakout: trade the user's MRC channel breakout (close crossing R2/S2) ONLY in the direction of the
    higher-timeframe trend, with an ATR stop and a chandelier (ATR) trailing exit that lets winners run.
TrendPullback: the user's mean-reversion idea (touch S2 and reverse) but ONLY with the trend
    (buy dips in uptrends / sell rips in downtrends), ATR stop, exit at the channel mean or trailing stop.
"""
import numpy as np
from engine import Sleeve
from indicators import mrc_channel, atr, ema, adx


class _Base(Sleeve):
    def __init__(self, d, ch_len, outer, trend_len, atr_len=14, stop_atr=2.0, trail_atr=3.0,
                 adx_len=14, adx_min=0.0, allow_short=True):
        self.o, self.h, self.l, self.c = d
        self.mean, _, _, self.up2, self.lo2 = mrc_channel(self.c, self.h, self.l, ch_len, 1.0, outer)
        self.atr = atr(self.h, self.l, self.c, atr_len)
        self.trend = ema(self.c, trend_len)
        self.adx = adx(self.h, self.l, self.c, adx_len) if adx_min > 0 else None
        self.stop_atr, self.trail_atr, self.adx_min = stop_atr, trail_atr, adx_min
        self.allow_short = allow_short
        self.warm = max(ch_len, trend_len, 3 * adx_len)

    def _regime(self, i):
        up = self.c[i] > self.trend[i] and self.trend[i] > self.trend[i - 24]
        dn = self.c[i] < self.trend[i] and self.trend[i] < self.trend[i - 24]
        if self.adx is not None and not self.adx[i] >= self.adx_min:
            return 0
        return 1 if up else (-1 if dn else 0)

    def _trail(self, i, p):
        """Chandelier trailing stop, ratchets only in the trade's favour."""
        if p.side > 0:
            p.extra["hh"] = max(p.extra.get("hh", p.entry), self.h[i])
            p.stop = max(p.stop, p.extra["hh"] - self.trail_atr * self.atr[i])
        else:
            p.extra["ll"] = min(p.extra.get("ll", p.entry), self.l[i])
            p.stop = min(p.stop, p.extra["ll"] + self.trail_atr * self.atr[i])


class TrendBreakout(_Base):
    name = "TB"

    def signal(self, i):
        if i < self.warm or np.isnan(self.atr[i]):
            return None
        r = self._regime(i)
        c = self.c
        if r > 0 and c[i] > self.up2[i] and c[i - 1] <= self.up2[i - 1]:
            return (1, c[i] - self.stop_atr * self.atr[i], None)
        if r < 0 and self.allow_short and c[i] < self.lo2[i] and c[i - 1] >= self.lo2[i - 1]:
            return (-1, c[i] + self.stop_atr * self.atr[i], None)
        return None

    def manage(self, i, p):
        self._trail(i, p)
        # trend regime flipped against the position -> exit
        return (p.side > 0 and self.c[i] < self.trend[i]) or (p.side < 0 and self.c[i] > self.trend[i])


class TrendPullback(_Base):
    name = "TP"

    def signal(self, i):
        if i < self.warm or np.isnan(self.atr[i]):
            return None
        r = self._regime(i)
        h, l, c = self.h, self.l, self.c
        if r > 0 and any(l[i - k] <= self.lo2[i - k] for k in range(3)) and c[i] > self.lo2[i] and c[i] > c[i - 1]:
            return (1, min(l[i - 2:i + 1].min(), c[i] - self.stop_atr * self.atr[i]), None)
        if r < 0 and self.allow_short and any(h[i - k] >= self.up2[i - k] for k in range(3)) \
                and c[i] < self.up2[i] and c[i] < c[i - 1]:
            return (-1, max(h[i - 2:i + 1].max(), c[i] + self.stop_atr * self.atr[i]), None)
        return None

    def manage(self, i, p):
        self._trail(i, p)
        return (p.side > 0 and self.c[i] < self.trend[i]) or (p.side < 0 and self.c[i] > self.trend[i])
