"""Indicator implementations (numpy), matching the Pine Script definitions used by the strategies."""
import math
import numpy as np


def supersmoother(x, length):
    """Ehlers 2-pole SuperSmoother, same recursion as the Pine `supersmoother()`."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.zeros(n)
    a1 = math.exp(-math.sqrt(2) * math.pi / length)
    b1 = 2 * a1 * math.cos(math.sqrt(2) * math.pi / length)
    c3 = -a1 * a1
    c2 = b1
    c1 = 1 - c2 - c3
    for i in range(n):
        p1 = out[i - 1] if i >= 1 else x[i]
        p2 = out[i - 2] if i >= 2 else (x[i - 1] if i >= 1 else x[i])
        out[i] = c1 * x[i] + c2 * p1 + c3 * p2
    return out


def true_range(h, l, c):
    pc = np.roll(c, 1)
    pc[0] = c[0]
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def rma(x, length):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < length:
        return out
    out[length - 1] = np.nanmean(x[:length])
    a = 1.0 / length
    for i in range(length, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def ema(x, length):
    x = np.asarray(x, dtype=float)
    out = np.empty(len(x))
    a = 2.0 / (length + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def atr(h, l, c, length):
    return rma(true_range(h, l, c), length)


def adx(h, l, c, length):
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = rma(true_range(h, l, c), length)
    pdi = 100 * rma(pdm, length) / tr
    mdi = 100 * rma(mdm, length) / tr
    dx = 100 * np.abs(pdi - mdi) / np.where(pdi + mdi == 0, np.nan, pdi + mdi)
    return rma(np.nan_to_num(dx), length)


def rolling_max(x, n):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    out[n - 1:] = sliding_window_view(x, n).max(axis=1)
    return out


def rolling_min(x, n):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    out[n - 1:] = sliding_window_view(x, n).min(axis=1)
    return out


def mrc_channel(c, h, l, length, inner, outer):
    """Mean Reversion Channel from the user's Pine script (SuperSmoother type)."""
    mean = supersmoother(c, length)
    rng = supersmoother(true_range(h, l, c), length)
    return (mean,
            mean + rng * math.pi * inner, mean - rng * math.pi * inner,
            mean + rng * math.pi * outer, mean - rng * math.pi * outer)
