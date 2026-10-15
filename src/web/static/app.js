'use strict';

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, observation, selectedId = null, busy = false, noticeTimer, loadSequence = 0;
const page = () => location.pathname === '/rotation' ? 'rotation' : location.pathname === '/market' ? 'market' : location.pathname === '/new' ? 'new' : 'home';
const params = () => new URLSearchParams(location.search);
function routeFrom(search, path, changes = {}, mode) {
  const next = new URLSearchParams(search);
  if (mode) next.set('mode', mode);
  for (const [key, value] of Object.entries(changes)) value == null ? next.delete(key) : next.set(key, value);
  const query = next.toString();
  return path + (query ? `?${query}` : '');
}
const route = (path, changes = {}) => routeFrom(params().toString(), path, changes, state?.mode);
function readingHref(search, theme, date, series, mode) {
  return routeFrom(search, '/rotation', {theme, as_of: date, card: null, series}, mode);
}
function navHref(search, path, mode) {
  return routeFrom(search, path, {card: null}, mode);
}
function shownSeries() {
  return observation?.series_kind || 'execution';
}
const number = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits);
const signed = (value, digits = 2) => value == null ? '—' : `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(digits)}`;
const direction = (value) => value > 0 ? 'positive' : value < 0 ? 'negative' : '';
const time = (value) => esc(String(value ?? '—').replace('T', ' '));
const shortDate = (value) => esc(value ? String(value).slice(5, 10) : '—');
const observed = (card) => (card.next_observation || card.thesis_inval_deadline ? (/^\d{4}-\d{2}-\d{2}$/.test(card.next_observation || card.thesis_inval_deadline) ? `到 ${card.next_observation || card.thesis_inval_deadline} 复核原论点。` : card.next_observation || card.thesis_inval_deadline) : null) || ({候选:'等待下一交易日的入场检查。',当下:'观察下一收盘与锁定失效位。',过去:'继续记录出场后的走势。',已结:'跟踪完成，保留事前判断。',作废:'保留原判断，计入全部记录。'}[card.status] || '等待下一次观测。');

function notify(message) {
  clearTimeout(noticeTimer);
  $('#notice').textContent = message;
  $('#notice').hidden = false;
  noticeTimer = setTimeout(() => { $('#notice').hidden = true; }, 6500);
}

async function api(path, body) {
  const url = new URL(path, location.origin);
  const mode = page() === 'market' ? 'market' : (state?.mode || params().get('mode'));
  if (mode) url.searchParams.set('mode', mode);
  const response = await fetch(url, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':state.csrf_token},
    body:JSON.stringify({...body, revision:state.revision}),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || '读取失败，请稍后重试。');
    error.status = response.status;
    throw error;
  }
  return data;
}

function cardButton(card) {
  const hasR = card.r_current != null;
  return `<button class="opportunity" data-card="${esc(card.id)}" aria-label="查看${esc(card.container)}，${esc(card.status)}详情">
    <div class="eyebrow">${esc(card.instrument_code)} · ${esc(card.trigger_type)}</div>
    <h3 class="opportunity-title">${esc(card.container)}<span class="arrow" aria-hidden="true">↗</span></h3>
    <p class="opportunity-thesis">${esc(card.thesis)}</p>
    <div class="metric-line"><span class="metric ${direction(card.r_current)}">${hasR ? signed(card.r_current) : card.status === '候选' ? '待进场' : '—'}</span>${hasR ? '<span class="metric-unit">R</span>' : ''}</div>
    <div class="metric-caption">${hasR ? `${card.exit_date ? '出场后继续跟踪' : '当前浮动'} · ${card.daily_date ? `${shortDate(card.daily_date)} 收盘` : '读数日期待登记'}` : `入场条件待检查 · ${shortDate(card.close_date)} 关注`}</div>
    <div class="opportunity-note"><span>下一观察</span><span>${esc(observed(card))}</span></div>
    ${['待评分','待独立评分'].includes(card.owner_score_status) ? '<div class="score-cue">待独立评分 · 查看冻结判断</div>' : ''}
  </button>`;
}

const fieldValue = field => field && field.available ? field.value : null;
const fieldReason = field => field?.reason || (field?.available ? '当前形态可以观察；形成机会仍需催化、筹码、流动性与预期证据。' : '尚无合格输入。');
const labels = {close:'原生收盘', rs_1m:'相对强弱 · 21 日', atr20:'ATR20 · 风险刻度', state:'形态状态', ext:'延伸度 · ATR14', z_month:'月末 z', rank:'全池名次'};
const kindNames = {research:'选定研究序列', execution:'执行 ETF', price_candidate:'未选价格候选'};
const identityText = identity => identity ? `${identity.code} / ${identity.adj} / ${identity.source}` : '未选定序列';
const basisText = identity => identity?.price_basis || (identity?.price_only === true ? '价格序列' : '价格口径未确定');
const priceUnit = identity => basisText(identity).includes('指数') ? '指数点位' : identity?.purpose === 'execution' ? 'ETF 价格' : '原生价格 · 单位未核定';
const windowText = field => {
  const win = field?.window;
  return win ? `${win.start || '—'} → ${win.end || '—'} · ${win.points ?? '—'} / ${win.required ?? '—'} 个观察点` : '计算窗口尚未形成';
};
function reading(field, key) {
  const value = fieldValue(field);
  if (value == null) return '—';
  if (key === 'state') return esc(field.state_label || value);
  if (key === 'rs_1m') return `${signed(value * 100)}%`;
  if (key === 'rank') return esc(value);
  return key === 'ext' || key === 'z_month' ? signed(value) : number(value, key === 'close' ? 3 : 2);
}
function observationLink(theme, date, text, extra = {}) {
  const when = date || observation?.requested_date;
  const href = extra.series
    ? readingHref(params().toString(), theme, when, extra.series, state?.mode)
    : route('/rotation', {theme, as_of:when, card:null, ...extra});
  return `<a data-route href="${esc(href)}">${text}</a>`;
}
const ENTERABLE_CODES = new Set(['POP', 'XB', 'BNB', 'REV']);
const ADVERSE_CODES = new Set(['EXH', 'DROP', 'XBD', 'BNBD']);
const ENTERABLE_LABELS = new Set(['启动', '回踩', '平台突破', '超跌反弹']);
const ADVERSE_LABELS = new Set(['过热', '破位', '遇阻', '阴跌']);
const STATE_MEANING = {启动:'第一次站上均线', 回踩:'上升中回到均线', 平台突破:'平台突破', 超跌反弹:'下跌中的反弹'};
function ruleLabel(appState) {
  if (appState && appState.mode === 'demo') return '演示规则';
  const enabled = appState && appState.rules && appState.rules.enabled;
  return Array.isArray(enabled) && enabled.length ? enabled.join('、') : '规则未启用';
}
function byRank(a, b) {
  if (a.rank == null && b.rank == null) return 0;
  if (a.rank == null) return 1;
  if (b.rank == null) return -1;
  return a.rank - b.rank;
}
function rowSnapshot(row) {
  const fields = row && row.fields || {};
  const stateField = fields.state || {};
  const available = stateField.available === true;
  const code = available ? String(stateField.value || '') : '';
  const label = available ? (stateField.state_label || code) : '';
  return {
    theme_id: row && row.theme_id,
    container: row && row.container || '',
    code: row && row.identity && row.identity.code || '',
    stateCode: code,
    stateLabel: label,
    rank: rankNumber(fields.rank),
    rs: fieldValue(fields.rs_1m),
    ext: fieldValue(fields.ext),
    window: fields.rs_1m && fields.rs_1m.window || null,
    available,
    enterable: available && (ENTERABLE_CODES.has(code) || ENTERABLE_LABELS.has(label)),
    adverse: available && (ADVERSE_CODES.has(code) || ADVERSE_LABELS.has(label)),
  };
}
function pickCandidate(data) {
  const snaps = ((data && data.containers) || []).map(rowSnapshot);
  const known = snaps.filter(row => row.available);
  const enterable = known.filter(row => row.enterable).sort(byRank);
  return {
    candidate: enterable[0] || null,
    rankOne: snaps.find(row => row.rank === 1) || null,
    enterable,
    others: enterable.slice(1, 5),
    adverse: known.filter(row => row.adverse).sort(byRank),
    available: known.length,
    unavailable: snaps.length - known.length,
    pool: snaps.length,
  };
}
function homeHeadline(data, appState) {
  const cards = (appState && appState.cards) || [];
  if (cards.length) {
    const holding = cards.filter(card => card.status === '当下').length;
    const waiting = cards.filter(card => card.status === '候选').length;
    return {title: `${holding} 笔正在验证，${waiting} 笔等待进场。`, lead: ''};
  }
  const picked = pickCandidate(data);
  const title = picked.enterable.length
    ? `${picked.pool} 个容器里 ${picked.enterable.length} 个处于可进态，没有在跑的判断。`
    : `${picked.pool} 个容器里没有处于可进态的，没有在跑的判断。`;
  const focus = picked.enterable.length ? picked.candidate : picked.rankOne;
  const tail = `${ruleLabel(appState)}，尚未扫描；这是观察，不是进场。`;
  const lead = focus
    ? `最强的一个是${focus.container} ${focus.code}：${focus.stateLabel || '—'}，名次 ${focus.rank == null ? '—' : focus.rank}，近 1 月相对沪深300 ${excessText(focus.rs)}。${tail}`
    : tail;
  return {title, lead};
}
function registryOnPage(name) {
  return name === 'market';
}
function homeFootNote() {
  if (state.mode === 'demo') return '隔离演示 · 全部为合成数据';
  const date = observation && observation.effective_date || '—';
  return `数字取自 ${date} 的执行 ETF 观察：腾讯不复权价格相对 H00300 全收益，与指数的差异按年 1% 打折。形态是观察量，不是信号；可进 = 启动 / 回踩 / 平台突破 / 超跌反弹。`;
}
function homeSpark(chart, win, code) {
  const rows = (chart || []).filter(item => Number.isFinite(item.close) && item.close > 0).slice(-60);
  if (!rows.length) return '<p class="empty">这个窗口尚无正且有限的收盘。</p>';
  const values = rows.map(item => item.close);
  const low = Math.min(...values), high = Math.max(...values);
  const span = Math.max(high - low, high * 0.01);
  const width = 640, height = 120, top = 8, bottom = 8;
  const x = index => rows.length === 1 ? width / 2 : width * index / (rows.length - 1);
  const y = value => top + (height - top - bottom) * ((high + span * 0.08) - value) / (span * 1.16);
  const path = rows.map((item, index) => `${index ? 'L' : 'M'}${x(index).toFixed(2)},${y(item.close).toFixed(2)}`).join(' ');
  let band = '';
  if (win && win.start && win.end) {
    const indexes = [];
    rows.forEach((item, index) => { if (String(item.date) >= String(win.start) && String(item.date) <= String(win.end)) indexes.push(index); });
    if (indexes.length) {
      const x0 = x(indexes[0]), x1 = x(indexes[indexes.length - 1]);
      const left = Math.min(x0, x1);
      band = `<rect class="spark-band" x="${left.toFixed(2)}" y="0" width="${Math.max(8, Math.abs(x1 - x0)).toFixed(2)}" height="${height}"/>`;
    }
  }
  const last = rows[rows.length - 1], start = rows[0];
  return `<svg class="spark-home" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(code)} ${esc(start.date)} 至 ${esc(last.date)} 收盘">${band}<path d="${path}"/><circle class="spark-end" cx="${x(rows.length - 1).toFixed(2)}" cy="${y(last.close).toFixed(2)}" r="3.5"/></svg><p class="spark-caption mono">${esc(code)} · ${esc(start.date)} → ${esc(last.date)} · ${rows.length} 个收盘 · 铺底 = 近 1 月窗口 · 末值 ${number(last.close, 3)}</p>`;
}
function watchRow(row) {
  return `<div class="watch-row"><span>${esc(row.container)} <span class="mono">${esc(row.code)}</span></span><span>${esc(row.stateLabel || '—')}</span><span class="mono">${row.rank == null ? '—' : esc(row.rank)}</span><span class="mono ${direction(row.rs)}">${excessText(row.rs)}</span></div>`;
}
function emptyCardLane(kind, withCards) {
  const copy = {
    past: ['lane-past', '上一次 · 出场后跟踪', '暂无出场后跟踪记录。', '第一张正式卡出场并走完跟踪期后，这里放它的 R 倍数、同期沪深300、为什么进、为什么出。'],
    now: ['lane-now', '当下 · 持有', '暂无持有记录。', '规则未启用，尚未扫描。正式台账启用后，这里是在跑的那张卡：入场价、1R = 入场价 − 失效位、每日追加的观测，以及什么时候退。'],
    next: ['lane-next', '下一个 · 候选', '暂无候选机会。', ''],
  }[kind];
  const note = withCards ? '' : copy[3];
  const extra = kind === 'next' ? createEntry() : '';
  return `<section class="lane ${copy[0]} lane-empty"><div class="eyebrow">${copy[1]}</div><h3>${copy[2]}</h3>${note ? `<p class="muted">${note}</p>` : ''}${extra}</section>`;
}
function createEntry() {
  if (!(state && state.authenticated && state.mode === 'readonly')) return '';
  return '<p class="next-create"><a data-route href="/new">立卡</a></p>';
}
function renderCardLane(kind, items, withCards) {
  if (!items.length) return emptyCardLane(kind, withCards);
  const heading = {past: ['lane-past', '上一次 · 出场后跟踪'], now: ['lane-now present', '当下 · 持有'], next: ['lane-next', '下一个 · 候选']}[kind];
  return `<section class="lane ${heading[0]}"><div class="eyebrow">${heading[1]}</div>${kind === 'next' ? createEntry() : ''}${items.map(cardButton).join('')}</section>`;
}
function renderNextLane(picked) {
  if (!picked.enterable.length) {
    return `<section class="lane lane-next lane-empty"><div class="eyebrow">下一个 · 观察</div><h3>今天没有处于可进态的容器。</h3><p class="muted">${picked.unavailable} 个容器形态不可用（原生历史有收盘缺口，不修补）。</p></section>`;
  }
  const row = picked.candidate;
  const meaning = STATE_MEANING[row.stateLabel] || '';
  const meaningText = meaning ? `（${meaning}）` : '';
  const extText = row.ext == null ? '' : ` · 离 20 日线 ${signed(row.ext, 1)} ATR`;
  const detail = observation && observation.detail;
  const chart = detail && detail.theme_id === row.theme_id ? homeSpark(detail.chart || [], row.window, row.code) : '<p class="empty">这个窗口尚无正且有限的收盘。</p>';
  const others = picked.others.map(watchRow).join('');
  return `<section class="lane lane-next"><div class="eyebrow">下一个 · 观察 · ${esc(row.container)} ${esc(row.code)} · 未入账 · ${esc(ruleLabel(state))}</div>${createEntry()}
    <div class="big-number mono ${direction(row.rs)}">${excessText(row.rs)}<small>观察</small></div>
    <p class="next-meta mono">近 1 月相对沪深300 · 名次 ${row.rank == null ? '—' : esc(row.rank)} / ${esc(picked.pool)}${esc(extText)}</p>
    <p class="next-explain">${esc(row.stateLabel || '—')}${esc(meaningText)}，落在可进集合里，所以放在这一栏。它是价格观察量，不是进场信号；入账前不冻结论点、预期和失效位。</p>
    <div class="spark">${chart}</div>
    <dl class="why-lines"><div><dt>为什么关注</dt><dd>${esc(row.stateLabel || '—')}${esc(meaningText)} · 名次 ${row.rank == null ? '—' : esc(row.rank)} / ${esc(picked.pool)} · 近 1 月相对沪深300 ${excessText(row.rs)}${esc(extText)}</dd></div>
    <div><dt>什么时候失效</dt><dd>尚未定义：入账时才冻结失效位</dd></div>
    <div><dt>证据</dt><dd>尚无证据包。</dd></div></dl>
    <div class="eyebrow next-rest">其余可进态 · ${picked.enterable.length - 1} 个</div>
    ${others}</section>`;
}
function renderAvoid(picked) {
  const date = observation && observation.effective_date || '—';
  const body = picked.adverse.length
    ? `<div class="watch-list">${picked.adverse.map(watchRow).join('')}</div>`
    : `<p class="avoid-none">截至 ${esc(date)}，${picked.available} 个形态可用的容器里没有处于过热 / 破位 / 遇阻 / 阴跌的。</p>`;
  return `<section class="avoid"><div class="eyebrow">今天不碰 · 形态不利，观察量不是禁入</div><h3>过热 / 破位 / 遇阻 / 阴跌</h3>${body}<p class="muted">另有 ${picked.unavailable} 个容器形态不可用（原生历史有收盘缺口，不修补），不在此列，名次仍然有效。</p></section>`;
}
function renderWorth() {
  const buckets = state.review && state.review.calibration && state.review.calibration.owner || [];
  if (buckets.some(bucket => bucket.enough)) return `<section class="worth">${renderReview(state.review)}</section>`;
  return `<section class="worth"><div class="eyebrow">规则今年值多少</div><h3>前向样本不足，不展示胜率或收益。</h3><p class="muted">正式台账跑出前向样本后，这里按 R 倍数分布报告，并给出去掉最好 1 / 2 / 3 笔后的期望；双基准是等权组合与沪深300。</p></section>`;
}
function sourceOptions() {
  return (state.sources || []).map(item => `<option value="${esc(item.source_id)}">${esc(item.source_id)} · ${esc(item.grade)} · ${esc(item.name)}</option>`).join('');
}
function evidenceFields(index) {
  return `<fieldset class="evidence-row"><legend class="field-label">证据 ${index}</legend>
    <label class="field-label" for="ev-source-${index}">固定源</label><select id="ev-source-${index}" name="source_id" required>${sourceOptions()}</select>
    <label class="field-label" for="ev-url-${index}">URL</label><input id="ev-url-${index}" name="url" type="text" required maxlength="2000" autocomplete="off">
    <label class="field-label" for="ev-title-${index}">标题</label><input id="ev-title-${index}" name="title" type="text" required maxlength="200" autocomplete="off">
    <label class="field-label" for="ev-published-${index}">发布时间</label><input id="ev-published-${index}" name="published_at" type="text" required maxlength="16" placeholder="YYYY-MM-DDTHH:MM" autocomplete="off">
    <label class="field-label" for="ev-excerpt-${index}">摘录原文</label><textarea id="ev-excerpt-${index}" name="summary" required maxlength="4000"></textarea></fieldset>`;
}
function renderComposer() {
  if (!(state && state.authenticated && state.mode === 'readonly')) {
    $('#overview').innerHTML = '<section class="composer"><div class="eyebrow">立卡</div><h1>登录后才能立卡。</h1></section>';
    return;
  }
  const containers = (state.containers || []).map(item => `<option value="${esc(item.theme_id)}">${esc(item.container)} · ${esc(item.code)}</option>`).join('');
  const prior = params().get('supersedes');
  const rebuild = prior ? `<p class="lede">作废并重建 ${esc(prior)}。旧卡保留并计入分母，新卡在提交时冻结。</p><label class="field-label" for="void-reason">作废理由</label><textarea id="void-reason" name="void_reason" required maxlength="2000"></textarea>` : '<p class="lede">只立事件驱动卡。论点、证据、量化预期和失效位在提交时冻结，之后不能改。</p>';
  $('#overview').innerHTML = `<form id="card-form" class="composer"><div class="eyebrow">事件驱动 · 提交即冻结</div><h1>立一张卡</h1>${rebuild}
    <label class="field-label" for="card-theme">容器</label><select id="card-theme" name="theme_id" required><option value="">选择容器</option>${containers}</select>
    <p id="quote-box" class="quote-box">选择容器后显示该执行 ETF 的最近收盘、ATR20，以及建议失效位（收盘 − 2 × ATR20）。</p>
    <label class="field-label" for="card-thesis">论点</label><textarea id="card-thesis" name="thesis" required maxlength="80"></textarea>
    <div id="evidence-list">${evidenceFields(1)}</div><button type="button" class="text-button" id="add-evidence">再加一条证据</button>
    <div class="composer-grid"><div><label class="field-label" for="horizon-days">期限（交易日）</label><input id="horizon-days" name="horizon_days" type="number" min="1" step="1" required></div>
    <div><label class="field-label" for="target-excess">超额目标 %</label><input id="target-excess" name="target_excess_pct" type="number" step="any" required></div></div>
    <label class="field-label" for="benchmark">基准</label><select id="benchmark" name="benchmark" required><option value="沪深300">沪深300</option><option value="等权组合">等权组合</option></select>
    <label class="field-label" for="invalidation">价格失效位</label><input id="invalidation" name="invalidation_price" type="number" step="any" min="0" required>
    <label class="field-label" for="inval-source">论点失效来源</label><select id="inval-source" name="thesis_inval_source_id" required>${sourceOptions()}</select>
    <label class="field-label" for="inval-deadline">论点失效截止</label><input id="inval-deadline" name="thesis_inval_deadline" type="date" required>
    <label class="field-label" for="inval-statement">论点失效条件</label><textarea id="inval-statement" name="thesis_inval_statement" required maxlength="500"></textarea>
    <div class="composer-grid"><div><label class="field-label" for="planned-size">计划仓位 %</label><input id="planned-size" name="planned_size_pct" type="number" min="0" max="25" step="any" required></div>
    <div><label class="field-label" for="tracking-days">跟踪天数</label><input id="tracking-days" name="tracking_days" type="number" value="20" readonly></div></div>
    <p class="muted small">评分规则 schema-v1-§3。跟踪天数固定 20。不生成 agent 分数。</p>
    <button class="primary-button" type="submit">提交并冻结</button></form>`;
  let evidenceCount = 1;
  $('#add-evidence').addEventListener('click', () => {
    evidenceCount += 1;
    $('#evidence-list').insertAdjacentHTML('beforeend', evidenceFields(evidenceCount));
  });
  $('#card-theme').addEventListener('change', refreshQuote);
  $('#card-form').addEventListener('submit', submitCard);
}
async function refreshQuote() {
  const theme = $('#card-theme').value;
  const box = $('#quote-box');
  if (!theme) {
    box.textContent = '选择容器后显示该执行 ETF 的最近收盘、ATR20，以及建议失效位（收盘 − 2 × ATR20）。';
    return;
  }
  box.textContent = '正在读取最近收盘与 ATR20…';
  try {
    const quote = await api(`/api/quote?theme=${encodeURIComponent(theme)}`);
    box.innerHTML = `<span class="mono">${esc(quote.code)}</span> ${esc(quote.name || '')}<br>最近收盘 <span class="mono">${number(quote.close, 3)}</span> · ATR20 <span class="mono">${number(quote.atr20, 3)}</span> · 建议失效位 <span class="mono">${number(quote.suggested, 3)}</span> · ${esc(quote.close_date || '')}`;
    const field = $('#invalidation');
    if (field && !field.value) field.value = quote.suggested;
  } catch (error) {
    box.textContent = error.message;
  }
}
async function submitCard(event) {
  event.preventDefault();
  if (busy) return;
  const form = event.currentTarget;
  const fields = new FormData(form);
  const evidence = [...form.querySelectorAll('.evidence-row')].map(row => ({
    source_id: row.querySelector('[name=source_id]').value,
    url: row.querySelector('[name=url]').value.trim(),
    title: row.querySelector('[name=title]').value.trim(),
    published_at: row.querySelector('[name=published_at]').value.trim(),
    summary: row.querySelector('[name=summary]').value.trim(),
  }));
  const body = {
    theme_id: fields.get('theme_id'), thesis: String(fields.get('thesis') || '').trim(), evidence,
    horizon_days: Number(fields.get('horizon_days')), target_excess_pct: Number(fields.get('target_excess_pct')),
    benchmark: fields.get('benchmark'), invalidation_price: Number(fields.get('invalidation_price')),
    thesis_inval_source_id: fields.get('thesis_inval_source_id'), thesis_inval_deadline: fields.get('thesis_inval_deadline'),
    thesis_inval_statement: String(fields.get('thesis_inval_statement') || '').trim(),
    planned_size_pct: Number(fields.get('planned_size_pct')), tracking_days: 20, scoring_rule: 'schema-v1-§3',
  };
  const prior = params().get('supersedes');
  if (prior) { body.supersedes = prior; body.void_reason = String(fields.get('void_reason') || '').trim(); }
  busy = true;
  form.querySelector('[type=submit]').disabled = true;
  try {
    const result = await api('/api/cards', body);
    state = result;
    notify('卡片已冻结。');
    await navigate(route('/', {card: result.created_id, supersedes: null}));
  } catch (error) {
    notify(error.message);
    const button = form.querySelector('[type=submit]');
    if (button) button.disabled = false;
  } finally { busy = false; }
}
function renderOverview() {
  if (page() === 'new') { renderComposer(); return; }
  if (page() === 'rotation') { renderRotation(); return; }
  const cards = state.cards || [];
  const headline = homeHeadline(observation, state);
  const picked = pickCandidate(observation);
  const past = cards.filter(card => card.status === '过去');
  const now = cards.filter(card => card.status === '当下');
  const waiting = cards.filter(card => card.status === '候选');
  const actions = state.mode === 'demo' && state.writable ? '<div class="demo-actions"><button id="reset-demo" class="text-button">重置演示</button><button id="advance-demo" class="primary-button">推进下一交易日 <span aria-hidden="true">→</span></button></div>' : '';
  const next = cards.length ? renderCardLane('next', waiting, true) : renderNextLane(picked);
  $('#overview').innerHTML = `<section class="home-head"><div><div class="eyebrow">今天</div><h1>${esc(headline.title)}</h1>${headline.lead ? `<p class="home-lead">${esc(headline.lead)}</p>` : ''}</div>${actions}</section>
    <section class="lanes" aria-label="上一次、当下与下一个">${renderCardLane('past', past, cards.length > 0)}<div class="lane-join" aria-hidden="true"><span class="lane-join-line"></span><span class="lane-join-mark">›</span></div>${renderCardLane('now', now, cards.length > 0)}<div class="lane-join" aria-hidden="true"><span class="lane-join-line"></span><span class="lane-join-mark">›</span></div>${next}</section>
    <p class="lane-nav" aria-hidden="true"><span>‹ 上一次</span><span class="lane-nav-now">● 当下</span><span>下一个 ›</span></p>
    ${renderAvoid(picked)}${renderWorth()}${registryOnPage(page()) ? renderRegistry() : ''}<p class="home-foot">${esc(homeFootNote())}</p>`;
  $('#overview').querySelectorAll('[data-card]').forEach(button => button.addEventListener('click', () => openCard(button.dataset.card)));
  $('#advance-demo')?.addEventListener('click', () => mutate('/api/demo/advance', {}, '已推进到下一交易日。'));
  $('#reset-demo')?.addEventListener('click', () => {
    if (confirm('重置会清除本次演示中的操作，恢复初始演示。是否继续？')) mutate('/api/demo/reset', {}, '演示已重置。', true);
  });
  wireNavigation();
}
function renderEvidenceGaps() {
  return `<div class="evidence-gaps">${[
    ['L1 · 物理催化','尚缺固定源、硬发布日期与历史可得时间组成的证据链。'],
    ['L2 · 筹码与份额','尚缺经核定的 ETF 份额和资金流输入；价格涨跌不能证明资金迁入。'],
    ['L3 · 流动性','尚缺可用于判断市场环境的合格流动性记录。'],
    ['L4 · 预期与溢价','尚缺同日、匹配口径的价格与 NAV；不从价格排名推断拥挤或溢价。'],
    ['源头 → 目的地','尚缺以上各层形成的迁徙证据；周截面只展示价格观察。']
  ].map(([label,reason]) => `<div class="gap-row"><h3>${label}</h3><p>${reason}</p></div>`).join('')}</div>`;
}
function renderRegistry() {
  if (state.mode !== 'market' || !state.market) return '';
  const market=state.market, series=market.series || [];
  return `<details class="disclosure registry-check"><summary>辅助检查 · 行情登记 ${series.length} 条序列</summary><p class="history-note">这是当前库全历史的登记清单，独立于页面观察日；首末日、行数与缺值统计不代表所选观察窗口可用。研究选中关系只读既有登记。</p><div class="market-scroll" tabindex="0" role="region" aria-label="行情登记辅助检查，可横向滚动"><table class="market-table"><thead><tr>${['代码 / 价格口径','容器 / 登记关系','历史范围 / 行数','库内最新收盘','来源','OHLC 缺失','量 / 额缺失'].map(label=>`<th scope="col">${label}</th>`).join('')}</tr></thead><tbody>${series.map(item=>`<tr><th scope="row"><span class="mono">${esc(item.code)} / ${esc(item.adj)}</span><small>${esc(item.name || item.code)} · ${esc(item.type)}</small><small>price_only ${item.price_only == null ? '未登记' : item.price_only ? 'true' : 'false'}</small></th><td>${esc((item.containers || []).join('、') || '—')}<small>${item.research_selected ? 'coverage 选中研究' : '未选中研究'}</small><small>${(item.relationships || []).map(relation=>`${esc(relation.theme_id)} · ${relation.role === 'research' ? '研究' : '执行'} · ${esc(relation.status)}`).join('<br>')}</small></td><td class="mono">${esc(item.first)} → ${esc(item.last)}<small>${esc(item.count)} 行</small></td><td class="mono">${esc(item.close ?? '—')}<small>${esc(item.last)}</small></td><td class="mono">${esc(item.source)}</td><td class="mono">${esc(item.ohlc_null)}<small>O ${esc(item.open_null)} / H ${esc(item.high_null)} / L ${esc(item.low_null)} / C ${esc(item.close_null)}</small></td><td class="mono">${esc(item.volume_null)} / ${esc(item.amount_null)}</td></tr>`).join('')}</tbody></table></div></details>`;
}
const ROTATION_GROUPS = [
  ['宽基', ['宽基']],
  ['科技', ['科技链']],
  ['制造', ['制造']],
  ['周期', ['周期', '周期/防守']],
  ['消费医药', ['消费医药']],
  ['金融地产', ['金融地产']],
  ['防守', ['防守']],
  ['海外', ['海外']],
];
const ROTATION_FOOT = '数字取自执行 ETF 的腾讯不复权价格相对 H00300 全收益；与指数的差异按年 1% 打折。成交量单位未核定，不画量。形态写「—」的容器历史上有收盘缺口，名次仍然有效。';
function heatClass(rs) {
  if (rs == null || !Number.isFinite(Number(rs))) return '';
  const value = Number(rs);
  const level = Math.round(Math.min(1, Math.abs(value) / 0.30) * 8);
  if (!level) return '';
  return `${value >= 0 ? 'heat-up' : 'heat-down'}-${level}`;
}
function shortState(label) {
  if (label == null || label === '') return '—';
  if (label === '上升中') return '上升';
  if (label === '下跌中') return '下跌';
  return label;
}
function excessText(rs) {
  return rs == null || !Number.isFinite(Number(rs)) ? '—' : `${signed(Number(rs) * 100, 1)}%`;
}
function rankNumber(field) {
  const value = fieldValue(field);
  return value == null || !Number.isFinite(Number(value)) ? null : Number(value);
}
function weekCell(data, themeId, date) {
  const cells = data?.rotation?.find(item => item.theme_id === themeId)?.cells || [];
  return cells.find(item => item.date === date) || null;
}
function rotationHeadline(data) {
  const comparison = data?.comparison || {};
  if (!comparison.comparison_complete) {
    return {
      title: '本周横截面不完整，不排名次。',
      lead: `${comparison.valid ?? 0}/${comparison.pool ?? 0} 个容器有合格相对强弱；缺口原因见各格说明。`,
    };
  }
  const date = data?.effective_date;
  const ranked = (data?.containers || []).map(row => ({row, cell: weekCell(data, row.theme_id, date)}));
  const named = rank => ranked.find(item => rankNumber(item.cell?.rank) === rank)?.row.container || '—';
  const top = ranked.find(item => rankNumber(item.cell?.rank) === 1);
  const pool = comparison.pool ?? (data?.containers || []).length;
  return {
    title: `${named(1)}最强，${named(2)}和${named(3)}跟着。`,
    lead: `近 1 月比沪深300全收益多 ${excessText(fieldValue(top?.cell?.rs_1m))}，${pool} 个容器里排第 1。这是价格观察，不是进场信号。`,
  };
}
function rankOneTheme(data) {
  if (!data?.comparison?.comparison_complete) return null;
  const date = data.effective_date;
  for (const row of data.containers || []) {
    if (rankNumber(weekCell(data, row.theme_id, date)?.rank) === 1) return row.theme_id;
  }
  return null;
}
function rotationGroups(containers) {
  const used = new Set();
  const groups = ROTATION_GROUPS.map(([title, lines]) => {
    const members = (containers || []).filter(row => lines.includes(row.line));
    members.forEach(row => used.add(row.theme_id));
    return [title, members];
  }).filter(([, members]) => members.length);
  const rest = (containers || []).filter(row => !used.has(row.theme_id));
  if (rest.length) groups.push(['其他', rest]);
  return groups;
}
function sparkline(chart) {
  const rows = chart || [];
  const positive = [];
  rows.forEach((item, index) => { if (Number.isFinite(item.close) && item.close > 0) positive.push(index); });
  const chosen = positive.slice(-80);
  if (!chosen.length) return '<p class="empty">这个窗口尚无正且有限的收盘。</p>';
  const windowRows = rows.slice(chosen[0], chosen[chosen.length - 1] + 1);
  const values = windowRows.map(item => Number.isFinite(item.close) && item.close > 0 ? item.close : null).filter(value => value != null);
  const low = Math.min(...values), high = Math.max(...values);
  const span = Math.max(high - low, high * 0.01);
  const width = 1100, height = 120, top = 8, bottom = 22;
  const x = index => windowRows.length === 1 ? width / 2 : width * index / (windowRows.length - 1);
  const y = value => top + (height - top - bottom) * ((high + span * 0.08) - value) / (span * 1.16);
  let drawing = false;
  const path = windowRows.map((item, index) => {
    if (!Number.isFinite(item.close) || item.close <= 0) { drawing = false; return ''; }
    const command = drawing ? 'L' : 'M';
    drawing = true;
    return `${command}${x(index).toFixed(2)},${y(item.close).toFixed(2)}`;
  }).join(' ');
  const start = windowRows[0], last = windowRows[windowRows.length - 1];
  return `<svg class="spark-line" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(start.date)} 至 ${esc(last.date)} 收盘"><path d="${path}"/><text x="0" y="${height - 4}">${esc(start.date)}</text><text x="${width}" y="${height - 4}" text-anchor="end">${esc(last.date)}  ${number(last.close, 3)}</text></svg>`;
}
function renderBasis(detail, row) {
  const fields = detail.fields || {};
  return `<p class="series-basis">${esc(kindNames[detail.series_kind] || detail.series_kind)} · <strong>${esc(basisText(detail.identity))}</strong><span>${esc(priceUnit(detail.identity))}</span><span class="mono">${esc(identityText(detail.identity))}</span>${detail.series_kind === 'execution' ? `<span>${esc(observation.discount_note || '与指数差异按年 1% 打折（intake §4.2）')}</span>` : ''}</p>
    <p class="volume-qualification"><span>成交量资格</span>${esc(detail.volume?.reason || '尚无已核定单位的同源成交量，不绘制量柱。')} · 单位 ${esc(detail.volume?.unit || '未核定')}</p>
    <div class="indicator-grid">${Object.entries(labels).map(([key, label]) => `<details class="indicator-fact"><summary><span>${label}${key === 'z_month' && fields[key]?.value_date ? ` <small class="muted mono">${esc(fields[key].value_date.slice(0, 7))}</small>` : ''}</span><span class="mono ${key === 'rs_1m' || key === 'z_month' ? direction(fieldValue(fields[key])) : ''}">${reading(fields[key], key)}</span></summary><p>${esc(fields[key]?.reason || '满足当前字段所需条件。')}</p><dl>${fact('截至', `${esc(fields[key]?.observation_date || observation.effective_date)} · 原生 ${esc(fields[key]?.native_date || '—')}`)}${fields[key]?.value_date ? fact('实际值日期', esc(fields[key].value_date)) : ''}${fact('计算窗口', esc(windowText(fields[key])))}${fact('序列身份', `<span class="mono">${esc(identityText(fields[key]))}</span>`)}${fact('价格口径', esc(basisText(fields[key])))}${fact('抓取时间', esc(fields[key]?.fetched_at || '未登记'))}</dl></details>`).join('')}</div>
    <details class="disclosure"><summary>逐日价格与原始来源</summary><div class="market-scroll" tabindex="0" role="region" aria-label="原生价格及获取时间"><table class="native-records"><thead><tr><th scope="col">原生日期</th><th scope="col">O / H / L / C</th><th scope="col">来源 / 获取时间</th><th scope="col">字段限制</th></tr></thead><tbody>${(detail.chart || []).map(item => `<tr><th scope="row" class="mono">${esc(item.date)}</th><td class="mono">${[item.open, item.high, item.low, item.close].map(value => number(value, 3)).join(' / ')}</td><td>${esc(item.source || '—')}<small>${esc(item.fetched_at || '未登记')}</small></td><td>${esc(item.close_reason || item.ohlc_reason || 'OHLC 完整')}</td></tr>`).join('')}</tbody></table></div></details>
    ${(detail.excluded_non_trading_dates || []).length ? `<details class="disclosure"><summary>原库保留的 ${detail.excluded_non_trading_dates.length} 个非交易日</summary><p class="history-note">${detail.excluded_non_trading_dates.map(esc).join('、')}。计算视图按官方日历排除，原记录没有删除或修改。</p></details>` : ''}
    ${(detail.gaps || []).length ? `<details class="disclosure"><summary>${detail.gaps.length} 条缺口 / 异常日期说明</summary><div class="gap-list">${detail.gaps.map(item => `<p><span class="mono">${esc(item.date)}</span> ${esc(item.reason)}</p>`).join('')}</div></details>` : ''}
    ${detail.unavailable ? `<div class="auxiliary-gaps">${[['nav', '净值 NAV'], ['premium', '折溢价'], ['shares', 'ETF 份额'], ['amount', '成交额']].map(([key, label]) => `<div><span>${label}</span><p>${esc(detail.unavailable[key] || '尚无合格输入')}</p></div>`).join('')}</div>` : ''}
    <p class="history-note">${esc(observation.history_note || '当前库版本重建截至该日的行情。抓取时间不等于历史可得时点。')} 量源：${esc(detail.volume_source || row?.volume_source || 'none')}。</p>`;
}
function renderFocus(detail, row) {
  if (!detail) return '<section id="series-detail" class="focus"><p class="empty">尚无可追溯的序列详情。</p></section>';
  const fields = detail.fields || {};
  const rs = fieldValue(fields.rs_1m);
  const rank = rankNumber(fields.rank);
  const stateText = fields.state?.available ? shortState(fields.state.state_label) : '—';
  const pool = observation?.comparison?.pool ?? (observation?.containers || []).length;
  const name = row?.container || detail.container || detail.theme_id;
  return `<section id="series-detail" class="focus" aria-label="所选格子"><div class="focus-head"><h2 id="series-title" tabindex="-1">${esc(name)} · ${esc(observation?.effective_date || '—')}</h2><span class="mono">${esc(detail.identity?.code || '—')} · ${esc(basisText(detail.identity))}</span></div>
    <div class="readings"><div><span class="reading-value mono ${direction(rs)}">${excessText(rs)}</span><small>近 1 月相对沪深300</small></div><div><span class="reading-value mono">${rank == null ? '—' : esc(rank)}</span><small>${esc(pool)} 个容器中的名次</small></div><div><span class="reading-value">${esc(stateText)}</span><small>形态 · 观察量，不是信号</small></div></div>
    <div class="spark">${sparkline(detail.chart || [])}</div>
    <details class="disclosure basis-fold"><summary>依据与限制</summary>${renderBasis(detail, row)}</details></section>`;
}
function renderRotation() {
  const data = observation || {}, rows = data.containers || [], weeks = data.weeks || [];
  const headline = rotationHeadline(data);
  const selectedTheme = params().get('theme') || data.detail?.theme_id;
  const selectedDate = data.effective_date;
  const latest = weeks.at(-1);
  const header = `<div class="ghead"></div>${weeks.map(week => `<div class="ghead">${esc(String(week.date || '').slice(5))}${week.partial ? '·至今' : ''}</div>`).join('')}`;
  const body = rotationGroups(rows).map(([title, members]) => `<div class="group-label">${esc(title)}</div>${members.map(row => {
    const cells = data.rotation?.find(item => item.theme_id === row.theme_id)?.cells || [];
    const head = `<div class="lab"><a data-route href="${esc(readingHref(params().toString(), row.theme_id, latest?.date, shownSeries(), state?.mode))}"><span class="lab-name">${esc(row.container)}</span><span class="lab-code mono">${esc(row.identity?.code || '—')}</span></a></div>`;
    const grid = weeks.map(week => {
      const cell = cells.find(item => item.date === week.date);
      const rs = fieldValue(cell?.rs_1m);
      const rank = rankNumber(cell?.rank);
      const stateText = cell?.state?.available ? shortState(cell.state.state_label) : '—';
      const tipState = cell?.state?.available ? (cell.state.state_label || '—') : (cell?.state?.reason || '—');
      const title = `${row.container} ${week.date}  名次 ${rank == null ? '—' : rank}  超额 ${excessText(rs)}  ${tipState}`;
      const selected = row.theme_id === selectedTheme && week.date === selectedDate;
      return `<a data-route class="cell ${heatClass(rs)}${selected ? ' is-selected' : ''}" href="${esc(readingHref(params().toString(), row.theme_id, week.date, cell?.rs_1m?.purpose || shownSeries(), state?.mode))}" title="${esc(title)}"${selected ? ' aria-current="true"' : ''}><span class="cell-rank mono">${rank == null ? '—' : esc(rank)}</span><span class="cell-state">${esc(stateText)}</span></a>`;
    }).join('');
    return head + grid;
  }).join('')}`).join('');
  $('#overview').innerHTML = `<section class="rotation-head"><h1>${esc(headline.title)}</h1><p class="lead">${esc(headline.lead)}</p></section>
    <div class="legend"><span class="mono">−30%</span><span class="legend-bar" aria-hidden="true"></span><span class="mono">+30%</span><span class="legend-note">格内数字是当周名次，1 最强。小字是形态。</span></div>
    <div class="rotation-scroll" tabindex="0" role="region" aria-label="${rows.length} 个容器、${weeks.length} 周的相对强弱，可横向滚动"><div class="rotation-grid">${header}${body}</div></div>
    ${renderFocus(data.detail, rows.find(row => row.theme_id === (data.detail && data.detail.theme_id)))}
    <p class="rotation-foot">${ROTATION_FOOT}</p>`;
  wireNavigation();
}
function priceChart(allRows, count = 90, identity) {
  const rows = count ? allRows.slice(-count) : allRows;
  const usable = rows.filter(row => Number.isFinite(row.close) && row.close > 0);
  if (!usable.length) return '<p class="empty">这个窗口尚无正且有限的真实收盘，价格图保留为空。</p>';
  const width=1120, height=290, left=58, right=18, top=22, bottom=38;
  const prices=usable.flatMap(row => [row.close, row.high, row.low].filter(value=>Number.isFinite(value)&&value>0));
  const low=Math.min(...prices), high=Math.max(...prices), span=Math.max(high-low,high*.01), minimum=low-span*.1, maximum=high+span*.1;
  const x=index=>left+(width-left-right)*(rows.length===1?.5:index/(rows.length-1));
  const y=value=>top+(height-top-bottom)*(maximum-value)/(maximum-minimum);
  let segment=false;
  const path=rows.map((row,index)=> {if (!Number.isFinite(row.close)||row.close<=0){segment=false;return '';} const command=segment?'L':'M'; segment=true;return `${command}${x(index).toFixed(2)},${y(row.close).toFixed(2)}`;}).join(' ');
  const candleWidth=Math.max(1,Math.min(7,(width-left-right)/rows.length*.5));
  const candles=rows.map((row,index)=> {
    if (![row.open,row.high,row.low,row.close].every(value=>Number.isFinite(value)&&value>0)||row.high<Math.max(row.open,row.close)||row.low>Math.min(row.open,row.close)) return '';
    return `<g class="${direction(row.close-row.open)}"><line x1="${x(index)}" y1="${y(row.high)}" x2="${x(index)}" y2="${y(row.low)}"/><rect x="${x(index)-candleWidth/2}" y="${y(Math.max(row.open,row.close))}" width="${candleWidth}" height="${Math.max(1,Math.abs(y(row.open)-y(row.close)))}"/></g>`;
  }).join('');
  const validVolumes=rows.filter(row=>Number.isFinite(row.volume)&&row.volume>=0&&!row.volume_reason);
  const volumeMax=Math.max(1,...validVolumes.map(row=>row.volume));
  const volume=validVolumes.length ? `<svg class="volume-chart" viewBox="0 0 ${width} 75" role="img" aria-label="同日期成交量">${rows.map((row,index)=>Number.isFinite(row.volume)&&row.volume>=0&&!row.volume_reason?`<rect x="${x(index)-candleWidth/2}" y="${65-row.volume/volumeMax*56}" width="${candleWidth}" height="${row.volume/volumeMax*56}"/>`:'').join('')}</svg>`:'';
  return `<svg class="native-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(identity?.code || '所选序列')} ${esc(rows[0].date)} 至 ${esc(rows.at(-1).date)}原生价格，缺收盘处断开">${[0,.5,1].map(ratio=>{const value=minimum+(maximum-minimum)*ratio;return `<line class="gridline" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/><text x="0" y="${y(value)+4}">${number(value,value<20?3:0)}</text>`;}).join('')}<path class="price-line" d="${path}"/><g class="candles">${candles}</g><text x="${left}" y="${height-6}">${esc(rows[0].date)}</text><text x="${width-right}" y="${height-6}" text-anchor="end">${esc(rows.at(-1).date)}</text></svg>${volume}<p class="chart-caption">${rows.length} 个原生日期位置 · 线为真实收盘，仅合格 OHLC 绘制蜡烛；缺收盘处断开。${rows.filter(row=>row.ohlc_reason).length} 处 OHLC 不完整或异常。</p>`;
}

function renderRules(rules) {
  const enabled = rules.enabled || [];
  const blocked = rules.blocked || [];
  return `<p class="status-line"><strong>${state.mode === 'demo' ? '演示推进已封存样例' : enabled.length ? esc(enabled.join('、')) : '正式规则未开启'}</strong>${enabled.length ? '已启用' : ''}</p>${blocked.length ? `<p class="status-line">待就绪：${esc(blocked.join('、'))}</p>` : ''}${rules.note ? `<p class="status-line">${esc(rules.note)}</p>` : ''}<p class="status-line">${state.scan?.latest_processed_day ? `已登记的每日处理截至 ${esc(state.scan.latest_processed_day)}` : '没有载入已完成的扫描记录'}；配置状态不能证明已执行扫描。</p>`;
}

function renderDataStatus(data) {
  return `<p class="status-line"><strong>收盘基准</strong>${data.benchmark_ready === true ? '可用' : '尚未就绪'}<span class="footer-dot">·</span><strong>策略研究</strong>${data.research_ready === true ? '输入可用' : '尚未就绪'}</p>${data.note ? `<p class="status-line">${esc(data.note)}</p>` : ''}`;
}

function renderReview(report) {
  if (!report || !Object.keys(report).length) return '<div class="section-heading"><h2>这套规则值多少</h2><span class="eyebrow">前向样本尚不足</span></div><p class="lead">尚无可用于评价规则的前向记录。</p><p class="summary-note">配置与行情不能代替封存判断及其后续验证；当前不展示规则胜率、预期收益或旧回放成绩。</p>';
  const buckets = report.calibration?.owner || [];
  const statusText = {triggered:'需人工审查', clear:'未触发', insufficient:'样本不足'};
  return `<div class="section-heading"><h2>评分与审查</h2><span class="eyebrow">${state.mode === 'demo' ? '演示记录' : '前向记录'}</span></div>
    <div class="review-grid"><div><h3>我的事前评分，正在积累答案</h3><p class="review-caption">每桶至少 30 条终态记录，才讨论区分度。</p>
      ${buckets.length ? `<div class="calibration-row calibration-heading"><span>事前分数</span><span>终态记录</span><span>当前结论</span></div>${buckets.map(bucket => `<div class="calibration-row"><div><span>${esc(bucket.bucket)}</span><small>已结 ${esc(bucket.closed)} · 作废 ${esc(bucket.voided)}</small></div><span class="mono">${esc(bucket.n)}</span><div>${bucket.enough ? `<span>达标率 ${number(bucket.hit_rate * 100, 1)}%</span><small>已结平均 <span class="mono ${direction(bucket.mean_r_closed)}">${signed(bucket.mean_r_closed)}R</span></small>` : '<span class="muted">样本不足，不下结论</span>'}</div></div>`).join('')}` : '<p class="empty">暂无可归入独立评分桶的记录。</p>'}
      ${report.calibration?.unscored ? `<p class="review-caption">未评分 ${esc(report.calibration.unscored.total)} 笔（终态 ${esc(report.calibration.unscored.n)}，在途 ${esc(report.calibration.unscored.open)}），全部保留在台账。</p>` : ''}
      <p class="review-caption">另一份评分的分桶保留至独立复核。</p></div>
      <div><h3>预定的审查时点</h3>${(report.alerts || []).map(alert => `<div class="review-alert"><div><span>${esc(alert.title)}</span><span class="muted">${statusText[alert.status] || '待观察'}</span></div>${renderAlertReading(alert)}</div>`).join('')}
      ${(report.pending || []).length ? `<details class="disclosure"><summary>尚待具备的审查条件</summary>${report.pending.map(item => `<div class="review-pending"><span>${esc(item.title)}</span><p>${esc(item.reason)}</p></div>`).join('')}</details>` : ''}
      <p class="review-caption">审查只作${(report.allowed_decisions || ['继续','停止','重开新版本']).map(esc).join('、')}，由人决定。</p></div></div>`;
}

function renderAlertReading(alert) {
  if (alert.id === 'last_20_mean_r') {
    return `<p>已结 <span class="mono">${esc(alert.n)} / ${esc(alert.required_n)}</span> 条 · 审查阈值 ≤ ${signed(alert.threshold)}R${alert.value != null ? ` · 当前 ${signed(alert.value)}R` : ''}</p>`;
  }
  if (alert.id === 'manual_exit_share') {
    return `<p>已出场 ${esc(alert.n)} 笔 · 审查阈值 > ${number(alert.threshold * 100,0)}%${alert.value != null ? ` · 当前 ${number(alert.value * 100,1)}%` : ''}</p>`;
  }
  return '';
}

function renderCounterfactual(data) {
  if (!data) return '';
  const frozen = data.frozen || {}, result = data.recorded_result;
  return `<section class="detail-section"><div class="section-heading"><h2>与什么作比较</h2><span class="eyebrow">${esc(frozen.date)} 冻结</span></div>
    <dl class="fact-list">${fact('等权组合', `创建时点位 <span class="mono">${number(frozen.equal_weight_level,3)}</span>`)}${fact('沪深300', `创建时点位 <span class="mono">${number(frozen.hs300_level,3)}</span>`)}${fact('容器参考价', `创建时价格 <span class="mono">${number(frozen.container_price,3)}</span>`)}</dl>
    ${result ? `<p class="counterfactual-result">已记录的${esc(result.benchmark)}超额 <span class="mono ${direction(result.realized_excess_pct)}">${signed(result.realized_excess_pct)}%</span><br><span class="muted small">持有窗口 ${esc(result.entry_date)} → ${esc(result.exit_date)}</span></p>` : ''}
    ${(data.comparisons || []).length ? `<details class="disclosure"><summary>对照结果待补全</summary>${data.comparisons.map(item=>`<p class="counterfactual-pending">${esc(item.reason)}</p>`).join('')}</details>` : ''}</section>`;
}

function renderShell() {
  document.body.dataset.page = page();
  $('#loading').hidden = true;
  $('#mode-label').textContent = state.mode === 'market' ? '真实观察 · 只读' : state.mode === 'demo' ? '演示数据 · 合成观察' : state.authenticated ? '正式台账 · 记账' : '正式台账 · 只读';
  const loginButton = $('#login-button'), loginForm = $('#login-form'), logoutButton = $('#logout-button');
  const canLogin = state.write_enabled && !state.authenticated;
  if (loginButton) loginButton.hidden = !canLogin;
  if (loginForm && !canLogin) loginForm.hidden = true;
  if (logoutButton) logoutButton.hidden = !state.authenticated;
  if (page() === 'rotation') {
    const count = observation?.weeks?.length || 12;
    $('#as-of').textContent = `截至 ${observation?.effective_date || '—'} 收盘 · 近 1 月 · ${count} 周`;
    $('#footer-source').textContent = state.mode === 'market' ? '真实观察 · 只读' : state.mode === 'demo' ? '隔离演示 · 全部为合成数据' : '正式台账 · 只读';
  } else {
    $('#as-of').textContent = `截至 ${observation?.effective_date || '—'} 收盘 · ${ruleLabel(state)}`;
    $('#footer-source').textContent = state.mode === 'demo' ? '隔离演示 · 全部为合成数据' : state.mode === 'readonly' ? (state.authenticated ? '正式台账 · 记账' : '正式台账 · 只读') : '真实观察 · 只读';
  }
  $('#mode-link').textContent = state.mode === 'demo' ? '正式台账 · 只读 ↗' : '返回演示台账 ↗';
  $('#mode-link').href = route(location.pathname, {mode:state.mode === 'demo' ? 'readonly' : 'demo',card:null});
  $('#mode-link').hidden = state.mode === 'market' || state.mode === 'demo' && state.readonly_available === false || state.mode === 'readonly' && state.demo_available === false;
  $('#mode-link').nextElementSibling.hidden = $('#mode-link').hidden;
  $('#nav-home').href = navHref(params().toString(), '/', state?.mode);
  $('#nav-rotation').href = navHref(params().toString(), '/rotation', state?.mode);
  $('#nav-home').setAttribute('aria-current', page() === 'rotation' ? 'false' : 'page');
  $('#nav-rotation').setAttribute('aria-current',page() === 'rotation' ? 'page' : 'false');
  $('#observation-controls').hidden = page() === 'new' || !observation;
  if (observation) {
    $('#observation-date').value = params().get('as_of') || observation.requested_date || '';
    if (observation.completed_date) $('#observation-date').max = observation.completed_date;
    if (observation.calendar?.first) $('#observation-date').min = observation.calendar.first;
    $('#observation-theme').innerHTML = (observation.containers || []).map(row=>`<option value="${esc(row.theme_id)}" ${row.theme_id === (params().get('theme') || observation.detail?.theme_id) ? 'selected' : ''}>${esc(row.container)} · ${esc(row.theme_id)}</option>`).join('');
    $('#observation-context').textContent = `有效日 ${observation.effective_date || '未确定'} · 库内行情末日 ${observation.actual_data_end || '无'}${observation.requested_date !== observation.effective_date ? ` · 请求 ${observation.requested_date}` : ''}`;
    const series = $('#series-kind');
    if (series) {
      const current = observation.series_kind || shownSeries();
      series.innerHTML = (observation.detail?.options || []).map(option => `<option value="${esc(option.kind)}">${esc(kindNames[option.kind] || option.kind)} · ${esc(option.identity?.code || '未选定')}</option>`).join('');
      if ([...series.options].some(option => option.value === current)) series.value = current;
    }
  }
  renderOverview();
  $('#overview').hidden = selectedId !== null;
  $('#detail').hidden = selectedId === null;
  if (!selectedId) $('#breadcrumb').textContent = page() === 'rotation' ? 'ETF 前向机会台账 › 轮动' : page() === 'market' ? 'ETF 前向机会台账 › 机会 › 行情检查' : page() === 'new' ? 'ETF 前向机会台账 › 立卡' : 'ETF 前向机会台账 › 机会';
}

function fact(label, value) {
  return `<div class="fact-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
}

function chart(daily) {
  const rows = daily.filter(row => Number.isFinite(row.r_current));
  if (!rows.length) return '<p class="empty">进场后，每日轨迹将在这里逐日记录。</p>';
  const width = 650, height = 200, left = 39, right = 12, top = 18, bottom = 32;
  const min = Math.min(0, ...rows.map(row => row.r_current)), max = Math.max(0, ...rows.map(row=>row.r_current));
  const span = Math.max(max-min, .5), low = min-span*.12, high = max+span*.12;
  const x = index => left + (width-left-right) * (rows.length === 1 ? .5 : index/(rows.length-1));
  const y = value => top+(height-top-bottom)*(high-value)/(high-low);
  const curve = rows.map((row,index) => `${index ? 'L' : 'M'}${x(index).toFixed(2)},${y(row.r_current).toFixed(2)}`).join(' ');
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(rows[0].date)}至${esc(rows.at(-1).date)}每日浮动 R 轨迹"><line class="baseline" x1="${left}" y1="${y(0)}" x2="${width-right}" y2="${y(0)}"/><text x="0" y="${y(0)+4}">0R</text><path class="curve" d="${curve}"/><circle class="dot" cx="${x(rows.length-1)}" cy="${y(rows.at(-1).r_current)}" r="3.5"/><text x="${left}" y="${height-5}">${esc(rows[0].date)}</text><text text-anchor="end" x="${width-right}" y="${height-5}">${esc(rows.at(-1).date)}</text></svg><p class="chart-caption">每日浮动 R · ${rows.length} 次收盘观测 · 截至 ${esc(rows.at(-1).date)} 收盘</p>`;
}

function pendingSignal(data) {
  if (data.exit || !(data.signals || []).length) return null;
  const signal = data.signals[data.signals.length - 1];
  const parts = [signal.signal_date, signal.reason || signal.exit_reason, signal.manual_reason].filter(Boolean);
  if (signal.signal_close != null) parts.push(`信号价 ${number(signal.signal_close, 3)}`);
  parts.push('等待后续交易日开盘成交');
  return parts.join(' · ');
}
function renderDecision(data) {
  const card = data.card || {}, daily = data.daily || [], last = daily.at(-1);
  const evidenceCount = Array.isArray(data.evidence) ? String(data.evidence.length) : null;
  const thesis = [card.thesis_inval_statement, card.thesis_inval_deadline].filter(Boolean).join(' · ');
  const crowd = [
    ['1 个月相对强弱名次', card.crowd_rs_1m_rank],
    ['3 个月相对强弱名次', card.crowd_rs_3m_rank],
    ['波动比', card.crowd_vol_ratio_20],
    ['溢价', card.crowd_premium_pct],
    ['份额变化', card.crowd_share_chg_20d],
    ['创建时 ATR', card.invalidation_atr_value],
    ['ATR 倍数', card.invalidation_atr_multiple],
    ['评分规则', card.scoring_rule],
  ];
  return `<section class="detail-section decision-lines"><div class="section-heading"><h2>当时为何触发</h2><span class="eyebrow">创建时冻结</span></div><dl class="fact-list">${fact('入场形态', textOrDash(card.state_at_entry))}${fact('拥挤排名', card.crowd_rs_1m_rank == null ? '—' : esc(card.crowd_rs_1m_rank))}${fact('触发类别', textOrDash(card.trigger_type))}${fact('冻结证据', evidenceCount == null ? '—' : esc(evidenceCount))}</dl><details class="disclosure"><summary>形态、拥挤依据与评分规则</summary><dl class="fact-list">${crowd.map(([label, value]) => fact(label, textOrDash(value))).join('')}</dl></details></section>
    <section class="detail-section decision-lines"><div class="section-heading"><h2>现在按什么条件退出</h2><span class="eyebrow">四项分开看</span></div><dl class="fact-list">${fact('创建失效位', card.invalidation_price == null ? '—' : `<span class="mono">${number(card.invalidation_price, 3)}</span>`)}${fact('当前生效止损', last?.stop_now == null ? '—' : `<span class="mono">${number(last.stop_now, 3)}</span>`)}${fact('论点失效条件', thesis ? esc(thesis) : '—')}${fact('待成交信号', esc(pendingSignal(data) || '—'))}</dl></section>`;
}
function textOrDash(value) {
  return value == null || value === '' ? '—' : esc(value);
}
function renderDetail(data) {
  const card = data.card, daily = data.daily || [], last = daily.at(-1), scores = data.scores || {}, actions = data.actions || {};
  const value = last?.r_current ?? data.exit?.realized_r;
  const expectation = card.expectation_target_r != null ? `以 ${signed(card.expectation_target_r)}R 为达标刻度` : `在 ${esc(card.expectation_horizon_days)} 个交易日内，超额目标 ${number(card.expectation_target_excess_pct)}%`;
  $('#breadcrumb').innerHTML = `<button id="breadcrumb-back">ETF 前向机会台账</button><span>›</span><strong>${esc(data.status)} · ${esc(card.container)}</strong>`;
  $('#breadcrumb-back').addEventListener('click', showHome);
  $('#detail').innerHTML = `<header class="detail-header"><div><div class="eyebrow">${esc(data.status)} · ${esc(card.instrument_code)} · ${esc(card.trigger_type)}</div><h1 id="detail-title" tabindex="-1">${esc(card.container)}</h1><p class="detail-thesis">${esc(card.thesis)}</p></div><div class="detail-metric"><div class="metric ${direction(value)}">${signed(value)}<span class="metric-unit"> R</span></div><div class="metric-caption">${data.exit ? '出场后跟踪' : '当前浮动'} · ${shortDate(last?.date || card.close_date)} 收盘</div></div></header>
    <p class="ledger-time-note">这张卡保留台账记账截至 ${time(state.observation_as_of || state.as_of)} 的记录。页面观察日期不回写卡片，也不把后来结果解释为当时已知。</p>
    <div class="detail-grid"><div>
      <section class="detail-section"><div class="section-heading"><h2>当时如何约定</h2><span class="eyebrow">创建时冻结</span></div><dl class="fact-list">${fact('关注时点', `${time(card.created_at)} · 对应 ${esc(card.close_date)} 收盘`)}${fact('量化预期', `${expectation} · 对照 ${esc(card.expectation_benchmark)}`)}${fact('价格失效位', `<span class="mono">${number(card.invalidation_price,3)}</span> · 创建时锁定`)}${fact('风险刻度', `1R = <span class="mono">${number(card.r_unit_per_share,3)}</span> / 份 · 计划仓位 ${number(card.planned_size_pct)}%`)}${fact('跟踪约定', `出场后继续跟踪 ${esc(card.tracking_days)} 个交易日`)}${card.thesis_inval_statement ? fact('论点失效', `${esc(card.thesis_inval_statement)}${card.thesis_inval_deadline ? ` · ${time(card.thesis_inval_deadline)}` : ''}`) : ''}${card.supersedes ? fact('重建自', esc(card.supersedes)) : ''}</dl></section>
      ${renderDecision(data)}
      <section class="detail-section"><div class="section-heading"><h2>价格与窗口</h2><span class="eyebrow">${esc(card.instrument_code)} · 账内收盘</span></div>${priceChart(daily,0,{code:card.instrument_code})}<p class="chart-caption">关注 ${esc(card.close_date)} · 入场 ${esc(data.entry?.entry_date || '未发生')} · 出场 ${esc(data.exit?.exit_date || '未发生')}。只画逐日记账收盘；没有入场前行情与 OHLC，不补画蜡烛。</p></section>
      <section class="detail-section"><div class="section-heading"><h2>现在发生了什么</h2><span class="eyebrow">逐日观测</span></div>${chart(daily)}${daily.length ? `<details class="disclosure"><summary>查看 ${daily.length} 条每日记录</summary><div class="observations"><div class="observation-row observation-heading"><span>日期</span><span>收盘</span><span>浮动 R</span><span>当前止损</span></div>${daily.map(row=>`<div class="observation-row mono"><span>${esc(row.date)}</span><span>${number(row.close,3)}</span><span class="${direction(row.r_current)}">${signed(row.r_current)}</span><span>${number(row.stop_now,3)}</span></div>`).join('')}</div></details>` : ''}</section>
      ${renderCounterfactual(data.counterfactual)}
      <section class="detail-section"><div class="section-heading"><h2>判断从何而来</h2><span class="eyebrow">${esc(card.evidence_status)}</span></div>${(data.evidence || []).length ? data.evidence.map(e => `<article class="evidence-item"><p>${esc(e.summary)}</p><div class="evidence-meta mono">${esc(e.source_id)} · 发布 ${time(e.published_at)}<br>首次看到 ${time(e.first_seen_at)} · 可得 ${time(e.available_at)}</div>${/^https?:\/\//.test(e.url || '') ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a>` : ''}</article>`).join('') : `<p class="empty">${card.evidence_status === '未检索' ? '这是一条机械触发的记录，创建时未检索外部证据。' : '创建时已检索，没有登记可用证据。'}</p>`}</section>
      <section class="detail-section"><div class="section-heading"><h2>同类历史</h2><span class="eyebrow">证据尚不足</span></div><p class="summary-note">尚未形成可靠的结果盲选样口径，不能判断哪些历史记录可作同类。这里不挑选盈利案例，也不把旧回放成绩当成这张卡的预期。</p></section>
      <section class="detail-section"><div class="section-heading"><h2>后续观察</h2><span class="eyebrow">原记录保留</span></div>${renderEvents(data)}</section>
    </div><aside aria-label="独立判断与操作">${renderScores(scores, actions, card)}${renderActions(data)}<div class="action-section"><h2>下一观察点</h2><p>${esc(observed({...card,status:data.status,next_observation:data.next_observation}))}</p>${data.tracking ? `<p class="space-top">出场后跟踪 <span class="mono">${esc(data.tracking.completed)} / ${esc(data.tracking.required)}</span> 个交易日</p>` : ''}</div><button class="detail-back" id="detail-back">← 返回全部机会</button></aside></div>`;
  $('#detail-back').addEventListener('click', showHome);
  $('#score-form')?.addEventListener('submit', event => {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    mutate(`/api/cards/${encodeURIComponent(card.id)}/score`, {score:Number(fields.get('score')),reason:fields.get('reason')}, '独立评分已封存。');
  });
  $('#void-form')?.addEventListener('submit', event => {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    mutate(`/api/cards/${encodeURIComponent(card.id)}/void`, {reason:fields.get('reason')}, '候选已作废，原记录保留并计入分母。');
  });
  $('#signal-form')?.addEventListener('submit', event => {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    mutate(`/api/cards/${encodeURIComponent(card.id)}/exit-signal`, {reason:fields.get('reason'),...(fields.get('reason') === '手动' ? {manual_reason:fields.get('manual_reason')} : {})}, '出场信号已记录，等待后续交易日开盘成交。');
  });
  $('#signal-reason')?.addEventListener('change', event => { const manual = event.target.value === '手动'; $('#manual-reason').required = manual; $('#manual-reason').hidden = !manual; $('label[for=manual-reason]').hidden = !manual; $('#thesis-signal-note').hidden = manual; });
  wireNavigation();
}

function renderScores(scores, actions, card) {
  const scoreRow = (label, score) => `<div class="score-record"><div><span class="small muted">${label}</span><div class="score-value">${esc(score.score)}<span class="small muted"> / 5</span></div></div><div><p>${esc(score.reason)}</p><span class="small muted">${time(score.scored_at)}</span></div></div>`;
  return `<section class="action-section"><h2>独立评分</h2>${scores.owner ? scoreRow('我的评分', scores.owner) : `<p>${actions.can_score ? '先只看冻结判断，独立给出你的证据强度。' : '本次未记录独立评分。'}</p>`}${scores.agent_hidden ? '<p class="space-top">另一份评分保持封存。</p>' : scores.agent ? scoreRow('Agent 评分', scores.agent) : ''}${actions.can_score && state.writable ? `<form id="score-form" class="action-form"><fieldset class="score-fieldset"><legend class="field-label">证据强度</legend><div class="score-options">${[0,1,2,3,4,5].map(score=>`<label><input type="radio" name="score" value="${score}" required aria-label="${score} 分"><span>${score}</span></label>`).join('')}</div><div class="score-endpoints"><span>0 · 最弱</span><span>5 · 最强</span></div></fieldset><label class="field-label" for="score-reason">一句话理由</label><textarea id="score-reason" name="reason" required maxlength="1000" placeholder="哪些事前证据支持你的判断？"></textarea><p class="score-deadline">截至 ${time(actions.score_deadline || card.owner_score_deadline)} · 提交后锁定</p><button class="primary-button" type="submit">封存我的评分</button></form>` : ''}</section>`;
}

function renderActions(data) {
  if (!state.writable) return '<p class="readonly-note">正式台账仅供查看。</p>';
  const actions = data.actions || {};
  if (actions.can_void) {
    const rebuild = state.mode === 'readonly' ? `<p class="next-create"><a data-route href="${esc(route('/new', {card: null, supersedes: data.card.id}))}">作废并重建</a></p>` : '';
    return `<section class="action-section"><h2>作废这次候选</h2><p>原判断与评分继续保留，也计入全部记录。</p><form id="void-form" class="action-form"><label class="field-label" for="void-reason">作废理由</label><textarea id="void-reason" name="reason" required maxlength="1000" placeholder="记录为什么不再等待入场。"></textarea><button class="primary-button" type="submit">记录作废</button></form>${rebuild}</section>`;
  }
  if (actions.can_signal) return `<section class="action-section"><h2>记录出场信号</h2><p>以 ${esc(actions.signal_date)} 收盘为信号，等待后续有效交易日开盘成交。</p><form id="signal-form" class="action-form"><label class="field-label" for="signal-reason">出场原因</label><select id="signal-reason" name="reason"><option value="手动">手动出场</option><option value="论点作废">论点作废</option></select><p id="thesis-signal-note" class="space-top" hidden>论点作废将按锁定的评分规则记为证伪。</p><label class="field-label" for="manual-reason">记录理由</label><textarea id="manual-reason" name="manual_reason" required maxlength="1000" placeholder="记录这次出场决定。"></textarea><button class="primary-button" type="submit">记录信号，等待成交</button></form></section>`;
  return '';
}

function renderEvents(data) {
  const events = [];
  if (data.entry) events.push([data.entry.entry_date, `按开盘价 ${number(data.entry.entry_price,3)} 入场。`]);
  (data.signals || []).forEach(signal => events.push([signal.signal_date, `${signal.exit_reason || signal.reason || '出场'}信号已记录${signal.manual_reason ? `：${signal.manual_reason}` : ''}。`]));
  if (data.exit) events.push([data.exit.exit_date, `${data.exit.exit_reason}出场 · 已实现 ${signed(data.exit.realized_r)}R。`]);
  if (data.final) events.push([data.final.recorded_at || '', `跟踪完成：${data.final.final_score}。出场后增量 ${signed(data.final.post_exit_r)}R；错过 ${signed(data.final.missed_r)}R。`]);
  if (data.void) events.push([data.void.voided_at || data.void.void_date, `候选作废：${data.void.reason}。仍计入分母。`]);
  return events.length ? events.map(([at, text])=>`<div class="event-line"><span class="mono">${time(at)}</span>${esc(text)}</div>`).join('') : '<p class="empty">尚无成交或出场记录，等待下一观察点。</p>';
}

async function openCard(id, focus = true, updateUrl = true) {
  try {
    const data = await api(`/api/cards/${encodeURIComponent(id)}`);
    selectedId = id;
    if (updateUrl) history.pushState(null,'',route(location.pathname,{card:id}));
    renderDetail(data);
    $('#overview').hidden = true;
    $('#detail').hidden = false;
    if (focus) { window.scrollTo({top:0}); $('#detail-title').focus({preventScroll:true}); }
  } catch (error) { selectedId=null; $('#overview').hidden=false; $('#detail').hidden=true; notify(error.message); }
}
function showHome() {
  selectedId = null;
  history.pushState(null,'',route('/',{card:null}));
  renderShell();
  window.scrollTo({top:0});
  $('#main').focus({preventScroll:true});
}
function wireNavigation() {
  document.querySelectorAll('[data-route]').forEach(link=>link.addEventListener('click',event=> {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault(); navigate(link.href, page() === 'rotation' && new URL(link.href).pathname === '/rotation');
  }));
}
async function navigate(url, focusDetail = false) {
  history.pushState(null,'',url);
  selectedId = params().get('card');
  await loadPage(focusDetail);
}
async function loadPage(focusDetail = false) {
  const sequence=++loadSequence;
  $('#loading').hidden=false;
  $('#loading').textContent='正在读取观察与台账…';
  $('#overview').setAttribute('aria-busy','true');
  try {
    const currentState=await api('/api/state');
    if (sequence !== loadSequence) return;
    state=currentState;
    if (page() === 'new') {
      selectedId = null;
      observation = null;
      const normalized = params();
      normalized.set('mode', state.mode);
      history.replaceState(null, '', `${location.pathname}?${normalized}`);
      renderShell();
      window.scrollTo({top: 0});
      return;
    }
    const search=params();
    const observationQuery=new URLSearchParams({weeks:'12'});
    ['as_of','theme','series'].forEach(key=>{if(search.get(key)) observationQuery.set(key,search.get(key));});
    if (!observationQuery.get('series')) observationQuery.set('series', 'execution');
    let currentObservation;
    try { currentObservation=await api(`/api/observation?${observationQuery}`); }
    catch(error) { currentObservation={reason:error.message,containers:[],weeks:[],rotation:[],detail:null}; notify(error.message); }
    if (sequence !== loadSequence) return;
    observation=currentObservation;
    const normalized=params(); normalized.set('mode', page() === 'market' ? 'market' : state.mode);
    if (!normalized.get('as_of') && observation.requested_date) normalized.set('as_of',observation.requested_date);
    if (!normalized.get('series')) normalized.set('series', observation.series_kind || 'execution');
    if (page() === 'rotation') {
      if (!search.get('theme') && observation.detail?.theme_id) {
        const top = rankOneTheme(observation);
        normalized.set('theme', top || observation.detail.theme_id);
        if (top && top !== observation.detail.theme_id) {
          const again = new URLSearchParams(observationQuery);
          again.set('theme', top);
          try {
            const refreshed = await api(`/api/observation?${again}`);
            if (sequence !== loadSequence) return;
            observation = refreshed;
          } catch (_) { normalized.set('theme', observation.detail.theme_id); }
        }
      }
    } else if (!(state.cards || []).length) {
      const theme = (pickCandidate(observation).candidate || {}).theme_id;
      if (theme) {
        normalized.set('theme', theme);
        if (theme !== observation.detail?.theme_id) {
          const again = new URLSearchParams(observationQuery);
          again.set('theme', theme);
          try {
            const refreshed = await api(`/api/observation?${again}`);
            if (sequence !== loadSequence) return;
            observation = refreshed;
          } catch (_) { normalized.set('theme', observation.detail && observation.detail.theme_id || theme); }
        }
      }
    } else if (!search.get('theme') && observation.detail?.theme_id) {
      normalized.set('theme', observation.detail.theme_id);
    }
    history.replaceState(null,'',location.pathname+`?${normalized}`);
    renderShell();
    if (selectedId) await openCard(selectedId,false,false);
    else if (focusDetail && $('#series-title')) { $('#series-title').focus({preventScroll:true}); $('#series-detail').scrollIntoView({block:'start'}); }
    else window.scrollTo({top:0});
  } catch(error) { $('#loading').textContent=`暂时无法读取观察。${error.message}`; notify(error.message); }
  finally {if(sequence === loadSequence) $('#overview').removeAttribute('aria-busy');}
}

async function mutate(path, body, message, returnHome = false) {
  if (busy || !state.writable) return;
  busy = true;
  document.querySelectorAll('form button, #advance-demo, #reset-demo').forEach(button => {button.disabled = true;});
  try {
    state = await api(path, body);
    if (returnHome) {
      selectedId = null;
      history.replaceState(null,'',route('/',{card:null,as_of:null}));
    }
    await loadPage();
    notify(message);
  } catch (error) {
    if (error.status === 409) {
      await loadPage();
    }
    notify(error.message);
  } finally {
    busy = false;
    document.querySelectorAll('form button, #advance-demo, #reset-demo').forEach(button => {button.disabled = false;});
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('#theme-toggle').setAttribute('aria-label', `切换为${theme === 'dark' ? '浅' : '深'}色`);
  try { localStorage.setItem('etf-ledger-theme', theme); } catch (_) { /* Theme also works with storage disabled. */ }
}
function boot() {
  selectedId = new URLSearchParams(location.search).get('card');
  try { setTheme(localStorage.getItem('etf-ledger-theme') === 'light' ? 'light' : 'dark'); } catch (_) { setTheme('dark'); }
  $('#theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  $('#login-button')?.addEventListener('click', () => { $('#login-form').hidden = false; $('#login-password').focus(); });
  $('#login-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !state) return;
    busy = true;
    try {
      state = await api('/api/login', {password: $('#login-password').value});
      $('#login-password').value = '';
      $('#login-form').hidden = true;
      await loadPage();
      notify('已登录，可以记账。');
    } catch (error) { notify(error.message); }
    finally { busy = false; }
  });
  $('#logout-button')?.addEventListener('click', async () => {
    if (busy || !state) return;
    busy = true;
    try {
      state = await api('/api/logout', {});
      if (page() === 'new') history.replaceState(null, '', route('/', {card: null, supersedes: null}));
      await loadPage();
      notify('已退出记账。');
    } catch (error) { notify(error.message); }
    finally { busy = false; }
  });
  $('#home-button').addEventListener('click', () => { if (state) navigate(route('/',{card:null})); });
  ['nav-home','nav-rotation'].forEach(id=>$('#'+id).addEventListener('click',event=> {if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button!==0)return;event.preventDefault();navigate(route(id==='nav-home'?'/':'/rotation',{card:null}));}));
  $('#observation-controls').addEventListener('submit',event=> {event.preventDefault();navigate(route(location.pathname,{as_of:$('#observation-date').value,theme:$('#observation-theme').value,card:null}), page() === 'rotation');});
  $('#series-kind')?.addEventListener('change', event => { if (state) navigate(route(location.pathname,{series:event.target.value,card:null}), page() === 'rotation'); });
  window.addEventListener('popstate',()=> {selectedId=params().get('card');loadPage();});
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && selectedId) showHome(); });
  loadPage();
}
if (typeof document !== 'undefined') boot();
if (typeof module === 'object' && module.exports) module.exports = {routeFrom, readingHref, navHref, renderDecision, pendingSignal, heatClass, shortState, rotationHeadline, homeHeadline, pickCandidate, registryOnPage};
