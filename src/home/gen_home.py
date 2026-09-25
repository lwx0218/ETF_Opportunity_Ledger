# -*- coding: utf-8 -*-
"""机会首页 · 三卡方向稿（深色为主）· 3 块 × 浅/深 → .dc.html + canvas.json。token 取自 docs/design/teardown-tokens.css。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import json, os
import pandas as pd
OUT = f"{ROOT_S}/outputs/home"
os.makedirs(OUT, exist_ok=True)

T = {
  "dark":  dict(bg="#0f1012", ink="#f1f0ec", ink2="#c3c4c8", muted="#7e8189", faint="#4e5158", hair="#25272b", hair2="#33363b", acc="#7aa2f5", up="#f07a6a", down="#5dc391", neu="#7e8189", dim="0.16"),
  "light": dict(bg="#f7f6f3", ink="#1a1b1e", ink2="#44474d", muted="#8a8e96", faint="#b8bbc1", hair="#e4e2dd", hair2="#d3d0ca", acc="#2f5fc9", up="#c0392b", down="#2e7d5b", neu="#8a8e96", dim="0.14"),
}
SANS = '"Geist", system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif'
MONO = '"Geist Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace'

def head(t, w, h):
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&amp;family=Geist+Mono:wght@400;500&amp;display=swap">
  <style>
    body {{ margin: 0; background: {t['bg']}; color: {t['ink']}; font-family: {SANS}; font-size: 15px; line-height: 1.6; -webkit-font-smoothing: antialiased; }}
    a {{ color: {t['acc']}; }} a:hover {{ color: {t['ink']}; }}
    .mono {{ font-family: {MONO}; font-variant-numeric: tabular-nums; letter-spacing: 0.02em; }}
    .eyebrow {{ font-family: {MONO}; font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; color: {t['muted']}; }}
    .muted {{ color: {t['muted']}; }} .ink2 {{ color: {t['ink2']}; }} .faint {{ color: {t['faint']}; }}
    .small {{ font-size: 13px; }}
    .row {{ display: grid; gap: 24px; padding: 12px 0; border-bottom: 1px solid {t['hair']}; align-items: baseline; font-size: 16px; }}
    .up {{ color: {t['up']}; }} .down {{ color: {t['down']}; }} .neu {{ color: {t['neu']}; }}
    .nav {{ height: 64px; display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: {t['muted']}; }}
    .nav b {{ color: {t['ink']}; font-weight: 500; }}
  </style>
</helmet>
<div style="width: {w}px; min-height: {h}px; background: {t['bg']}; padding: 0 80px 64px; box-sizing: border-box; display: flex; flex-direction: column;">
'''
TAIL = '''</div>
</x-dc>
</body>
</html>
'''

def nav(t, crumb="ETF 前向机会台账 › <b>机会</b>"):
    return f'''
  <div class="nav"><span>{crumb}</span><span class="mono">As of 2026-09-14 收盘 · 窗口 20 日 · 每日收盘后更新</span></div>
'''

# ---------------- 1. 首屏三卡 ----------------
def card(t, eyebrow, num, num_cls, sentence, action, sub, scale, dimmed):
    big = scale == 1.0
    return f'''
    <div style="flex: 0 0 auto; width: {600 if big else 300}px; opacity: {1 if big else 0.6}; display: flex; flex-direction: column; gap: {18 if big else 12}px; border-top: 1px solid {t['hair2']}; padding-top: 22px; margin-top: {0 if big else 40}px;">
      <div class="eyebrow">{eyebrow}</div>
      <div class="mono {num_cls}" style="font-size: {68 if big else 40}px; line-height: 1; font-weight: 500; letter-spacing: -0.02em;">{num}</div>
      <div style="font-size: {17 if big else 14}px; line-height: 1.55;">{sentence}</div>
      <div style="display: flex; align-items: baseline; gap: 16px;"><span style="font-size: {16 if big else 14}px; font-weight: 600; color: {t['acc']};">{action}</span><span class="small muted">{sub}</span></div>
    </div>'''

def home(t):
    return head(t, 1440, 900) + nav(t) + f'''
  <div style="margin-top: 56px; display: flex; flex-direction: column; gap: 10px;">
    <div class="eyebrow">今天</div>
    <div style="font-size: 34px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.2;">一笔防守在跑，没有可进的进攻。</div>
  </div>
  <div style="margin-top: 48px; display: flex; align-items: flex-start; justify-content: center; gap: 40px;">
    {card(t, "上一次 · 防守 · 8-05 → 9-02", "+6.2%", "up", "红利，20 日到期。沪深300 同期 −2.0%，对源头少亏 10.9 个点。", "对了", "复盘", 0.78, True)}
    {card(t, "当下 · 防守 · 第 5 天", "+2.5%", "up", "银行在跑。源头三只（半导体 · AI · 科创50）仍在下跌中，持有到 10-12，或源头转强即退。", "持有", "沪深300 同期 −1.8% · 对源头少亏 7.7 个点", 1.0, False)}
    {card(t, "下一个 · 进攻 · 等回踩", "≈3 日", "neu", "原油排名第 1、溢价 3%，但离 20 日线 2.4 个 ATR。回踩不破位再进；上升中到回踩，今年中位 3 天。", "等", "还差一个条件", 0.78, True)}
  </div>
  <div style="margin-top: 44px; display: flex; justify-content: center; align-items: center; gap: 28px;" class="mono small muted">
    <span>‹ 上一次</span><span style="color: {t['ink']};">● 当下</span><span>下一个 ›</span>
  </div>
  <div style="margin-top: 60px; display: flex; justify-content: center;" class="mono small faint">↓ 今天不碰</div>
''' + TAIL

# ---------------- 2. 细节层 ----------------
def price_svg(t):
    a = pd.read_csv(f"{ROOT_S}/data/kline_512800.csv", parse_dates=["date"]); a = a[a.date >= "2026-06-15"].reset_index(drop=True)
    b = pd.read_csv(f"{ROOT_S}/data/kline_510300.csv", parse_dates=["date"]); b = b[b.date >= "2026-06-15"].reset_index(drop=True)
    W, H, L, R, TP, BT = 1280, 300, 56, 24, 20, 40
    n = len(a); i0 = int(a.index[a.date == "2026-09-07"][0])
    # 窗口到 10-12：向右延伸 20 个交易日的位置
    total = n + 20
    X = lambda i: L + (W - L - R) * i / (total - 1)
    e = a.close.iloc[i0]
    bi = b.close / b.close.iloc[i0] * e          # 沪深300 以进场日对齐
    lo, hi = min(a.close.min(), bi.min()) * 0.99, max(a.close.max(), bi.max()) * 1.01
    Y = lambda v: TP + (H - TP - BT) * (1 - (v - lo) / (hi - lo))
    p1 = " ".join(("M" if i == 0 else "L") + f"{X(i):.1f} {Y(v):.1f}" for i, v in enumerate(a.close))
    p2 = " ".join(("M" if i == 0 else "L") + f"{X(i):.1f} {Y(v):.1f}" for i, v in enumerate(bi))
    x0, x1, xn = X(i0), X(total - 1), X(n - 1)
    return f'''<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" style="display: block; overflow: visible;">
      <rect x="{x0:.1f}" y="{TP}" width="{x1 - x0:.1f}" height="{H - TP - BT}" fill="{t['acc']}" opacity="0.07"/>
      <line x1="{xn:.1f}" y1="{TP}" x2="{xn:.1f}" y2="{H - BT}" stroke="{t['hair2']}" stroke-dasharray="3 4"/>
      <line x1="{L}" y1="{Y(e):.1f}" x2="{x1:.1f}" y2="{Y(e):.1f}" stroke="{t['hair']}"/>
      <path d="{p2}" fill="none" stroke="{t['faint']}" stroke-width="1.5"/>
      <path d="{p1}" fill="none" stroke="{t['ink']}" stroke-width="2"/>
      <circle cx="{x0:.1f}" cy="{Y(e):.1f}" r="4" fill="{t['acc']}" stroke="{t['bg']}" stroke-width="2"/>
      <circle cx="{xn:.1f}" cy="{Y(a.close.iloc[-1]):.1f}" r="4" fill="{t['ink']}" stroke="{t['bg']}" stroke-width="2"/>
      <text x="{x0:.1f}" y="{TP - 6}" font-family="{MONO}" font-size="12" fill="{t['acc']}">9-07 进场 0.835</text>
      <text x="{xn + 8:.1f}" y="{Y(a.close.iloc[-1]) + 4:.1f}" font-family="{MONO}" font-size="12" fill="{t['ink']}">9-14 · 0.856 · +2.5%</text>
      <text x="{x1:.1f}" y="{H - 14}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{t['muted']}">窗口截止 10-12</text>
      <text x="{L}" y="{H - 14}" font-family="{MONO}" font-size="12" fill="{t['muted']}">6-15</text>
      <text x="{X(4):.1f}" y="{Y(bi.iloc[4]) - 8:.1f}" font-family="{MONO}" font-size="12" fill="{t['muted']}">沪深300（进场日对齐）</text>
    </svg>'''

def detail(t):
    return head(t, 1440, 1280) + nav(t, "ETF 前向机会台账 › 机会 › <b>当下 · 银行</b>") + f'''
  <div style="margin-top: 40px; display: grid; grid-template-columns: 520px minmax(0, 1fr); gap: 60px; align-items: end;">
    <div style="display: flex; flex-direction: column; gap: 14px;">
      <div class="eyebrow">当下 · 防守 · 银行 ETF 512800 · 第 5 天</div>
      <div class="mono up" style="font-size: 68px; line-height: 1; font-weight: 500; letter-spacing: -0.02em;">+2.5%</div>
      <div style="font-size: 17px;">持有。到 10-12，或源头转强即退。</div>
    </div>
    <div class="mono small muted" style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px;">
      <div><div>沪深300 同期</div><div style="color: {t['ink']}; font-size: 16px;">−1.8%</div></div>
      <div><div>对源头少亏</div><div style="color: {t['ink']}; font-size: 16px;">+7.7 个点</div></div>
      <div><div>窗口</div><div style="color: {t['ink']}; font-size: 16px;">9-07 → 10-12 · 20 日</div></div>
    </div>
  </div>

  <div style="margin-top: 48px; padding-top: 22px; border-top: 1px solid {t['hair']};">
    <div style="font-size: 16px; font-weight: 600;"><span class="down">▼</span> 为什么触发：源头三只两只以上在下跌中且有一只反弹遇阻，钱在往防守走；银行是防守四个里最强的。</div>
    <div class="row" style="grid-template-columns: 200px 1fr 1fr 1fr; margin-top: 8px;"><span class="muted small">9-07 源头状态</span><span>半导体 <span class="mono muted">下跌中 · 排名 16</span></span><span>AI算力 <span class="mono muted">遇阻 · 排名 14</span></span><span>科创50 <span class="mono muted">下跌中 · 排名 15</span></span></div>
    <div class="row" style="grid-template-columns: 200px 1fr;"><span class="muted small">9-07 目的地</span><span>银行 排名 2，上升中，离 20 日线 1.0 ATR；红利 4，黄金 7，现金 6</span></div>
    <div class="row" style="grid-template-columns: 200px 1fr; border-bottom: 0;"><span class="muted small">什么时候退</span><span>源头两只以上回到回踩 / 平台突破 / 上升中 → 退；或 10-12 到期 → 退；银行自己出现破位 → 退。</span></div>
  </div>

  <div style="margin-top: 40px; padding-top: 22px; border-top: 1px solid {t['hair']};">
    <div style="font-size: 16px; font-weight: 600;"><span class="up">▲</span> 价格与窗口：进场后价格在 20 日线上方，窗口还剩 15 个交易日。</div>
    <div style="margin-top: 16px;">{price_svg(t)}</div>
  </div>

  <div style="margin-top: 40px; padding-top: 22px; border-top: 1px solid {t['hair']}; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 60px;">
    <div>
      <div style="font-size: 16px; font-weight: 600;"><span class="neu">●</span> 同类历史：今年防守规则只响过 2 次，样本不够，不作数。</div>
      <div class="row" style="grid-template-columns: 1fr 1fr 1fr; margin-top: 8px;"><span class="muted small">3-10 红利</span><span class="mono">+0.4%</span><span class="muted small">对源头 +17.9 个点</span></div>
      <div class="row" style="grid-template-columns: 1fr 1fr 1fr; border-bottom: 0;"><span class="muted small">8-05 红利</span><span class="mono">+8.2%</span><span class="muted small">对源头 +10.9 个点</span></div>
    </div>
    <div>
      <div style="font-size: 16px; font-weight: 600;"><span class="neu">●</span> 物理证据链：防守不需要论点；这里放的是资金去向的证据。</div>
      <div class="row" style="grid-template-columns: 1fr 120px; margin-top: 8px;"><span>险资、社保持续增配高股息资产 <span class="muted small">界面 · 9-10</span></span><span class="mono muted small">consensus</span></div>
      <div class="row" style="grid-template-columns: 1fr 120px;"><span>8 月股票型 ETF 转为净赎回；货币 ETF 年内净流入 343 亿 <span class="muted small">新浪 · 9-07</span></span><span class="mono muted small">verified</span></div>
      <div class="row" style="grid-template-columns: 1fr 120px; border-bottom: 0;"><span>两融余额自 6 月峰 −12% <span class="muted small">东财 · 9-08</span></span><span class="mono muted small">verified</span></div>
    </div>
  </div>
''' + TAIL

# ---------------- 3. 往下滚：每屏一件事 ----------------
def screen(t, eyebrow, title, body, first=False):
    return f'''
  <div style="height: 720px; display: flex; flex-direction: column; justify-content: center; gap: 22px; border-top: {'0' if first else '1px solid ' + t['hair']};">
    <div class="eyebrow">{eyebrow}</div>
    <div style="font-size: 56px; font-weight: 600; letter-spacing: -0.025em; line-height: 1.1; max-width: 18em;">{title}</div>
    {body}
  </div>'''

def scroll(t):
    avoid = f'''
    <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 40px; margin-top: 12px; font-size: 17px;">
      <div><div>美股 QDII 三只</div><div class="muted small mono">纳指科技 溢价 23% · 全球半导体 14% · 纳指100 10.5%</div></div>
      <div><div>半导体 · AI · 科创50</div><div class="muted small mono">下跌中 60 天，排名 13–17；不抄底，等启动</div></div>
      <div><div>农业</div><div class="muted small mono">上周 −2.7%，9-10 全线跌</div></div>
    </div>'''
    score = f'''
    <div style="display: flex; gap: 80px; align-items: baseline; margin-top: 12px;">
      <div><div class="mono" style="font-size: 68px; line-height: 1;">44%</div><div class="muted small">进攻规则今年 32 次的胜率 · 中位 −1.7%</div></div>
      <div><div class="mono" style="font-size: 68px; line-height: 1;">+58%</div><div class="muted small">最好的一次（半导体设备 5-29）· 最差 −24%</div></div>
      <div><div class="mono" style="font-size: 68px; line-height: 1;">2 / 2</div><div class="muted small">防守规则今年两次都对 · +0.4%、+8.2%</div></div>
    </div>
    <div class="ink2" style="font-size: 17px; max-width: 40em;">钱在少数有物理催化的尾部，所以进攻必须叠加论点；防守单靠状态就能用。这些数字是预期的来源，不是承诺。</div>'''
    how = f'''
    <div style="display: flex; flex-direction: column; gap: 6px; font-size: 17px; max-width: 40em;">
      <div>1 · 先看首屏中间那张卡，它就是今天该做的事。</div>
      <div>2 · 左右两张是复盘和观察，不是动作。</div>
      <div>3 · 想知道为什么，点进卡；想知道不做什么，往下滚。</div>
    </div>'''
    return head(t, 1440, 1560) + nav(t) + screen(t, "往下滚 · 第二屏", "今天不碰。", avoid, first=True) + screen(t, "第三屏", "这套规则今年值多少。", score) + TAIL

FILES = {"Main.dc.html": ("dark", home), "HomeLight.dc.html": ("light", home), "Detail.dc.html": ("dark", detail), "DetailLight.dc.html": ("light", detail), "Scroll.dc.html": ("dark", scroll), "ScrollLight.dc.html": ("light", scroll)}
for name, (theme, fn) in FILES.items():
    open(os.path.join(OUT, name), "w", encoding="utf-8").write(fn(T[theme]))

old = ["DirectionA.dc.html", "DirectionADark.dc.html", "DirectionB.dc.html", "DirectionBDark.dc.html", "DirectionC.dc.html", "DirectionCDark.dc.html"]
canvas = {
  "pages": [{"id": "page-1", "name": "三卡首页"}, {"id": "page-2", "name": "旧稿 · 平铺三方向"}],
  "artboards": [
    {"file": "Main.dc.html", "title": "首屏三卡 · 深", "x": 0, "y": 0, "w": 1440, "h": 900, "page": "page-1"},
    {"file": "Detail.dc.html", "title": "细节层 · 深", "x": 1560, "y": 0, "w": 1440, "h": 1280, "page": "page-1"},
    {"file": "Scroll.dc.html", "title": "往下滚 · 深", "x": 3120, "y": 0, "w": 1440, "h": 2300, "page": "page-1"},
    {"file": "HomeLight.dc.html", "title": "首屏三卡 · 浅", "x": 0, "y": 1320, "w": 1440, "h": 900, "page": "page-1"},
    {"file": "DetailLight.dc.html", "title": "细节层 · 浅", "x": 1560, "y": 1320, "w": 1440, "h": 1280, "page": "page-1"},
    {"file": "ScrollLight.dc.html", "title": "往下滚 · 浅", "x": 3120, "y": 2440, "w": 1440, "h": 2300, "page": "page-1"},
    {"file": "DirectionA.dc.html", "title": "旧 A · 结论优先 · 浅", "x": 0, "y": 0, "w": 1200, "h": 1360, "page": "page-2"},
    {"file": "DirectionB.dc.html", "title": "旧 B · 时间轴 · 浅", "x": 1320, "y": 0, "w": 1200, "h": 920, "page": "page-2"},
    {"file": "DirectionC.dc.html", "title": "旧 C · 三问 · 浅", "x": 2640, "y": 0, "w": 1200, "h": 900, "page": "page-2"},
    {"file": "DirectionADark.dc.html", "title": "旧 A · 深", "x": 0, "y": 1520, "w": 1200, "h": 1360, "page": "page-2"},
    {"file": "DirectionBDark.dc.html", "title": "旧 B · 深", "x": 1320, "y": 1520, "w": 1200, "h": 920, "page": "page-2"},
    {"file": "DirectionCDark.dc.html", "title": "旧 C · 深", "x": 2640, "y": 1520, "w": 1200, "h": 900, "page": "page-2"},
  ],
  "annotations": [
    {"id": "note-home", "x": 0, "y": -200, "w": 620, "page": "page-1", "text": "首屏：三卡，中间放大、左右缩小并压暗（tokens 的 --dim）。每张正面只有 眉题 / 一个数 / 一句话 / 一个动作词。按 design-rules：页面即背景，无卡片框，只用间距、字号、四级灰做层级；数字用 Geist Mono；方向标记用 --sig-up/down（A 股红涨）。\n点左/右卡：那张滑到中间成为主角（这版是静态稿，不做交互）。"},
    {"id": "note-detail", "x": 1560, "y": -200, "w": 620, "page": "page-1", "text": "细节层：点进中卡。四块按你选的顺序：为什么触发/什么时候退 → 价格图+窗口 → 同类历史 → 证据链。每块第一行是「方向标记 + 一句结论」，再往下才是依据（design-rules 的结论先行）。价格图是 512800 真实近 3 月，沪深300 按进场日对齐做对照，窗口区用强调色 7% 铺底。"},
    {"id": "note-scroll", "x": 3120, "y": -200, "w": 620, "page": "page-1", "text": "往下滚：每屏一件事，56px 大标题 + 一段。第二屏 今天不碰；第三屏 这套规则今年值多少（三个大数）；第四屏 怎么用（三句）。"},
    {"id": "note-old", "x": 0, "y": -160, "w": 520, "page": "page-2", "text": "09-15 上午的三个平铺方向稿，留档对比用。"},
  ],
  "launch": {"view": "canvas", "page": "page-1"},
}
json.dump(canvas, open(os.path.join(OUT, "canvas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok")
