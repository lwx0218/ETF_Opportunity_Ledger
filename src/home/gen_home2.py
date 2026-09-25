# -*- coding: utf-8 -*-
"""三卡首页 v2：卡上带一层细节 + 三卡之间的连接 + 展开态。复用 gen_home 的 token / 细节层 / 往下滚。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import importlib.util, json, os, sys
import pandas as pd
spec = importlib.util.spec_from_file_location("g", f"{ROOT_S}/src/home/gen_home.py")
g = importlib.util.module_from_spec(spec); sys.argv = ["x"]; spec.loader.exec_module(g)
T, head, nav, TAIL, MONO, OUT = g.T, g.head, g.nav, g.TAIL, g.MONO, g.OUT

def spark(t, code, start, marks, w=280, h=64, shade=None):
    """迷你价格线：marks = [(date, label, accent?)]；shade = (from_date, to_date_or_None) 窗口铺底"""
    d = pd.read_csv(f"{ROOT_S}/data/kline_{code}.csv", parse_dates=["date"]); d = d[d.date >= start].reset_index(drop=True)
    n = len(d); ext = 14 if shade and shade[1] is None else 0
    X = lambda i: 2 + (w - 4) * i / (n - 1 + ext)
    lo, hi = d.close.min(), d.close.max(); Y = lambda v: 6 + (h - 12) * (1 - (v - lo) / (hi - lo))
    idx = lambda ds: int(d.index[d.date == pd.Timestamp(ds)][0])
    path = " ".join(("M" if i == 0 else "L") + f"{X(i):.1f} {Y(v):.1f}" for i, v in enumerate(d.close))
    out = ""
    if shade:
        a = X(idx(shade[0])); b = X(n - 1 + ext) if shade[1] is None else X(idx(shade[1]))
        out += f'<rect x="{a:.1f}" y="0" width="{b - a:.1f}" height="{h}" fill="{t["acc"]}" opacity="0.10"/>'
    out += f'<path d="{path}" fill="none" stroke="{t["ink2"]}" stroke-width="1.5"/>'
    for ds, lab, acc in marks:
        i = idx(ds); out += f'<circle cx="{X(i):.1f}" cy="{Y(d.close.iloc[i]):.1f}" r="3.5" fill="{t["acc"] if acc else t["ink"]}" stroke="{t["bg"]}" stroke-width="1.5"/>'
    return f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="display:block; overflow: visible;">{out}</svg>'

def kv(t, rows, size=13):
    return "".join(f'<div style="display: grid; grid-template-columns: 88px 1fr; gap: 12px; padding: 7px 0; border-bottom: 1px solid {t["hair"]}; font-size: {size}px; line-height: 1.45;"><span class="muted">{k}</span><span>{v}</span></div>' for k, v in rows)

def card(t, kind, eyebrow, num, num_cls, sentence, action, sub, spark_svg, spark_cap, rows, foot, big):
    w = 560 if big else 280
    return f'''
    <div style="flex: 0 0 auto; width: {w}px; opacity: {1 if big else 0.62}; display: flex; flex-direction: column; gap: {14 if big else 10}px; border-top: 1px solid {t['hair2']}; padding-top: 20px; margin-top: {0 if big else 36}px;">
      <div class="eyebrow">{eyebrow}</div>
      <div style="display: flex; align-items: baseline; gap: 18px;"><div class="mono {num_cls}" style="font-size: {68 if big else 40}px; line-height: 1; font-weight: 500; letter-spacing: -0.02em;">{num}</div><div style="font-size: {16 if big else 14}px; font-weight: 600; color: {t['acc']};">{action}</div></div>
      <div class="mono muted" style="font-size: 12px;">{sub}</div>
      <div style="font-size: {17 if big else 14}px; line-height: 1.55;">{sentence}</div>
      <div style="margin-top: 6px;">{spark_svg}<div class="mono muted" style="font-size: 11px; margin-top: 6px;">{spark_cap}</div></div>
      <div>{kv(t, rows, 13 if big else 12)}</div>
      <div class="mono" style="font-size: 12px; color: {t['acc']}; text-align: right;">{foot}</div>
    </div>'''

def connector(t, text, up=False):
    return f'''
    <div style="flex: 0 0 auto; width: 80px; margin-top: 236px; display: flex; flex-direction: column; align-items: center; gap: 8px;">
      <div style="width: 100%; height: 1px; background: {t['hair2']}; position: relative;"><span style="position: absolute; right: -2px; top: -6px; color: {t['hair2']}; font-size: 12px;">›</span></div>
      <div class="mono muted" style="font-size: 11px; line-height: 1.4; text-align: center;">{text}</div>
    </div>'''

def home(t):
    last_spark = spark(t, "510880", "2026-07-20", [("2026-08-05", "进", True), ("2026-09-02", "出", False)], w=280, h=56, shade=("2026-08-05", "2026-09-02"))
    cur_spark = spark(t, "512800", "2026-07-20", [("2026-09-07", "进", True)], w=560, h=96, shade=("2026-09-07", None))
    nxt_spark = spark(t, "501018", "2026-07-20", [("2026-08-05", "上次回踩", True)], w=280, h=56)
    return head(t, 1440, 1000) + nav(t) + f'''
  <div style="margin-top: 48px; display: flex; flex-direction: column; gap: 10px;">
    <div class="eyebrow">今天</div>
    <div style="font-size: 34px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.2;">一笔防守在跑，没有可进的进攻。</div>
    <div class="ink2" style="font-size: 15px;">源头链（半导体 · AI · 科创50）下跌中第 60 天；美股 QDII 溢价 10–23%；原油差一个回踩。</div>
  </div>
  <div style="margin-top: 36px; display: flex; align-items: flex-start; justify-content: center; gap: 0;">
    {card(t, "last", "上一次 · 防守 · 8-05 → 9-02", "+6.2%", "up", "红利，20 日到期出。对了。", "复盘", "沪深300 同期 −2.0% · 对源头少亏 10.9 个点", last_spark, "510880 · 7-20 → 9-14 · 铺底 = 持有窗口",
        [("为什么进", "源头两只下跌中、一只遇阻；红利排名 3"), ("为什么出", "9-02 满 20 日到期；源头未转强")], "点开 › 完整复盘", False)}
    {connector(t, "9-02 出<br>源头仍衰竭<br>9-07 换到银行")}
    {card(t, "cur", "当下 · 防守 · 银行 ETF 512800 · 第 5 / 20 天", "+2.5%", "up", "持有。源头三只仍在下跌中，到 10-12 或源头转强即退。", "持有", "沪深300 同期 −1.8% · 对源头少亏 7.7 个点 · 同类今年 2 次都对", cur_spark, "512800 · 7-20 → 9-14 · 铺底 = 窗口，到 10-12",
        [("为什么进", "9-07 源头 下跌中 / 遇阻 / 下跌中；银行是防守四个里最强（排名 2）"), ("什么时候退", "源头两只以上回到回踩或上升中 · 10-12 到期 · 银行自己破位"), ("证据", "险资/社保增配高股息 · 8 月股票 ETF 净赎回 · 两融 −12%")], "点开 › 为什么 · 价格 · 历史 · 证据", True)}
    {connector(t, "源头转强<br>或原油回踩<br>→ 切换")}
    {card(t, "next", "下一个 · 进攻 · 原油 501018 · 等回踩", "2.4 ATR", "neu", "离 20 日线还有这么远。回到线上不破位就是回踩，那时再进。排名第 1，溢价 3%。", "等", "上升中→回踩 今年中位 3 天（1–8）", nxt_spark, "501018 · 7-20 → 9-14 · 点 = 上次回踩 8-05",
        [("还差什么", "回踩到 20 日线且不破位"), ("物理催化", "待录：霍尔木兹 / EIA 周报")], "点开 › 条件与证据", False)}
  </div>
  <div style="margin-top: 40px; display: flex; justify-content: center; align-items: center; gap: 28px;" class="mono small muted">
    <span>‹ 上一次</span><span style="color: {t['ink']};">● 当下</span><span>下一个 ›</span>
  </div>
  <div style="margin-top: 36px; display: flex; justify-content: center;" class="mono small faint">↓ 今天不碰</div>
''' + TAIL

def expand(t):
    """展开态：点了中卡之后的中间帧——中卡撑开到全宽，侧卡压到边上，细节层四段接在卡的下方。"""
    cur_spark = spark(t, "512800", "2026-07-20", [("2026-09-07", "进", True)], w=280, h=64, shade=("2026-09-07", None))
    return head(t, 1440, 1180) + nav(t, "ETF 前向机会台账 › 机会 › <b>当下 · 银行</b>") + f'''
  <div style="margin-top: 32px; display: flex; align-items: flex-start; gap: 24px;">
    <div style="flex: 0 0 auto; width: 56px; opacity: 0.35; border-top: 1px solid {t['hair2']}; padding-top: 20px;"><div class="eyebrow" style="writing-mode: vertical-rl;">‹ 上一次 · 红利 +6.2%</div></div>
    <div style="flex: 1 1 auto; border-top: 1px solid {t['hair2']}; padding-top: 20px; display: flex; flex-direction: column; gap: 14px;">
      <div class="eyebrow">当下 · 防守 · 银行 ETF 512800 · 第 5 天</div>
      <div style="display: flex; align-items: baseline; gap: 18px;"><div class="mono up" style="font-size: 68px; line-height: 1; font-weight: 500; letter-spacing: -0.02em;">+2.5%</div><div style="font-size: 16px; font-weight: 600; color: {t['acc']};">持有</div><div class="mono muted small">沪深300 同期 −1.8% · 对源头少亏 7.7 个点 · 窗口 9-07 → 10-12</div></div>
      <div style="font-size: 17px;">持有。源头三只仍在下跌中，到 10-12 或源头转强即退。</div>
      <div style="display: grid; grid-template-columns: 300px minmax(0,1fr); gap: 24px; align-items: start;">
        <div>{cur_spark}<div class="mono muted" style="font-size: 11px; margin-top: 4px;">卡上的小图，展开后放大成下面的价格图</div></div>
        <div>{kv(t, [("为什么进", "9-07 源头 下跌中 / 遇阻 / 下跌中；银行是防守四个里最强（排名 2）"), ("什么时候退", "源头两只以上回到回踩或上升中 · 10-12 到期 · 银行自己破位")])}</div>
      </div>
      <div class="mono muted" style="font-size: 12px; margin-top: 6px;">↓ 卡下方接着展开：价格与窗口 · 同类历史 · 证据链（同细节层，见右边画板）</div>
      <div style="margin-top: 18px; padding-top: 18px; border-top: 1px solid {t['hair']};">
        <div style="font-size: 16px; font-weight: 600;"><span class="up">▲</span> 价格与窗口：进场后价格在 20 日线上方，窗口还剩 15 个交易日。</div>
        <div style="margin-top: 12px;">{g.price_svg(t).replace('width="1280"', 'width="1180"')}</div>
      </div>
    </div>
    <div style="flex: 0 0 auto; width: 56px; opacity: 0.35; border-top: 1px solid {t['hair2']}; padding-top: 20px;"><div class="eyebrow" style="writing-mode: vertical-rl;">下一个 · 原油 等回踩 ›</div></div>
  </div>
''' + TAIL

FILES = {"Main.dc.html": ("dark", home), "HomeLight.dc.html": ("light", home),
         "Detail.dc.html": ("dark", g.detail), "DetailLight.dc.html": ("light", g.detail), "Scroll.dc.html": ("dark", g.scroll), "ScrollLight.dc.html": ("light", g.scroll)}
for name, (theme, fn) in FILES.items():
    open(os.path.join(OUT, name), "w", encoding="utf-8").write(fn(T[theme]))

canvas = json.load(open(os.path.join(OUT, "canvas.json"), encoding="utf-8"))
p1 = [
    {"file": "Main.dc.html", "title": "首屏三卡 v2 · 深", "x": 0, "y": 0, "w": 1440, "h": 1000, "page": "page-1"},
    {"file": "Detail.dc.html", "title": "点开中卡 → 展开到底 · 深", "x": 1560, "y": 0, "w": 1440, "h": 1280, "page": "page-1"},
    {"file": "Scroll.dc.html", "title": "往下滚 · 深", "x": 3120, "y": 0, "w": 1440, "h": 1560, "page": "page-1"},
    {"file": "HomeLight.dc.html", "title": "首屏三卡 v2 · 浅", "x": 0, "y": 1420, "w": 1440, "h": 1000, "page": "page-1"},
    {"file": "DetailLight.dc.html", "title": "点开中卡 → 展开到底 · 浅", "x": 1560, "y": 1420, "w": 1440, "h": 1280, "page": "page-1"},
    {"file": "ScrollLight.dc.html", "title": "往下滚 · 浅", "x": 3120, "y": 1700, "w": 1440, "h": 1560, "page": "page-1"},
]
canvas["artboards"] = p1 + [a for a in canvas["artboards"] if a.get("page") == "page-2"]
canvas["annotations"] = [a for a in canvas["annotations"] if a.get("page") == "page-2"] + [
    {"id": "note-v2", "x": 0, "y": -220, "w": 720, "page": "page-1", "text": "v2.1 三卡：每张卡三层——① 数 + 动作词 + 一句话；② 小价格图（铺底 = 持有窗口）+ 两三行「为什么进 / 什么时候退」；③ 底部「点开 ›」写明点进去还有什么。\n三卡之间用一条细线和一句话连起来：上一次 9-02 到期出 → 源头仍衰竭 → 9-07 换到银行；当下 → 源头转强或原油回踩 → 切换到下一个。左右卡内容是中卡的同一模板缩小版，所以能层层递进。"},
    {"id": "note-expand", "x": 1560, "y": -160, "w": 620, "page": "page-1", "text": "点开中卡直接展开到底，就是这块。动效：卡撑到全宽、侧卡滑出、小图长成价格图、两行「为什么」展开成段——约 300ms 的一次过渡，不是一个停留页。"},
]
json.dump(canvas, open(os.path.join(OUT, "canvas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok")
