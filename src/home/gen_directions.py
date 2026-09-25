# -*- coding: utf-8 -*-
"""机会首页 · 三个方向稿 × 浅/深 → .dc.html 画板 + canvas.json（数字 = 2026-09-14 收盘，复权）"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import json, os
OUT = f"{ROOT_S}/outputs/home"
os.makedirs(OUT, exist_ok=True)

T = {
  "light": dict(bg="#fbfbf9", ink="#141413", ink2="#5c5b56", ink3="#8a8983", hair="#e4e3dd", hair2="#d3d2cb", acc="#2a78d6", accink="#1c5cab", wash="rgba(42,120,214,.08)"),
  "dark":  dict(bg="#131312", ink="#f1f0ec", ink2="#bdbcb3", ink3="#898781", hair="#2a2a28", hair2="#383835", acc="#3987e5", accink="#7fb0f0", wash="rgba(57,135,229,.14)"),
}
FONT = '"Geist",-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",system-ui,sans-serif'

def head(t, h):
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&amp;display=swap">
  <style>
    body {{ margin: 0; background: {t['bg']}; color: {t['ink']}; font-family: {FONT}; font-size: 13px; line-height: 1.55; -webkit-font-smoothing: antialiased; }}
    a {{ color: {t['accink']}; }} a:hover {{ color: {t['acc']}; }}
    .eyebrow {{ font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: {t['ink3']}; font-weight: 500; }}
    .h1 {{ font-size: 22px; font-weight: 600; letter-spacing: -.01em; line-height: 1.3; }}
    .h2 {{ font-size: 14px; font-weight: 600; }}
    .k {{ color: {t['ink3']}; font-size: 12px; }}
    .m {{ color: {t['ink2']}; }}
    .num {{ font-variant-numeric: tabular-nums; }}
    .acc {{ color: {t['accink']}; font-weight: 600; }}
    .row {{ display: grid; gap: 16px; padding: 10px 0; border-bottom: 1px solid {t['hair']}; align-items: baseline; }}
    .sec {{ border-top: 1px solid {t['hair']}; padding: 18px 0 22px; }}
    .chip {{ display: inline-block; padding: 1px 7px; border: 1px solid {t['hair2']}; border-radius: 3px; font-size: 11px; color: {t['ink2']}; }}
    .chip.on {{ border-color: {t['acc']}; color: {t['accink']}; }}
    .strike {{ color: {t['ink3']}; }}
  </style>
</helmet>
<div style="width: 1200px; min-height: {h}px; background: {t['bg']}; padding: 32px 40px 40px; box-sizing: border-box; display: flex; flex-direction: column; gap: 0;">
'''

TAIL = '''</div>
</x-dc>
</body>
</html>
'''

def header(t, title_tag):
    return f'''
  <div style="display: flex; justify-content: space-between; align-items: baseline; gap: 24px;">
    <div style="display: flex; flex-direction: column; gap: 4px;">
      <div class="eyebrow">ETF 前向机会台账 · 机会</div>
      <div class="h1">2026-09-14 收盘 <span class="k" style="font-weight: 400; font-size: 13px;">· 每日收盘后更新 · 方向 {title_tag}</span></div>
    </div>
    <div style="display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end;">
      <span class="chip">存量 · 收缩</span><span class="chip num">两融 2.65 万亿 · 自 6 月峰 −12%</span><span class="chip num">成交 1.6 万亿 · 连续 4 日 &lt;2 万亿</span><span class="chip num">沪深300 近 1 月 −3.7%</span>
    </div>
  </div>
'''

def verdict(t):
    return f'''
  <div class="sec" style="margin-top: 22px; border-top: 0; padding-top: 0;">
    <div class="eyebrow" style="margin-bottom: 8px;">今日结论</div>
    <div class="h1" style="font-size: 26px; max-width: 30em;">今天没有可进的进攻机会。防守仓在跑：银行，第 5 天，<span class="acc num">+2.5%</span>。</div>
    <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px; margin-top: 14px;">
      <div class="m">源头链（半导体 · AI · 科创50）下跌中 60 天，6 月高点回撤 −25% 到 −37%，还没出现「启动」或「平台突破」。</div>
      <div class="m">美股 QDII 三只溢价 10% 到 23%，预期极端，进攻条件不成立。</div>
      <div class="m">唯一在榜的进攻候选是原油：排名 1、溢价 3%，但离 20 日线 2.4 个 ATR，等回踩。</div>
    </div>
  </div>
'''

def current(t, compact=False):
    return f'''
  <div class="sec">
    <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px;"><div class="h2">当下机会</div><div class="k">只列两个条件都成立的；进行中的数字每天更新</div></div>
    <div class="row" style="grid-template-columns: 150px 1fr 1fr 1fr 1fr 90px;"><span class="k">机会</span><span class="k">触发</span><span class="k">进行中</span><span class="k">窗口</span><span class="k">预期（2026 同类）</span><span class="k">今天</span></div>
    <div class="row" style="grid-template-columns: 150px 1fr 1fr 1fr 1fr 90px;">
      <span><span class="chip on">防守</span> 银行 <span class="k num">512800</span></span>
      <span class="m num">9-07 · 源头三只 下跌中 / 遇阻 / 下跌中；银行排名 2</span>
      <span class="num">第 5 天 <b>+2.5%</b><br><span class="k">沪深300 −1.8% · 对源头少亏 +7.7%</span></span>
      <span class="num m">到 10-12（20 日）<br><span class="k">或源头转强即退出</span></span>
      <span class="num m">2 次：+0.4%、+8.2%<br><span class="k">样本太少，不作数</span></span>
      <span class="acc">持有</span>
    </div>
    <div class="row" style="grid-template-columns: 150px 1fr 90px; border-bottom: 0;">
      <span><span class="chip">进攻</span> <span class="strike">无</span></span>
      <span class="m num">4 个「回踩」信号在跑（煤炭 9-03、黄金 9-04、红利 9-08、纳指100 8-20），全部 −1% 到 −3%。这条规则今年 32 次、中位 −1.7%，不单独算机会——进攻要等物理催化。</span>
      <span class="k">不动</span>
    </div>
  </div>
'''

def nxt(t):
    rows = [
      ("原油", "501018", "回踩到 20 日线且不破位", "离均线 2.4 ATR · 溢价 3% · 排名 1", "上升中→回踩 中位 3 日（1–8）", "待录：霍尔木兹 / EIA 周报"),
      ("半导体链", "512760 · 159516 · 159819", "启动 或 平台突破", "下跌中 60 天 · 回撤 −25% 到 −37%", "下行→进场态 中位 14 日（5–21），本轮已远超", "Teardown 证据层"),
      ("全球半导体", "501225", "溢价 &lt;5% 再看底层", "溢价 14%（5-27 峰 48%，110 天降到这里）", "无先例", "同上"),
      ("纳指科技", "159509", "溢价回落", "溢价 23%，一个月没降", "—", "不看"),
    ]
    body = "".join(f'''
    <div class="row" style="grid-template-columns: 170px 1.2fr 1.3fr 1.2fr 1fr;{' border-bottom: 0;' if i == len(rows)-1 else ''}">
      <span>{n} <span class="k num">{c}</span></span><span class="m">{cond}</span><span class="m num">{now}</span><span class="k num">{ref}</span><span class="k">{cat}</span>
    </div>''' for i, (n, c, cond, now, ref, cat) in enumerate(rows))
    return f'''
  <div class="sec">
    <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px;"><div class="h2">下一个可能</div><div class="k">观察，不是动作；「还差什么」满足了才会升到上面那块</div></div>
    <div class="row" style="grid-template-columns: 170px 1.2fr 1.3fr 1.2fr 1fr;"><span class="k">候选</span><span class="k">还差什么</span><span class="k">现在</span><span class="k">参考周期（2026 数据）</span><span class="k">物理催化</span></div>
    {body}
  </div>
'''

def last(t):
    return f'''
  <div class="sec">
    <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px;"><div class="h2">上一次机会</div><div class="k">复盘：窗口、实际收益、对不对</div></div>
    <div class="row" style="grid-template-columns: 150px 1fr 1fr 1fr 70px;"><span class="k">机会</span><span class="k">窗口</span><span class="k">实际</span><span class="k">对照</span><span class="k">结果</span></div>
    <div class="row" style="grid-template-columns: 150px 1fr 1fr 1fr 70px;">
      <span><span class="chip on">防守</span> 红利 <span class="k num">510880</span></span><span class="m num">8-05 → 9-02 · 20 日到期</span><span class="num"><b>+6.2%</b></span><span class="k num">沪深300 −2.0% · 对源头少亏 +10.9%</span><span class="acc">对</span>
    </div>
    <div class="row" style="grid-template-columns: 150px 1fr 1fr 1fr 70px;">
      <span><span class="chip">进攻</span> 有色 <span class="k num">512400</span></span><span class="m num">8-13 回踩 → 9-10 到期</span><span class="num"><b>+2.2%</b></span><span class="k num">沪深300 −2.4%</span><span class="acc">小对</span>
    </div>
    <div class="row" style="grid-template-columns: 150px 1fr 1fr 1fr 70px; border-bottom: 0;">
      <span class="k">今年最大 / 最差</span><span class="m num">半导体设备 5-29 回踩 → 6-29 过热出</span><span class="num"><b>+59.0%</b></span><span class="k num">半导体 7-06 回踩 → 8-03 到期 <b>−29.5%</b></span><span class="k">尾部</span>
    </div>
  </div>
'''

def avoid(t):
    return f'''
  <div class="sec">
    <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px;"><div class="h2">今天不碰</div><div class="k">说不，比说买靠谱</div></div>
    <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px;">
      <div><div>美股 QDII 三只</div><div class="k num">纳指科技 溢价 23% · 全球半导体 14% · 纳指100 10.5%</div></div>
      <div><div>半导体 · AI · 科创50 · 半导体设备</div><div class="k num">下跌中，排名 13–17；不抄底，等启动</div></div>
      <div><div>农业</div><div class="k num">排名 3 但上周 −2.7%，9-10 粮食/农产品全线跌</div></div>
    </div>
  </div>
'''

def scorecard(t):
    return f'''
  <div class="sec">
    <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px;"><div class="h2">这套规则今年值多少</div><div class="k">预期收益从这里来，不是承诺</div></div>
    <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px;">
      <div class="num"><span class="k">进攻（回踩/启动/平台突破 + 排名前五 + 溢价 &lt;20%）</span><br>32 次 · 胜率 44% · 中位 <b>−1.7%</b> · 均值 +2.8% · 最好 +58% · 最差 −24%</div>
      <div class="num"><span class="k">防守（源头衰竭 → 红利/银行/黄金/现金里最强的）</span><br>2 次 · +0.4%、+8.2%</div>
    </div>
    <div class="m" style="margin-top: 10px; max-width: 70em;">进攻信号单独不值钱，钱在少数有物理催化的尾部（2 月原油、5–6 月半导体）。所以进攻必须叠加论点；防守单靠状态就能用。</div>
  </div>
'''

def howto(t):
    return f'''
  <div style="border-top: 1px solid {t['hair']}; padding-top: 12px; margin-top: 6px;" class="k">怎么用：先看结论；结论说有机会，再看「当下」那一行的「今天」列；「下一个可能」是观察不是动作；「上一次」是复盘；「今天不碰」是不做的事。数据每天收盘后更新，价格复权，QDII 与 LOF 的价格含溢价。</div>
'''

# ---------------- 方向 A · 结论优先 ----------------
def direction_a(t):
    return head(t, 1360) + header(t, "A · 结论优先") + verdict(t) + current(t) + nxt(t) + last(t) + avoid(t) + scorecard(t) + howto(t) + TAIL

# ---------------- 方向 B · 时间轴 ----------------
def timeline(t):
    return f'''
  <div class="sec" style="margin-top: 22px; border-top: 0; padding-top: 0;">
    <div class="eyebrow" style="margin-bottom: 10px;">机会的时间轴 · 7 月 → 10 月</div>
    <div style="position: relative; height: 150px; border-bottom: 1px solid {t['hair2']};">
      <div style="position: absolute; left: 0; right: 0; top: 96px; height: 1px; background: {t['hair2']};"></div>
      <!-- 上一次：8-05 → 9-02 -->
      <div style="position: absolute; left: 20%; width: 24%; top: 88px; height: 16px; background: {t['acc']}; opacity: .35; border-radius: 2px;"></div>
      <div style="position: absolute; left: 20%; top: 20px; display: flex; flex-direction: column; gap: 2px;"><span class="k">上一次 · 防守</span><span>红利 <span class="k num">8-05 → 9-02</span></span><span class="num"><b>+6.2%</b> <span class="k">沪深300 −2.0%</span></span></div>
      <!-- 当下：9-07 → 10-12 -->
      <div style="position: absolute; left: 49%; width: 6.5%; top: 88px; height: 16px; background: {t['acc']}; border-radius: 2px;"></div>
      <div style="position: absolute; left: 55.5%; width: 25%; top: 88px; height: 16px; border: 1px dashed {t['acc']}; box-sizing: border-box; border-radius: 2px;"></div>
      <div style="position: absolute; left: 49%; top: 20px; display: flex; flex-direction: column; gap: 2px;"><span class="k">当下 · 防守 · 进行中</span><span>银行 <span class="k num">9-07 → 最迟 10-12</span></span><span class="num"><b>+2.5%</b> <span class="k">第 5 天 · 沪深300 −1.8%</span></span></div>
      <!-- 下一个 -->
      <div style="position: absolute; left: 83%; width: 15%; top: 88px; height: 16px; border: 1px dashed {t['hair2']}; box-sizing: border-box; border-radius: 2px;"></div>
      <div style="position: absolute; left: 83%; top: 20px; display: flex; flex-direction: column; gap: 2px;"><span class="k">下一个 · 等条件</span><span>原油 <span class="k">等回踩</span></span><span class="k num">中位 3 日（1–8）</span></div>
      <!-- 今天线 -->
      <div style="position: absolute; left: 55.5%; top: 70px; width: 1px; height: 60px; background: {t['ink']};"></div>
      <div style="position: absolute; left: 56.5%; top: 118px;" class="k num">今天 9-14</div>
      <div style="position: absolute; left: 0; top: 118px;" class="k num">7-01</div>
      <div style="position: absolute; right: 0; top: 118px;" class="k num">10-12</div>
    </div>
  </div>
'''

def direction_b(t):
    body = f'''
  <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 32px;" class="sec">
    <div>
      <div class="h2" style="margin-bottom: 8px;">上一次 · 对了吗</div>
      <div class="row" style="grid-template-columns: 1fr;"><span><span class="chip on">防守</span> 红利 <span class="k num">8-05 → 9-02 · 20 日到期</span><br><span class="num"><b>+6.2%</b></span> <span class="k num">沪深300 −2.0% · 对源头少亏 +10.9%</span> <span class="acc">对</span></span></div>
      <div class="row" style="grid-template-columns: 1fr;"><span><span class="chip">进攻</span> 有色 <span class="k num">8-13 → 9-10</span><br><span class="num"><b>+2.2%</b></span> <span class="k num">沪深300 −2.4%</span> <span class="acc">小对</span></span></div>
      <div class="row" style="grid-template-columns: 1fr; border-bottom: 0;"><span class="k num">今年最大 +59.0%（半导体设备 5-29 → 6-29）· 最差 −29.5%（半导体 7-06 → 8-03）</span></div>
    </div>
    <div>
      <div class="h2" style="margin-bottom: 8px;">当下 · 该做什么</div>
      <div class="row" style="grid-template-columns: 1fr;"><span><span class="chip on">防守</span> 银行 <span class="k num">512800</span> <span class="acc">持有</span><br><span class="k num">9-07 触发：源头三只 下跌中 / 遇阻 / 下跌中；银行排名 2</span><br><span class="num">第 5 天 <b>+2.5%</b></span> <span class="k num">沪深300 −1.8% · 对源头少亏 +7.7%</span><br><span class="k num">窗口到 10-12，或源头转强即退出 · 2026 同类 2 次：+0.4%、+8.2%</span></span></div>
      <div class="row" style="grid-template-columns: 1fr; border-bottom: 0;"><span><span class="chip">进攻</span> <span class="strike">无</span><br><span class="k num">4 个回踩信号在跑，全部 −1% 到 −3%；规则今年中位 −1.7%，不算机会</span></span></div>
    </div>
    <div>
      <div class="h2" style="margin-bottom: 8px;">下一个 · 还差什么</div>
      <div class="row" style="grid-template-columns: 1fr;"><span>原油 <span class="k num">501018</span><br><span class="k num">差：回踩到 20 日线 · 现离均线 2.4 ATR · 溢价 3% · 中位 3 日</span></span></div>
      <div class="row" style="grid-template-columns: 1fr;"><span>半导体链<br><span class="k num">差：启动 / 平台突破 · 下跌中 60 天 · 回撤 −25% 到 −37% · 参考 14 日已远超</span></span></div>
      <div class="row" style="grid-template-columns: 1fr; border-bottom: 0;"><span>全球半导体 <span class="k num">501225</span><br><span class="k num">差：溢价 &lt;5% · 现 14%（峰 48%，110 天）</span></span></div>
    </div>
  </div>
'''
    return head(t, 920) + header(t, "B · 时间轴") + timeline(t) + body + avoid(t) + scorecard(t) + howto(t) + TAIL

# ---------------- 方向 C · 三问 ----------------
def direction_c(t):
    def qa(q, a, sub):
        return f'''
    <div class="row" style="grid-template-columns: 260px 1fr; padding: 18px 0;">
      <div class="h1" style="font-size: 20px;">{q}</div>
      <div style="display: flex; flex-direction: column; gap: 6px;"><div style="font-size: 16px; line-height: 1.5;">{a}</div><div class="k num">{sub}</div></div>
    </div>'''
    body = f'''
  <div class="sec" style="margin-top: 22px; border-top: 0; padding-top: 0;">
    {qa('现在能进什么？', '只有防守：银行，9-07 起，第 5 天 <b class="num">+2.5%</b>，持有到 10-12 或源头转强。进攻：<b>没有</b>。', '四个「回踩」信号在跑（煤炭、黄金、红利、纳指100），全部 −1% 到 −3%；这条规则今年 32 次中位 −1.7%，不算机会。')}
    {qa('什么在等条件？', '原油等回踩（现离均线 2.4 ATR，溢价 3%）；半导体链等启动（下跌中 60 天，回撤 −25% 到 −37%）；全球半导体等溢价回到 5% 以下（现 14%）。', '参考周期：上升中→回踩 中位 3 日；下行→进场态 中位 14 日，本轮已远超；溢价从 48% 到 14% 用了 110 天。')}
    {qa('上一次对了吗？', '对。红利 8-05 → 9-02，<b class="num">+6.2%</b>，沪深300 同期 −2.0%，对源头少亏 +10.9%。', '今年最大：半导体设备 5-29 回踩 → 6-29 过热出，+59.0%。最差：半导体 7-06 回踩 → 8-03 到期，−29.5%。')}
    <div class="row" style="grid-template-columns: 260px 1fr; padding: 18px 0; border-bottom: 0;">
      <div class="h1" style="font-size: 20px;">今天不做的事</div>
      <div style="display: flex; flex-direction: column; gap: 4px;"><div>不碰美股 QDII（溢价 10% 到 23%）</div><div>不抄底半导体 / AI / 科创50（下跌中，排名 13–17）</div><div>不追农业（上周 −2.7%，9-10 全线跌）</div></div>
    </div>
  </div>
'''
    return head(t, 900) + header(t, "C · 三问") + body + scorecard(t) + howto(t) + TAIL

# 方向 A 直接写成 DirectionA*.dc.html：原先写成 Main/MainDark，再靠一次手工复制改名，gen_home 随后覆盖 Main.dc.html；
# 2026-09-25 导入时改为直接写目标文件名，产物与 09-15 画布逐字节一致，且不再留下孤儿文件 MainDark.dc.html。
FILES = {
  "DirectionA.dc.html": ("light", direction_a), "DirectionADark.dc.html": ("dark", direction_a),
  "DirectionB.dc.html": ("light", direction_b), "DirectionBDark.dc.html": ("dark", direction_b),
  "DirectionC.dc.html": ("light", direction_c), "DirectionCDark.dc.html": ("dark", direction_c),
}
H = {"DirectionA.dc.html": 1360, "DirectionADark.dc.html": 1360, "DirectionB.dc.html": 920, "DirectionBDark.dc.html": 920, "DirectionC.dc.html": 900, "DirectionCDark.dc.html": 900}
for name, (theme, fn) in FILES.items():
    open(os.path.join(OUT, name), "w", encoding="utf-8").write(fn(T[theme]))

canvas = {
  "artboards": [
    {"file": "DirectionA.dc.html", "title": "A · 结论优先 · 浅", "x": 0, "y": 0, "w": 1200, "h": 1360},
    {"file": "DirectionB.dc.html", "title": "B · 时间轴 · 浅", "x": 1320, "y": 0, "w": 1200, "h": 920},
    {"file": "DirectionC.dc.html", "title": "C · 三问 · 浅", "x": 2640, "y": 0, "w": 1200, "h": 900},
    {"file": "DirectionADark.dc.html", "title": "A · 结论优先 · 深", "x": 0, "y": 1520, "w": 1200, "h": 1360},
    {"file": "DirectionBDark.dc.html", "title": "B · 时间轴 · 深", "x": 1320, "y": 1520, "w": 1200, "h": 920},
    {"file": "DirectionCDark.dc.html", "title": "C · 三问 · 深", "x": 2640, "y": 1520, "w": 1200, "h": 900},
  ],
  "annotations": [
    {"id": "note-brief", "x": 0, "y": -230, "w": 560, "text": "机会首页 · 三个方向稿（2026-09-14 收盘真实数据，复权）\n三个方向的内容一样：今日结论 / 当下机会 / 下一个可能 / 上一次 / 今天不碰 / 规则成绩单。不同的是「先看什么」。\n预期收益 = 这套规则今年的成绩分布，不是预测；样本小的地方写明「不作数」。"},
    {"id": "note-a", "x": 620, "y": -170, "w": 300, "text": "A · 结论优先\n先给一句话结论，再逐块往下。最像研究员的日报。\n代价：块多，得往下滚；每块都要读一行「怎么读」。"},
    {"id": "note-b", "x": 1320, "y": -170, "w": 300, "text": "B · 时间轴\n把上一次 / 当下 / 下一个放在一条时间线上，窗口和到来周期一眼看到。\n代价：机会稀少时时间线大半是空的；两个以上并行机会时会挤。"},
    {"id": "note-c", "x": 2640, "y": -170, "w": 300, "text": "C · 三问\n只回答三个问题加一张「不做」清单，最克制，最贴「做减法」。\n代价：没有表，细节要点开别的页；数字多了会变成长句。"},
    {"id": "note-names", "x": 960, "y": -120, "w": 300, "text": "状态改用白话，不再用 Kell 的名字：\n可进 = 启动 / 回踩 / 平台突破 / 超跌反弹\n危险 = 过热 / 破位 / 遇阻 / 阴跌"},
  ],
  "launch": {"view": "canvas"},
}
json.dump(canvas, open(os.path.join(OUT, "canvas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok", list(FILES))
