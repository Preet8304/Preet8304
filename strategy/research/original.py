"""Faithful port of the user's Pine Script 'Dual-Engine: Mean Reversion + Breakout' (default inputs, all filters off)."""
import numpy as np
from engine import Sleeve
from indicators import mrc_channel, rolling_min, rolling_max


class MeanReversion(Sleeve):
    name = "MR"

    def __init__(self, d, length=200, inner=1.0, outer=1.8, swing=10, use_be=True):
        self.o, self.h, self.l, self.c = d
        _, _, _, self.up2, self.lo2 = mrc_channel(self.c, self.h, self.l, length, inner, outer)
        self.swl, self.swh = rolling_min(self.l, swing), rolling_max(self.h, swing)
        self.use_be, self.warm = use_be, length

    def signal(self, i):
        if i < self.warm:
            return None
        h, l, c, up, lo = self.h, self.l, self.c, self.up2, self.lo2
        touched_s2 = any(l[i - k] <= lo[i - k] for k in range(3))
        touched_r2 = any(h[i - k] >= up[i - k] for k in range(3))
        if touched_s2 and c[i] > lo[i] and c[i] > c[i - 1]:
            return (1, min(self.swl[i], l[i]), None)
        if touched_r2 and c[i] < up[i] and c[i] < c[i - 1]:
            return (-1, max(self.swh[i], h[i]), None)
        return None

    def manage(self, i, p):
        if i <= p.entry_i:
            return False
        if p.side > 0:
            if self.l[i] <= self.lo2[i]:          # "Same Band Re-touch"
                return True
            if self.use_be and not p.extra.get("be") and self.h[i] >= p.entry + p.risk:
                p.stop, p.extra["be"] = p.entry, True
        else:
            if self.h[i] >= self.up2[i]:
                return True
            if self.use_be and not p.extra.get("be") and self.l[i] <= p.entry - p.risk:
                p.stop, p.extra["be"] = p.entry, True
        return False


class Breakout(Sleeve):
    name = "BO"

    def __init__(self, d, length=100, inner=1.0, outer=1.8, swing=10, use_be=True, min_hold=1):
        self.o, self.h, self.l, self.c = d
        _, _, _, self.up2, self.lo2 = mrc_channel(self.c, self.h, self.l, length, inner, outer)
        self.swl, self.swh = rolling_min(self.l, swing), rolling_max(self.h, swing)
        self.use_be, self.warm, self.min_hold = use_be, length, min_hold

    def signal(self, i):
        if i < self.warm:
            return None
        c, up, lo = self.c, self.up2, self.lo2
        if c[i] > up[i] and c[i - 1] <= up[i - 1]:
            return (1, min(self.swl[i], self.l[i]), None)
        if c[i] < lo[i] and c[i - 1] >= lo[i - 1]:
            return (-1, max(self.swh[i], self.h[i]), None)
        return None

    def manage(self, i, p):
        if i < p.entry_i + self.min_hold:
            return False
        if p.side > 0:
            if self.l[i] <= self.up2[i]:           # "Wick Touch" retouch of R2
                return True
            if self.use_be and not p.extra.get("be") and self.h[i] >= p.entry + p.risk:
                p.stop, p.extra["be"] = p.entry, True
        else:
            if self.h[i] >= self.lo2[i]:
                return True
            if self.use_be and not p.extra.get("be") and self.l[i] <= p.entry - p.risk:
                p.stop, p.extra["be"] = p.entry, True
        return False
