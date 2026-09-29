"""形态状态机（原 Kell 状态机，已改名）。从 src/rotation/etf_probe.py 的 kell_states 原样抽出，字段 kell → state；
规则见 docs/etf-rotation-framework-v0.md §3.1。只用 t 日及以前的数据（rolling / ewm / shift(1)），
与 kell_states 的逐日一致性由 tests/indicators 在构造数据上验证，与历史产物 data/panel_daily.csv 的一致性用 legacy-check 验证。

注意：放量条件（成交量 > 1.5 × 20 日均量）在没有成交量的序列上恒为假，启动 / 超跌反弹 / 过热 / 破位四态不会出现。
"""
from __future__ import annotations

import pandas as pd

STATES = ("POP", "XB", "BNB", "REV", "EXH", "DROP", "XBD", "BNBD", "TREND_UP", "TREND_DOWN", "NEUTRAL")


def form_states(df: pd.DataFrame) -> pd.DataFrame:
    """df：单个容器按日期升序的 close, high, low, volume。返回 ema10, ema20, sma50, sma200, atr14, ext, state。"""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    v20 = v.rolling(20).mean()
    ext = (c - ema10) / atr
    up = (ema10 > ema20) & (ema20 > sma50)
    down = (ema10 < ema20) & (ema20 < sma50)
    below20_prior = (c.shift(1) < ema20.shift(1)).rolling(20).mean()  # 前 20 日在 EMA20 下方的比例
    up_recent = up.shift(1).rolling(20).max().fillna(0) > 0
    hi20 = h.rolling(20).max().shift(1)
    lo20 = l.rolling(20).min().shift(1)
    rng20 = (h.rolling(20).max() - l.rolling(20).min()).shift(1)
    tight = rng20 <= 3 * atr
    hivol = v > 1.5 * v20

    st = pd.Series("NEUTRAL", index=df.index)
    st[up] = "TREND_UP"
    st[down] = "TREND_DOWN"
    st[down & (ext < -3) & hivol] = "REV"
    st[(below20_prior >= 0.6) & (c > ema10) & (c > ema20) & (c.shift(1) <= ema20.shift(1)) & hivol] = "POP"
    st[up & (l <= ema20 * 1.005) & (c >= ema20)] = "XB"
    st[up & tight & (c > hi20)] = "BNB"
    st[up & (ext > 3) & hivol] = "EXH"
    st[up_recent & (c < ema10) & (c < ema20) & (c.shift(1) >= ema20.shift(1)) & hivol] = "DROP"
    st[down & (h >= ema20 * 0.995) & (c < ema20)] = "XBD"
    st[down & tight & (c < lo20)] = "BNBD"
    return pd.DataFrame({"ema10": ema10, "ema20": ema20, "sma50": sma50, "sma200": sma200, "atr14": atr, "ext": ext, "state": st},
                        index=df.index)
