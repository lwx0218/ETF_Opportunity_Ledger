#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etf_probe.py — A 股 ETF/LOF 轮动框架 v0 的数据探针（在 Faye 本机跑）

用途
  1. --smoke      只拉一只（588000）验证 akshare 接口是否可用
  2. --snapshot   只追加今天的全市场 ETF/LOF 快照（份额、折溢价、成交额）到 out/snapshots/
  3. 默认         解析容器 → 拉日线 + 净值 → 算状态向量 → 输出面板 CSV + 事件日排名

依赖
  pip install akshare pandas numpy
  akshare 的函数签名已对照 GitHub 源码（fund_etf_em.py / fund_em.py），但本脚本未在云沙盒执行过
  （沙盒对行情站点 403）。任何一步失败都会打印错误并继续，不会整段中断。

产出（默认 ./out）
  out/snapshots/etf_spot_YYYYMMDD.csv, lof_spot_YYYYMMDD.csv
  out/containers_resolved.csv     容器 → 实际选中的代码/名称
  out/panel_long.csv              date, line, container, code, close, ret, rs_1m, rs_3m, vol_pct, vol_20_250, prem, kell
  out/regime.csv                  date, turnover, turn_20_60, margin, margin_d20
  out/episodes.md                 5 个已核日期的事前(t-5)/当日容器排名
"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import argparse
import datetime as dt
import os
import sys
import time
import traceback

import numpy as np
import pandas as pd

try:
    import akshare as ak
except ImportError:
    print("请先 pip install akshare pandas numpy", file=sys.stderr)
    sys.exit(1)

# ----------------------------------------------------------------------------
# 容器定义：name, line, keywords(按顺序匹配名称), preferred(优先代码), kind(etf|lof|any)
# 脚本在快照里按关键字找名称，取成交额最大的那只；preferred 若在快照里就直接用。
# ----------------------------------------------------------------------------
CONTAINERS = [
    # ---- A 股线 ----
    ("宽基-沪深300", "A", ["沪深300ETF"], ["510300"], "etf"),
    ("宽基-中证500", "A", ["中证500ETF"], ["510500"], "etf"),
    ("宽基-科创50", "A", ["科创50ETF"], ["588000"], "etf"),
    ("宽基-创业板", "A", ["创业板ETF"], ["159915"], "etf"),
    ("半导体", "A", ["芯片ETF", "半导体ETF", "科创半导体ETF"], ["512760", "588170", "512480"], "etf"),
    ("半导体设备", "A", ["半导体设备ETF"], ["159516"], "etf"),
    ("AI算力", "A", ["人工智能ETF", "人工智能AIETF", "AIETF"], ["159819", "515070"], "etf"),
    ("通信光模块", "A", ["通信ETF"], ["515880"], "etf"),
    ("软件信创", "A", ["软件ETF"], ["515230"], "etf"),
    ("机器人", "A", ["机器人ETF"], ["562500"], "etf"),
    ("新能源", "A", ["光伏ETF", "新能源车ETF", "新能源ETF"], ["515790", "515030"], "etf"),
    ("军工", "A", ["军工ETF"], ["512660"], "etf"),
    ("医药", "A", ["医药ETF", "创新药ETF"], ["512010", "159992"], "etf"),
    ("消费", "A", ["消费ETF", "酒ETF"], ["159928", "512690"], "etf"),
    ("红利", "A", ["红利ETF", "红利低波ETF"], ["510880", "512890"], "etf"),
    ("银行", "A", ["银行ETF"], ["512800"], "etf"),
    ("券商", "A", ["证券ETF", "券商ETF"], ["512880"], "etf"),
    ("地产", "A", ["房地产ETF", "地产ETF"], ["512200"], "etf"),
    ("煤炭能源", "A", ["煤炭ETF", "能源ETF"], ["515220"], "etf"),
    ("有色", "A", ["有色金属ETF", "有色ETF"], ["512400"], "etf"),
    ("黄金", "A", ["黄金ETF"], ["518880"], "etf"),
    ("原油", "A", ["原油"], ["501018", "160723", "161129"], "lof"),
    ("农业", "A", ["农业ETF", "粮食ETF", "畜牧ETF", "豆粕ETF", "农牧ETF"], ["159825", "159985", "159867"], "etf"),
    ("港股科技", "A", ["恒生科技ETF", "恒生互联网ETF"], ["513180", "513330"], "etf"),
    ("现金", "A", ["银华日利", "短融ETF", "货币ETF"], ["511880", "511360"], "etf"),
    ("国债", "A", ["十年国债ETF", "国债ETF"], ["511260"], "etf"),
    # ---- QDII 线 ----
    ("Q-纳指100", "Q", ["纳指ETF", "纳斯达克ETF", "纳指100ETF"], ["513100"], "etf"),
    ("Q-纳指科技", "Q", ["纳指科技ETF"], ["159509"], "etf"),
    ("Q-标普500", "Q", ["标普500ETF"], ["513500"], "etf"),
    ("Q-全球半导体", "Q", ["全球芯片", "全球半导体"], ["501225"], "lof"),
    ("Q-中韩半导体", "Q", ["中韩半导体ETF"], ["513310"], "etf"),
    ("Q-日本", "Q", ["日经ETF", "日经225ETF"], ["513520"], "etf"),
]

BENCH_CODE = "510300"  # 论点 alpha 的基准

# 已核验的 5 个事件日（框架文档 §9）
EPISODES = [
    ("2026-03-02", "原油：霍尔木兹受阻，布伦特开盘 +13%，原油 LOF 溢价 >26%"),
    ("2026-05-11", "全球芯片 LOF 溢价 46–47%，上交所重点监控"),
    ("2026-06-01", "全球芯片LOF / 纳指科技ETF / 中韩半导体ETF 同日临停"),
    ("2026-08-31", "粮食ETF +6.3%，AI 核心标的低迷，半导体 ETF 净流出"),
    ("2026-09-10", "银行主题 ETF 全线涨，粮食/农产品全线跌，成交连续 4 日 <2 万亿"),
]


def log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def safe(fn, *a, **kw):
    """调用 akshare，失败返回 None 并打印一行错误。"""
    try:
        time.sleep(0.35)  # 东财限流
        return fn(*a, **kw)
    except Exception as e:  # noqa
        log(f"  ! {fn.__name__}({a}, {kw}) 失败: {type(e).__name__}: {str(e)[:160]}")
        return None


# ----------------------------------------------------------------------------
# 快照
# ----------------------------------------------------------------------------
def take_snapshot(out):
    d = dt.date.today().strftime("%Y%m%d")
    os.makedirs(os.path.join(out, "snapshots"), exist_ok=True)
    etf = safe(ak.fund_etf_spot_em)
    lof = safe(ak.fund_lof_spot_em)
    if etf is not None:
        p = os.path.join(out, "snapshots", f"etf_spot_{d}.csv")
        etf.to_csv(p, index=False, encoding="utf-8-sig")
        log(f"ETF 快照 {len(etf)} 行 → {p}")
    if lof is not None:
        p = os.path.join(out, "snapshots", f"lof_spot_{d}.csv")
        lof.to_csv(p, index=False, encoding="utf-8-sig")
        log(f"LOF 快照 {len(lof)} 行 → {p}")
    return etf, lof


def _col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def resolve_containers(etf, lof):
    """容器 → (code, name, kind)。"""
    rows = []
    frames = []
    if etf is not None:
        f = etf.copy()
        f["_kind"] = "etf"
        frames.append(f)
    if lof is not None:
        f = lof.copy()
        f["_kind"] = "lof"
        frames.append(f)
    if not frames:
        log("没有快照，无法解析容器；改用 preferred 代码")
        for name, line, kws, pref, kind in CONTAINERS:
            rows.append(dict(container=name, line=line, code=pref[0], name="", kind=kind))
        return pd.DataFrame(rows)

    allf = pd.concat(frames, ignore_index=True)
    ccode = _col(allf, "代码", "基金代码")
    cname = _col(allf, "名称", "基金简称")
    camt = _col(allf, "成交额")
    allf[camt] = pd.to_numeric(allf[camt], errors="coerce").fillna(0)

    for name, line, kws, pref, kind in CONTAINERS:
        hit = None
        # 1) preferred 代码若存在直接用
        for p in pref:
            m = allf[allf[ccode].astype(str) == p]
            if len(m):
                hit = m.iloc[0]
                break
        # 2) 否则按关键字取成交额最大
        if hit is None:
            for kw in kws:
                m = allf[allf[cname].astype(str).str.contains(kw, regex=False)]
                if kind != "any":
                    m = m[m["_kind"] == kind] if len(m[m["_kind"] == kind]) else m
                if len(m):
                    hit = m.sort_values(camt, ascending=False).iloc[0]
                    break
        if hit is None:
            log(f"  ? 容器「{name}」未解析到代码，使用 preferred {pref[0]}")
            rows.append(dict(container=name, line=line, code=pref[0], name="", kind=kind))
        else:
            rows.append(dict(container=name, line=line, code=str(hit[ccode]), name=str(hit[cname]), kind=hit["_kind"]))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 历史数据
# ----------------------------------------------------------------------------
def fetch_hist(code, kind, start, end):
    fn = ak.fund_lof_hist_em if kind == "lof" else ak.fund_etf_hist_em
    df = safe(fn, symbol=code, period="daily", start_date=start, end_date=end, adjust="")
    if df is None or not len(df):
        # LOF/ETF 互相兜底
        fn2 = ak.fund_etf_hist_em if kind == "lof" else ak.fund_lof_hist_em
        df = safe(fn2, symbol=code, period="daily", start_date=start, end_date=end, adjust="")
    if df is None or not len(df):
        return None
    df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
                            "成交量": "volume", "成交额": "amount"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["date", "open", "close", "high", "low", "volume", "amount"]].sort_values("date").reset_index(drop=True)


def fetch_nav(code, start, end):
    df = safe(ak.fund_etf_fund_info_em, fund=code, start_date=start, end_date=end)
    if df is None or not len(df):
        df = safe(ak.fund_open_fund_info_em, symbol=code, indicator="单位净值走势")
    if df is None or not len(df):
        return None
    df = df.rename(columns={"净值日期": "date", "单位净值": "nav"})
    if "date" not in df.columns or "nav" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    return df[["date", "nav"]].dropna().sort_values("date").reset_index(drop=True)


# ----------------------------------------------------------------------------
# 指标 + Kell 状态机 v0（规则见框架文档 §3.1）
# ----------------------------------------------------------------------------
def kell_states(df):
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
    out = df.copy()
    out["ema10"], out["ema20"], out["sma50"], out["sma200"], out["atr"], out["ext"], out["kell"] = ema10, ema20, sma50, sma200, atr, ext, st
    return out


def build_panel(resolved, start, end, out):
    panels = []
    bench = fetch_hist(BENCH_CODE, "etf", start, end)
    if bench is None:
        log("基准 510300 拉取失败，RS 将为空")
    else:
        bench = bench.set_index("date")["close"]

    for _, r in resolved.iterrows():
        log(f"拉 {r['container']} {r['code']} {r['name']}")
        h = fetch_hist(r["code"], r["kind"], start, end)
        if h is None:
            continue
        h = kell_states(h)
        h["ret"] = h["close"].pct_change()
        h["r21"] = h["close"].pct_change(21)
        h["r63"] = h["close"].pct_change(63)
        if bench is not None:
            b = bench.reindex(h["date"]).ffill().values
            bs = pd.Series(b, index=h.index)
            h["rs_1m"] = h["r21"] - bs.pct_change(21)
            h["rs_3m"] = h["r63"] - bs.pct_change(63)
        else:
            h["rs_1m"] = h["r21"]
            h["rs_3m"] = h["r63"]
        h["vol_pct"] = h["amount"].rolling(250, min_periods=60).rank(pct=True)
        h["vol_20_250"] = h["amount"].rolling(20).mean() / h["amount"].rolling(250, min_periods=60).mean()
        nav = fetch_nav(r["code"], start, end)
        if nav is not None:
            h = h.merge(nav, on="date", how="left")
            h["nav"] = h["nav"].ffill()
            h["prem"] = h["close"] / h["nav"] - 1
        else:
            h["prem"] = np.nan
        h["container"], h["line"], h["code"] = r["container"], r["line"], r["code"]
        panels.append(h[["date", "line", "container", "code", "close", "ret", "rs_1m", "rs_3m", "vol_pct", "vol_20_250", "prem", "ext", "kell"]])

    if not panels:
        log("面板为空")
        return None
    panel = pd.concat(panels, ignore_index=True).sort_values(["date", "container"])
    p = os.path.join(out, "panel_long.csv")
    panel.to_csv(p, index=False, encoding="utf-8-sig")
    log(f"面板 {len(panel)} 行 → {p}")
    return panel


def build_regime(start, end, out):
    rows = None
    sh = safe(ak.index_zh_a_hist, symbol="000001", period="daily", start_date=start, end_date=end)
    sz = safe(ak.index_zh_a_hist, symbol="399001", period="daily", start_date=start, end_date=end)
    if sh is not None and sz is not None:
        a = sh[["日期", "成交额"]].rename(columns={"日期": "date", "成交额": "sh"})
        b = sz[["日期", "成交额"]].rename(columns={"日期": "date", "成交额": "sz"})
        rows = a.merge(b, on="date", how="inner")
        rows["date"] = pd.to_datetime(rows["date"])
        rows["turnover"] = pd.to_numeric(rows["sh"], errors="coerce") + pd.to_numeric(rows["sz"], errors="coerce")
        rows["turn_20_60"] = rows["turnover"].rolling(20).mean() / rows["turnover"].rolling(60).mean()
        rows = rows[["date", "turnover", "turn_20_60"]]
    m = safe(ak.stock_margin_sse, start_date=start, end_date=end)
    if m is not None and len(m):
        cd = _col(m, "信用交易日期", "日期")
        cb = _col(m, "融资融券余额", "融资余额")
        mm = m[[cd, cb]].rename(columns={cd: "date", cb: "margin"})
        mm["date"] = pd.to_datetime(mm["date"].astype(str))
        mm["margin"] = pd.to_numeric(mm["margin"], errors="coerce")
        mm = mm.sort_values("date")
        mm["margin_d20"] = mm["margin"].pct_change(20)
        rows = mm if rows is None else rows.merge(mm, on="date", how="outer").sort_values("date")
    if rows is None:
        log("regime 数据全部失败")
        return None
    p = os.path.join(out, "regime.csv")
    rows.to_csv(p, index=False, encoding="utf-8-sig")
    log(f"regime {len(rows)} 行 → {p}")
    return rows


def write_episodes(panel, out):
    lines = ["# 事件日排名（事前 t-5 与当日）\n"]
    dates = sorted(panel["date"].unique())
    for d, why in EPISODES:
        d = pd.Timestamp(d)
        ds = [x for x in dates if x <= d]
        if not ds:
            continue
        d0 = ds[-1]
        d5 = ds[-6] if len(ds) >= 6 else ds[0]
        lines.append(f"\n## {d.date()} — {why}\n")
        for tag, dd in (("事前 t-5", d5), ("当日", d0)):
            s = panel[panel["date"] == dd].sort_values("rs_1m", ascending=False)
            lines.append(f"\n**{tag} {dd.date()}**\n")
            lines.append("| 容器 | rs_1m | rs_3m | vol_pct | vol_20_250 | prem | ext | kell |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for _, r in s.iterrows():
                f = lambda x, p=3: "" if pd.isna(x) else f"{x:.{p}f}"
                lines.append(f"| {r['container']} | {f(r['rs_1m'])} | {f(r['rs_3m'])} | {f(r['vol_pct'],2)} | {f(r['vol_20_250'],2)} | {f(r['prem'],3)} | {f(r['ext'],1)} | {r['kell']} |")
    p = os.path.join(out, "episodes.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    log(f"事件日排名 → {p}")


# ----------------------------------------------------------------------------
def smoke(start, end):
    log("smoke: fund_etf_spot_em")
    s = safe(ak.fund_etf_spot_em)
    if s is not None:
        print(s.head(3).to_string())
        print("列:", list(s.columns))
    log("smoke: fund_etf_hist_em 588000")
    h = safe(ak.fund_etf_hist_em, symbol="588000", period="daily", start_date=start, end_date=end, adjust="")
    if h is not None:
        print(h.tail(3).to_string())
    log("smoke: fund_etf_fund_info_em 588000")
    n = safe(ak.fund_etf_fund_info_em, fund="588000", start_date=start, end_date=end)
    if n is not None:
        print(n.tail(3).to_string())
    log("smoke: fund_lof_hist_em 501225")
    lf = safe(ak.fund_lof_hist_em, symbol="501225", period="daily", start_date=start, end_date=end, adjust="")
    if lf is not None:
        print(lf.tail(3).to_string())
    log("smoke: index_zh_a_hist 000001")
    ix = safe(ak.index_zh_a_hist, symbol="000001", period="daily", start_date=start, end_date=end)
    if ix is not None:
        print(ix.tail(2).to_string())
    log("smoke: stock_margin_sse")
    m = safe(ak.stock_margin_sse, start_date=start, end_date=end)
    if m is not None:
        print(m.tail(2).to_string())
    log("smoke 结束：以上任一段报错，把整段输出发给 Claude")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20250101", help="YYYYMMDD（留足 250 日算分位）")
    ap.add_argument("--end", default=dt.date.today().strftime("%Y%m%d"))
    ap.add_argument("--out", default=f"{ROOT_S}/outputs/probe")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    log(f"akshare {getattr(ak, '__version__', '?')}  window {a.start}–{a.end}")

    if a.smoke:
        smoke(a.start, a.end)
        return

    etf, lof = take_snapshot(a.out)
    if a.snapshot:
        return

    resolved = resolve_containers(etf, lof)
    resolved.to_csv(os.path.join(a.out, "containers_resolved.csv"), index=False, encoding="utf-8-sig")
    print(resolved.to_string())

    try:
        panel = build_panel(resolved, a.start, a.end, a.out)
        build_regime(a.start, a.end, a.out)
        if panel is not None:
            write_episodes(panel, a.out)
    except Exception:
        traceback.print_exc()
    log("完成。把 out/ 目录打包附到对话即可。")


if __name__ == "__main__":
    main()
