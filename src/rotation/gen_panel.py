# -*- coding: utf-8 -*-
"""生成 2026 ETF 轮动面板（单文件 HTML，供 Artifact 发布）。读 data/panel.json。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import json, os

J = json.load(open(f"{ROOT_S}/data/panel.json", encoding="utf-8"))

# 分组（面板行序）
GROUPS = [
    ("宽基", ["宽基-沪深300", "宽基-科创50"]),
    ("科技 · AI", ["半导体", "半导体设备", "AI算力", "通信"]),
    ("周期 · 商品", ["有色", "煤炭", "黄金", "原油", "农业"]),
    ("防守", ["红利", "银行", "现金"]),
    ("QDII（价格含溢价）", ["Q-全球半导体", "Q-纳指科技", "Q-纳指100"]),
]
CODES = {"宽基-沪深300": "510300", "宽基-科创50": "588000", "半导体": "512760", "半导体设备": "159516", "AI算力": "159819",
         "通信": "515880", "有色": "512400", "煤炭": "515220", "黄金": "518880", "原油": "501018", "农业": "159825",
         "红利": "510880", "银行": "512800", "现金": "511880", "Q-全球半导体": "501225", "Q-纳指科技": "159509", "Q-纳指100": "513100"}
J["groups"] = GROUPS
J["codes"] = CODES

VERDICT = {
    "E1": ("通过", "目的地事前在榜：t−5 相对强弱排第 2，成交额是过去一年均值的 3.9 倍，趋势态；但溢价已到 10%，预期从「未定价」进入「部分定价」。t−5 起 20 个交易日 +94%（价格含溢价）对沪深300 −5%。源头当时没有衰竭——2 月半导体还没挤，这是纯催化剂事件。"),
    "E2": ("通过", "极端被标出：t−5 溢价 24%、排名 1、成交 2.8 倍。按规则「溢价 >20% 不进」——代价是错过之后 20 日 +38%，收益是躲过 5-27 之后的 −30%。拥挤是条件不是触发，在这里被再次验证：极端状态持续了 4 周才塌。"),
    "E3": ("通过", "极端持续：t−5 溢价 46%，之后 5/10/20 日 −2.5% / −7.6% / −6.3%。退出信号正确，但真正的塌方（−30%）在两个月后，中间还有一次反弹。"),
    "E4": ("部分", "t−5 排名 6，差一位没进前五；但形态状态在 t−2、t−1 给出平台突破，源头半导体 / AI / 科创50 同期是遇阻（反弹到均线被压回）。t−5 起 10 日 +7.5% 对沪深300 +0.2%。注意容器口径：当天 +6% 的是粮食 ETF，这里的农业容器是 159825，涨得少。"),
    "E5": ("通过", "t−5 排名 4，趋势态；源头三只全部下行态。t−5 起 7 日 +1.9% 对沪深300 −1.5%，源头 −4.8%——防守模式「少亏」的样子。样本到 9-14 为止，还太短。"),
}
for ep in J["episodes"]:
    ep["verdict"], ep["verdict_text"] = VERDICT[ep["id"]]

data_js = json.dumps(J, ensure_ascii=False, separators=(",", ":"))

HTML = r'''<title>2026 ETF 轮动面板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&display=swap">
<style>
:root{
  color-scheme:light;
  --bg:#fbfbf9; --ink:#141413; --ink-2:#5c5b56; --ink-3:#8a8983; --hair:#e4e3dd; --hair-2:#d3d2cb;
  --acc:#2a78d6; --acc-ink:#1c5cab; --neg:#e34948; --neg-ink:#b83232; --mid:#f0efec; --wash:rgba(42,120,214,.08);
  --pos-ramp:#2a78d6; --neg-ramp:#e34948;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#131312; --ink:#f1f0ec; --ink-2:#bdbcb3; --ink-3:#898781; --hair:#2a2a28; --hair-2:#383835;
    --acc:#3987e5; --acc-ink:#7fb0f0; --neg:#e66767; --neg-ink:#f08b8b; --mid:#2b2b29; --wash:rgba(57,135,229,.14);
    --pos-ramp:#3987e5; --neg-ramp:#e66767;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#131312; --ink:#f1f0ec; --ink-2:#bdbcb3; --ink-3:#898781; --hair:#2a2a28; --hair-2:#383835;
  --acc:#3987e5; --acc-ink:#7fb0f0; --neg:#e66767; --neg-ink:#f08b8b; --mid:#2b2b29; --wash:rgba(57,135,229,.14);
  --pos-ramp:#3987e5; --neg-ramp:#e66767;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.55 "Geist",-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.page{max-width:1160px;margin:0 auto;padding-block:36px 64px;padding-inline:24px}
h1{font-size:22px;font-weight:600;letter-spacing:-.01em;margin:0 0 6px;text-wrap:balance}
h2{font-size:14px;font-weight:600;margin:0;letter-spacing:.01em}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:500}
.sub{color:var(--ink-2);margin:0;max-width:72ch}
.num{font-variant-numeric:tabular-nums}
section{border-top:1px solid var(--hair);padding-block:22px 26px}
.sec-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:12px}
.sec-head .note{color:var(--ink-3);font-size:12px}
.rows{display:grid}
.row{display:grid;grid-template-columns:120px 1fr;gap:16px;padding:9px 0;border-bottom:1px solid var(--hair);align-items:baseline}
.row:last-child{border-bottom:0}
.row .k{color:var(--ink-3);font-size:12px}
.pass{color:var(--acc-ink);font-weight:600}
.part{color:var(--ink-2);font-weight:600}
.v{font-weight:600}
/* ---- 面板 ---- */
.scroll{overflow-x:auto;padding-bottom:6px}
.grid{display:grid;grid-template-columns:150px repeat(var(--n),26px);align-items:stretch;width:max-content}
.grid .lab{position:sticky;left:0;background:var(--bg);z-index:2;padding-right:10px;font-size:12px;display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--hair)}
.grid .lab .code{color:var(--ink-3);font-size:10px}
.grid .ghead{grid-column:1 / -1;padding:12px 0 4px;font-size:11px;color:var(--ink-3);letter-spacing:.06em;text-transform:uppercase}
.grid .ghead:first-of-type{padding-top:0}
.grid .mh{font-size:10px;color:var(--ink-3);height:16px;line-height:16px;white-space:nowrap;overflow:visible}
.grid .eh{height:18px;position:relative}
.grid .eh span{position:absolute;left:0;top:0;font-size:10px;font-weight:600;color:var(--acc-ink);white-space:nowrap;line-height:18px}
.cell{height:32px;border-bottom:1px solid var(--hair);border-right:1px solid var(--bg);position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:default;color:var(--ink)}
.cell .r{font-size:11px;line-height:1;font-weight:500}
.cell .s{font-size:8px;line-height:1;letter-spacing:.02em;margin-top:3px;color:var(--ink-2)}
.cell.ep{box-shadow:inset 0 0 0 1.5px var(--acc)}
.cell.na{background:transparent}
.cell:hover{outline:2px solid var(--ink);outline-offset:-1px;z-index:3}
.legend{display:flex;gap:28px;flex-wrap:wrap;align-items:center;margin:6px 0 14px;font-size:12px;color:var(--ink-2)}
.ramp{display:inline-flex;align-items:center;gap:6px}
.ramp i{display:inline-block;width:14px;height:12px}
.toggle{margin-left:auto;font:inherit;font-size:12px;color:var(--ink);background:transparent;border:1px solid var(--hair-2);border-radius:3px;padding:4px 10px;cursor:pointer}
.toggle:hover{border-color:var(--ink-3)}
.toggle:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
table.tv{border-collapse:collapse;font-size:11px;width:max-content}
table.tv th,table.tv td{padding:4px 6px;border-bottom:1px solid var(--hair);text-align:right;white-space:nowrap}
table.tv th{color:var(--ink-3);font-weight:500}
table.tv td:first-child,table.tv th:first-child{text-align:left;position:sticky;left:0;background:var(--bg)}
/* ---- tooltip ---- */
#tip{position:fixed;z-index:20;pointer-events:none;background:var(--bg);color:var(--ink);border:1px solid var(--hair-2);padding:8px 10px;font-size:11px;line-height:1.5;min-width:180px;box-shadow:0 4px 14px rgba(0,0,0,.08)}
#tip b{font-weight:600}
#tip .g{display:grid;grid-template-columns:auto auto;gap:1px 12px}
#tip .g span:nth-child(odd){color:var(--ink-3)}
/* ---- 溢价 ---- */
.multi{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:22px 28px}
.multi figure{margin:0}
.multi figcaption{font-size:12px;color:var(--ink-2);margin-bottom:4px;display:flex;justify-content:space-between;gap:8px}
.multi figcaption b{color:var(--ink);font-weight:600}
.multi svg{width:100%;height:auto;display:block;overflow:visible}
/* ---- 事件 ---- */
.ep-block{border-bottom:1px solid var(--hair);padding:16px 0 18px}
.ep-block:last-child{border-bottom:0}
.ep-head{display:grid;grid-template-columns:44px 1fr auto;gap:14px;align-items:baseline}
.ep-head .id{font-weight:600;color:var(--acc-ink)}
.ep-head .why{color:var(--ink-2)}
.ep-body{display:grid;grid-template-columns:minmax(300px,1.1fr) minmax(280px,1fr);gap:18px 36px;margin-top:10px}
@media (max-width:760px){.ep-body{grid-template-columns:1fr}.row{grid-template-columns:1fr;gap:4px}}
table.xs{border-collapse:collapse;width:100%;font-size:11.5px}
table.xs th{font-weight:500;color:var(--ink-3);text-align:right;padding:3px 6px;border-bottom:1px solid var(--hair-2);white-space:nowrap}
table.xs td{padding:3px 6px;border-bottom:1px solid var(--hair);text-align:right;white-space:nowrap}
table.xs th:first-child,table.xs td:first-child{text-align:left}
table.xs tr.hi td{font-weight:600}
table.xs tr.hi td:first-child::before{content:"";display:inline-block;width:6px;height:6px;background:var(--acc);margin-right:6px;vertical-align:1px}
table.xs tr.src td{color:var(--ink-2)}
table.xs tr.src td:first-child::before{content:"";display:inline-block;width:6px;height:6px;background:var(--neg);margin-right:6px;vertical-align:1px}
.seq{font-size:11px;margin-top:2px}
.seq .name{display:inline-block;width:52px;color:var(--ink-3)}
.seq .ttl{display:block;margin-top:8px;color:var(--ink-2);font-weight:500}
.seq .k{display:inline-grid;grid-auto-flow:column;gap:3px}
.seq .k i{font-style:normal;display:inline-block;min-width:34px;text-align:center;font-size:9px;line-height:16px;border-bottom:1px solid var(--hair);white-space:nowrap}
.seq .k i.up{color:var(--acc-ink);font-weight:600}
.seq .k i.dn{color:var(--neg-ink);font-weight:600}
.seq .k i.rk{font-size:10px;color:var(--ink-3);border-bottom:0}
.fwd{margin-top:10px;font-size:12px;color:var(--ink-2)}
.fwd b{color:var(--ink);font-weight:600}
.verdict{margin-top:8px;color:var(--ink-2);max-width:70ch}
/* ---- 回放 ---- */
table.rp{border-collapse:collapse;font-size:12.5px;max-width:560px;width:100%}
table.rp th{font-weight:500;color:var(--ink-3);text-align:right;padding:5px 8px;border-bottom:1px solid var(--hair-2)}
table.rp td{padding:6px 8px;border-bottom:1px solid var(--hair);text-align:right}
table.rp th:first-child,table.rp td:first-child{text-align:left}
.pos{color:var(--acc-ink)} .negt{color:var(--neg-ink)}
.prose{max-width:72ch;color:var(--ink-2)}
.prose p{margin:0 0 10px}
.prose b{color:var(--ink);font-weight:600}
footer{border-top:1px solid var(--hair);padding-top:14px;font-size:11.5px;color:var(--ink-3);max-width:80ch}
</style>

<div class="page">
<header>
  <div class="eyebrow">ETF 前向机会台账 · 轮动面板 · v0</div>
  <h1>2026 ETF 轮动面板</h1>
  <p class="sub">17 个容器，每周一个截面（1-09 → 9-14）。格子颜色 = 近 1 月相对沪深300 的超额收益，格内数字 = 当周排名（1 = 最强），小字 = 形态状态。五个已核事件日标在列上。价格来自腾讯/新浪接口，QDII 与 LOF 的价格含溢价，净值单列在下方。</p>
</header>

<section id="verdict">
  <div class="sec-head"><h2>预先登记的检验</h2><span class="note">标准：五个事件里至少三个「目的地事前（t−5）进前五」或「极端预期被标出」</span></div>
  <div class="rows" id="verdict-rows"></div>
</section>

<section id="panel">
  <div class="sec-head"><h2>周截面</h2><span class="note">周五收盘；最后一列 9-14 只有一个交易日</span></div>
  <div class="legend">
    <span class="ramp"><i style="background:var(--neg-ramp)"></i><i style="background:color-mix(in oklab,var(--neg-ramp) 50%,var(--mid))"></i><i style="background:var(--mid)"></i><i style="background:color-mix(in oklab,var(--pos-ramp) 50%,var(--mid))"></i><i style="background:var(--pos-ramp)"></i>&nbsp;近 1 月相对沪深300：−30% … 0 … +30%（截断）</span>
    <span>格内小字是当周的价格状态。<b style="color:var(--acc-ink);font-weight:600">可进</b>：启动（第一次站上均线）· 回踩（上升中回到均线）· 平台突破 · 超跌反弹；<b style="color:var(--neg-ink);font-weight:600">危险</b>：过热（离均线太远且放量）· 破位（跌破均线）· 遇阻（反弹到均线被压回）· 阴跌（下跌中再破平台）</span>
    <button class="toggle" id="tv-btn" type="button" aria-pressed="false">表格视图</button>
  </div>
  <div class="scroll" id="grid-wrap"><div class="grid" id="grid"></div></div>
  <div class="scroll" id="table-wrap" hidden></div>
</section>

<section id="prem">
  <div class="sec-head"><h2>溢价率（周五收盘价 / 最新净值 − 1）</h2><span class="note">虚线以上 = 20%，框架里的「极端」门槛</span></div>
  <div class="multi" id="prem-multi"></div>
</section>

<section id="episodes">
  <div class="sec-head"><h2>五个事件日：事前截面与之后发生了什么</h2><span class="note">左表 = t−5 当天的容器排名（前 8 + 目的地 + 源头）；右侧 = t−10 → t 的状态序列；前向收益从 t−5 收盘起算</span></div>
  <div id="ep-list"></div>
</section>

<section id="replay">
  <div class="sec-head"><h2>周度回放（不是策略，是「钱在哪」这一层有没有持续性）</h2><span class="note">每周五按近 1 月相对强弱排序，持有到下周五，35 周</span></div>
  <table class="rp num">
    <thead><tr><th>组合</th><th>年内累计</th><th>周胜率（对全容器等权）</th></tr></thead>
    <tbody id="rp-body"></tbody>
  </table>
  <p class="prose" style="margin-top:10px">两段大趋势（2–3 月原油、4–5 月全球半导体）贡献了大头，而且 QDII 价格里含溢价；这一行只说明 2026 年周尺度上强者恒强、弱者恒弱，没有均值回归——它不是可交易的结论。加了「溢价 &lt;20% 且非 EXH/DROP」的过滤后累计反而略低，因为过滤掉了全球芯片 LOF 的溢价段，这与 E2 的结论一致。</p>
</section>

<section id="notes">
  <div class="sec-head"><h2>读法与下一步</h2></div>
  <div class="prose">
    <p><b>通过了什么。</b>五个事件里四个满足预先登记的标准，一个部分满足。但要说清楚这个检验证明的是什么：状态向量能在头条出现前一周把「钱已经开始去的地方」标出来，也能把「预期已经极端」标出来。它证明的是<b>迁徙一旦开始有持续性</b>，不是催化剂能被预测。预测那一段是 L1（物理催化层）的活，这里没测。</p>
    <p><b>溢价是双面的。</b>E1 与 E2 里最大的收益来自溢价膨胀，E3 之后最大的损失来自溢价塌方。「溢价 &gt;20% 不进」在 2026 年会少赚（E2 之后 +38%）也会少亏（5-27 之后 −30%）。这条规则的取舍要用更多样本定，现在只能说它把风险标对了、时点标早了。</p>
    <p><b>形态状态可用但要校准。</b>目的地的平台突破 / 回踩、源头的遇阻在 E4、E5 里都出现在事前；过热全年只触发 15 次，阈值（3 个 ATR）偏严；现金容器（货币 ETF）的状态没有意义，只看它的相对强弱。</p>
    <p><b>下一步。</b>一，把容器口径定下来（农业 vs 粮食这种差别会改变结论）；二，补份额层——从交易所的历史文件回填，不需要每天手工跑；三，把 L1 论点台账开起来，用 2026 年的五个事件倒填一遍证据时间线，看物理证据比相对强弱早多少。</p>
  </div>
</section>

<footer>数据：腾讯 fqkline（日线，2025-03 → 2026-09-14）、新浪 CaihuiFundInfoService（净值，4 只）；相对强弱以 510300 为基准；成交额 = 收盘价 × 成交量的近似；形态状态为 v0 规则版（10/20 EMA、50 SMA、ATR14、20 日均量）。文字字段经小模型转写，数字已两源交叉。</footer>
</div>
<div id="tip" hidden></div>

<script>
const D = __DATA__;
const W = D.weeks, N = W.length;
const fmtP = (x, d=1) => x==null ? '—' : ((x>0?'+':'')+(100*x).toFixed(d)+'%');
const CLIP = 0.30;
function cellBg(rs){
  if(rs==null) return 'transparent';
  const t = Math.min(1, Math.abs(rs)/CLIP);
  const pct = Math.round(t*100);
  return rs>=0 ? `color-mix(in oklab, var(--pos-ramp) ${pct}%, var(--mid))` : `color-mix(in oklab, var(--neg-ramp) ${pct}%, var(--mid))`;
}
const SHOW = new Set(['POP','XB','BNB','EXH','DROP','XBD','BNBD','REV']);
const UP = new Set(['POP','XB','BNB','REV']), DN = new Set(['EXH','DROP','XBD','BNBD']);
const ZH = {POP:'启动', XB:'回踩', BNB:'平台突破', EXH:'过热', DROP:'破位', XBD:'遇阻', BNBD:'阴跌', REV:'超跌反弹', TREND_UP:'上升中', TREND_DOWN:'下跌中', NEUTRAL:'无趋势'};
const zh = k => ZH[k] || k;
const ZH2 = {POP:'启动', XB:'回踩', BNB:'平台', EXH:'过热', DROP:'破位', XBD:'遇阻', BNBD:'阴跌', REV:'超跌'};
const zh2 = k => ZH2[k] || zh(k);
const epCols = {}; D.episodes.forEach(e => { let idx = W.findIndex(w => w >= e.date); if(idx<0) idx = N-1; epCols[idx] = (epCols[idx]||[]).concat(e.id); });

// ---- verdict rows
(function(){
  const box = document.getElementById('verdict-rows');
  const passN = D.episodes.filter(e=>e.verdict==='通过').length, partN = D.episodes.filter(e=>e.verdict==='部分').length;
  const head = document.createElement('div'); head.className='row';
  head.innerHTML = `<span class="k">结果</span><span><span class="v">${passN} 通过 · ${partN} 部分 · ${D.episodes.length-passN-partN} 未通过</span>，达到「至少三个」的门槛——这条路值得继续走，但看清它证明了什么（见页尾）。</span>`;
  box.appendChild(head);
  D.episodes.forEach(e=>{
    const r = document.createElement('div'); r.className='row';
    r.innerHTML = `<span class="k">${e.id} · ${e.date.slice(5)}</span><span><span class="${e.verdict==='通过'?'pass':'part'}">${e.verdict}</span>　${e.dest} — ${e.why}</span>`;
    box.appendChild(r);
  });
})();

// ---- grid
(function(){
  const g = document.getElementById('grid'); g.style.setProperty('--n', N);
  const monthRow = document.createDocumentFragment();
  const lab0 = document.createElement('div'); lab0.className='lab'; lab0.style.borderBottom='0'; monthRow.appendChild(lab0);
  let lastM = '';
  W.forEach((w,i)=>{ const m = w.slice(5,7); const d = document.createElement('div'); d.className='mh'; if(m!==lastM){ d.textContent = parseInt(m)+'月'; lastM=m; } monthRow.appendChild(d); });
  g.appendChild(monthRow);
  const epRow = document.createDocumentFragment();
  const lab1 = document.createElement('div'); lab1.className='lab'; lab1.style.borderBottom='0'; epRow.appendChild(lab1);
  W.forEach((w,i)=>{ const d = document.createElement('div'); d.className='eh'; if(epCols[i]) d.innerHTML = `<span>${epCols[i].join('·')}</span>`; epRow.appendChild(d); });
  g.appendChild(epRow);
  D.groups.forEach(([gname, conts])=>{
    const gh = document.createElement('div'); gh.className='ghead'; gh.textContent = gname; g.appendChild(gh);
    conts.forEach(c=>{
      const lab = document.createElement('div'); lab.className='lab'; lab.innerHTML = `<span>${c.replace('宽基-','').replace('Q-','')}</span><span class="code num">${D.codes[c]}</span>`; g.appendChild(lab);
      const cells = D.cells[c];
      cells.forEach((v,i)=>{
        const d = document.createElement('div'); d.className='cell'+(epCols[i]?' ep':'');
        if(!v || v.rs==null){ d.classList.add('na'); g.appendChild(d); return; }
        d.style.background = cellBg(v.rs);
        const isCash = c==='现金';
        const s = (!isCash && SHOW.has(v.kell)) ? `<span class="s" style="color:${UP.has(v.kell)?'var(--acc-ink)':'var(--neg-ink)'}">${zh2(v.kell)}</span>` : '';
        d.innerHTML = `<span class="r num">${v.rank}</span>${s}`;
        d.dataset.c = c; d.dataset.i = i;
        d.addEventListener('mouseenter', showTip); d.addEventListener('mousemove', moveTip); d.addEventListener('mouseleave', hideTip);
        g.appendChild(d);
      });
    });
  });
  // table view twin
  const tw = document.getElementById('table-wrap');
  let h = '<table class="tv num"><thead><tr><th>容器</th>' + W.map(w=>`<th>${w.slice(5)}</th>`).join('') + '</tr></thead><tbody>';
  D.containers.forEach(c=>{ h += `<tr><td>${c}</td>` + D.cells[c].map(v => v && v.rs!=null ? `<td title="${zh(v.kell)}">${v.rank} · ${fmtP(v.rs,0)}</td>` : '<td>—</td>').join('') + '</tr>'; });
  tw.innerHTML = h + '</tbody></table>';
  const btn = document.getElementById('tv-btn');
  btn.addEventListener('click', ()=>{ const on = tw.hidden; tw.hidden = !on; document.getElementById('grid-wrap').hidden = on; btn.setAttribute('aria-pressed', String(on)); btn.textContent = on ? '色块视图' : '表格视图'; });
})();

const tip = document.getElementById('tip');
function showTip(ev){
  const c = ev.currentTarget.dataset.c, i = +ev.currentTarget.dataset.i, v = D.cells[c][i];
  const fx = (x,d=2)=> x==null?'—':(+x).toFixed(d);
  tip.innerHTML = `<b>${c}</b> · ${W[i]}<div class="g">
    <span>近1月相对强弱</span><span class="num">${fmtP(v.rs)}（第 ${v.rank}）</span>
    <span>近1周相对强弱</span><span class="num">${fmtP(v.rs1w)}</span>
    <span>成交 20日/250日</span><span class="num">${fx(v.v20)}×</span>
    <span>成交 5日/60日</span><span class="num">${fx(v.v5)}×</span>
    <span>离 EMA10（ATR）</span><span class="num">${fx(v.ext,1)}</span>
    <span>溢价</span><span class="num">${v.prem==null?'—':fmtP(v.prem)}</span>
    <span>价格状态</span><span>${zh(v.kell)}</span>
    <span>收盘</span><span class="num">${v.close}</span></div>`;
  tip.hidden = false; moveTip(ev);
}
function moveTip(ev){ const x = ev.clientX+14, y = ev.clientY+14; const r = tip.getBoundingClientRect(); tip.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px'; tip.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px'; }
function hideTip(){ tip.hidden = true; }

// ---- premium small multiples
(function(){
  const box = document.getElementById('prem-multi');
  const funds = ['Q-全球半导体','Q-纳指科技','Q-纳指100','原油'];
  const Wd=260, Hd=96, padL=30, padR=34, padT=8, padB=16, y0=-0.06, y1=0.52;
  const X = i => padL + (Wd-padL-padR) * i/(N-1);
  const Y = p => padT + (Hd-padT-padB) * (1 - (p-y0)/(y1-y0));
  funds.forEach(c=>{
    const cells = D.cells[c];
    const pts = cells.map((v,i)=> (v && v.prem!=null) ? [X(i), Y(v.prem), v.prem, i] : null).filter(Boolean);
    if(!pts.length) return;
    const path = pts.map((p,k)=> (k?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
    const area = path + ` L${pts[pts.length-1][0].toFixed(1)} ${Y(0).toFixed(1)} L${pts[0][0].toFixed(1)} ${Y(0).toFixed(1)} Z`;
    const last = pts[pts.length-1], mx = pts.reduce((a,b)=> b[2]>a[2]?b:a);
    const epMarks = D.episodes.filter(e => e.dest===c).map(e=>{ let idx = W.findIndex(w=>w>=e.date); if(idx<0) idx=N-1; return `<line x1="${X(idx).toFixed(1)}" y1="${padT}" x2="${X(idx).toFixed(1)}" y2="${Hd-padB}" stroke="var(--acc)" stroke-width="1" opacity=".55"/>`; }).join('');
    const fig = document.createElement('figure');
    fig.innerHTML = `<figcaption><b>${c.replace('Q-','')}</b><span class="num">${D.codes[c]} · 现 ${fmtP(last[2])}</span></figcaption>
    <svg viewBox="0 0 ${Wd} ${Hd}" role="img" aria-label="${c} 溢价率周序列">
      <line x1="${padL}" y1="${Y(0).toFixed(1)}" x2="${Wd-padR}" y2="${Y(0).toFixed(1)}" stroke="var(--hair-2)" stroke-width="1"/>
      <line x1="${padL}" y1="${Y(0.2).toFixed(1)}" x2="${Wd-padR}" y2="${Y(0.2).toFixed(1)}" stroke="var(--ink-3)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${padL-4}" y="${Y(0)+3}" text-anchor="end" font-size="9" fill="var(--ink-3)">0</text>
      <text x="${padL-4}" y="${Y(0.2)+3}" text-anchor="end" font-size="9" fill="var(--ink-3)">20%</text>
      <text x="${padL-4}" y="${Y(0.4)+3}" text-anchor="end" font-size="9" fill="var(--ink-3)">40%</text>
      ${epMarks}
      <path d="${area}" fill="var(--acc)" opacity=".12"/>
      <path d="${path}" fill="none" stroke="var(--acc)" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="${mx[0].toFixed(1)}" cy="${mx[1].toFixed(1)}" r="3" fill="var(--acc)" stroke="var(--bg)" stroke-width="2"/>
      <text x="${(mx[0]+ (mx[0]>Wd-60?-6:6)).toFixed(1)}" y="${(mx[1]-6).toFixed(1)}" text-anchor="${mx[0]>Wd-60?'end':'start'}" font-size="9" fill="var(--ink)">${fmtP(mx[2],0)} · ${W[mx[3]].slice(5)}</text>
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" fill="var(--acc)" stroke="var(--bg)" stroke-width="2"/>
      <text x="${(last[0]+6).toFixed(1)}" y="${(last[1]+3).toFixed(1)}" font-size="9" fill="var(--ink)">${fmtP(last[2],0)}</text>
      <text x="${padL}" y="${Hd-3}" font-size="9" fill="var(--ink-3)">${W[0].slice(5)}</text>
      <text x="${Wd-padR}" y="${Hd-3}" font-size="9" fill="var(--ink-3)" text-anchor="end">${W[N-1].slice(5)}</text>
    </svg>`;
    box.appendChild(fig);
  });
})();

// ---- episodes
(function(){
  const box = document.getElementById('ep-list');
  D.episodes.forEach(e=>{
    const t5 = e.tables.t5; const keep = new Set([e.dest, ...e.sources]);
    const rows = t5.filter((r,k)=> k<8 || keep.has(r.c));
    const tr = rows.map(r=>`<tr class="${r.c===e.dest?'hi':(e.sources.includes(r.c)?'src':'')}"><td>${r.c}</td><td class="num">${r.rank}</td><td class="num">${fmtP(r.rs)}</td><td class="num">${r.v20==null?'—':r.v20.toFixed(1)+'×'}</td><td class="num">${r.v5==null?'—':r.v5.toFixed(1)+'×'}</td><td class="num">${r.prem==null?'—':fmtP(r.prem,0)}</td><td>${zh(r.kell)}</td></tr>`).join('');
    const seqNames = [e.dest, ...e.sources];
    const seqs = seqNames.map(n=>{ const s = e.seqs[n]; if(!s) return '';
      const ks = s.kell.map(k=>`<i class="${UP.has(k)?'up':(DN.has(k)?'dn':'')}">${SHOW.has(k)?zh2(k):(k==='TREND_UP'?'↑':(k==='TREND_DOWN'?'↓':'·'))}</i>`).join('');
      const rk = s.rank.map(r=>`<i class="rk">${r}</i>`).join('');
      const pr = s.prem.some(p=>p!=null) ? `<div><span class="name"></span><span class="k">${s.prem.map(p=>`<i class="rk">${p==null?'':Math.round(100*p)+'%'}</i>`).join('')}</span></div>` : '';
      return `<span class="ttl">${n===e.dest?'目的地 · ':'源头 · '}${n}</span><div><span class="name">状态</span><span class="k">${ks}</span></div><div><span class="name">排名</span><span class="k">${rk}</span></div>${pr.replace('<span class="name"></span>','<span class="name">溢价</span>')}`; }).join('');
    const f = e.fwd, g = e.fwd_got;
    const fwd = `<div class="fwd">从 t−5 收盘起：目的地 <b class="num">${fmtP(f.dest_5d)} / ${fmtP(f.dest_10d)} / ${fmtP(f.dest_20d)}</b>（${g.got_5} / ${g.got_10} / ${g.got_20} 日）　沪深300 <span class="num">${fmtP(f.bench_5d)} / ${fmtP(f.bench_10d)} / ${fmtP(f.bench_20d)}</span>${f.src_5d!=null?`　源头均值 <span class="num">${fmtP(f.src_5d)} / ${fmtP(f.src_10d)} / ${fmtP(f.src_20d)}</span>`:''}</div>`;
    const blk = document.createElement('div'); blk.className='ep-block';
    blk.innerHTML = `<div class="ep-head"><span class="id">${e.id}</span><span><b>${e.date}</b>　<span class="why">${e.why}</span></span><span class="${e.verdict==='通过'?'pass':'part'}">${e.verdict}</span></div>
      <div class="ep-body">
        <div><div class="eyebrow" style="margin-bottom:6px">t−5 截面 · ${e.t5}</div>
          <table class="xs"><thead><tr><th>容器</th><th>排名</th><th>近1月RS</th><th>量20/250</th><th>量5/60</th><th>溢价</th><th>形态状态</th></tr></thead><tbody>${tr}</tbody></table></div>
        <div><div class="eyebrow" style="margin-bottom:2px">t−10 → t 序列 · ${e.seqs[e.dest].dates[0].slice(5)} → ${e.date.slice(5)}</div><div class="seq">${seqs}</div>${fwd}<div class="verdict">${e.verdict_text}</div></div>
      </div>`;
    box.appendChild(blk);
  });
})();

// ---- replay
(function(){
  const r = D.replay, b = document.getElementById('rp-body');
  const rows = [['前 3（近 1 月相对强弱）','top3'],['前 3 + 过滤（溢价 <20%、非 EXH/DROP）','top3_filt'],['后 3','bot3'],['全容器等权','ew'],['沪深300','hs300']];
  b.innerHTML = rows.map(([n,k])=>`<tr><td>${n}</td><td class="${r.cum[k]>=0?'pos':'negt'}">${fmtP(r.cum[k])}</td><td>${r.hit[k]!=null?Math.round(100*r.hit[k])+'%':'—'}</td></tr>`).join('');
})();
</script>
'''

out = HTML.replace("__DATA__", data_js)
os.makedirs(f"{ROOT_S}/outputs/rotation", exist_ok=True)
open(f"{ROOT_S}/outputs/rotation/rotation-panel-2026.html", "w", encoding="utf-8").write(out)
print("written", len(out)//1024, "KB")
