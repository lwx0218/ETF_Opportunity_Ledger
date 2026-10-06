'use strict';

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mode = new URLSearchParams(location.search).get('mode') === 'readonly' ? 'readonly' : 'demo';
const query = mode === 'readonly' ? '?mode=readonly' : '';
let state, selectedId = null, busy = false, noticeTimer;
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
  const response = await fetch(path + query, body === undefined ? {cache:'no-store'} : {
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
    <div class="metric-caption">${hasR ? (card.exit_date ? '出场后继续跟踪' : '当前浮动') : '入场条件待检查'} · ${shortDate(card.close_date)} 收盘起</div>
    <div class="opportunity-note"><span>下一观察</span><span>${esc(observed(card))}</span></div>
    ${['待评分','待独立评分'].includes(card.owner_score_status) ? '<div class="score-cue">待独立评分 · 查看冻结判断</div>' : ''}
  </button>`;
}

function renderOverview() {
  const cards = state.cards || [], summary = state.summary || {};
  const groups = ['过去', '当下', '候选'].map(status => cards.filter(card => card.status === status));
  const archive = cards.filter(card => ['已结', '作废'].includes(card.status));
  const title = !cards.length ? '新的判断，从这里开始。' : `${groups[1].length} 笔正在验证，${groups[2].length} 笔等待进场。`;
  const description = state.mode === 'demo' ? '把判断留在事前，把答案交给时间。' : '正式台账只读；每一次关注、持有与离场都保留原始记录。';
  $('#overview').innerHTML = `<section class="intro"><div><div class="eyebrow">THE OPPORTUNITY LEDGER</div><h1>${title}</h1><p>${description}</p></div>${state.writable ? '<div class="demo-actions"><button id="reset-demo" class="text-button">重置演示</button><button id="advance-demo" class="primary-button">推进下一交易日 <span aria-hidden="true">→</span></button></div>' : ''}</section>
    <section class="timeline" aria-label="过去、当下与未来">${groups.map((items, index) => `<section class="lane ${index === 1 ? 'present' : ''}" aria-labelledby="lane-${index}"><div class="lane-heading"><h2 id="lane-${index}">${['过去','当下','未来'][index]}</h2><span class="count">${String(items.length).padStart(2,'0')}</span></div><div class="lane-label">${['出场后，判断仍在被验证','持有中，跟踪每一次变化','已记录，等待入场检查'][index]}</div>${items.length ? items.map(cardButton).join('') : `<p class="empty">${['暂无出场后跟踪记录。','暂无持有记录。','暂无候选机会。'][index]}</p>`}</section>`).join('')}</section>
    <div class="flow-caption">过去 ← 当下 ← 未来 <span>·</span> 每一笔都有来处</div>
    <div class="lower-grid"><section aria-labelledby="archive-heading"><div class="section-heading"><h2 id="archive-heading">留在台账里的判断</h2><span class="eyebrow">已结 / 作废</span></div>${archive.length ? archive.map(card => `<button class="archive-row" data-card="${esc(card.id)}" aria-label="查看${esc(card.container)}${esc(card.status)}记录"><span class="archive-name">${esc(card.container)}</span><span class="muted">${esc(card.status)}</span><span class="mono muted">${shortDate(card.exit_date || card.close_date)}</span><span class="result">${esc(card.final_score || '计入分母')} ↗</span></button>`).join('') : '<p class="empty">尚无已结或作废记录。</p>'}</section>
    <section aria-labelledby="summary-heading"><div class="section-heading"><h2 id="summary-heading">每一次判断都算数</h2><span class="eyebrow">${state.mode === 'demo' ? '演示累计' : '累计'}</span></div><div class="summary-metrics"><div><div class="summary-number">${esc(summary.denominator ?? cards.length)}</div><div class="summary-label">全部记录 · 分母</div></div><div><div class="summary-number">${esc(summary.by_status?.已结 ?? archive.filter(c=>c.status==='已结').length)}</div><div class="summary-label">完成验证</div></div><div><div class="summary-number">${esc(summary.by_status?.作废 ?? archive.filter(c=>c.status==='作废').length)}</div><div class="summary-label">作废 · 仍计入</div></div></div><p class="summary-note">${state.mode === 'demo' ? '演示记录用于体验流程，不用于判断策略有效性。' : '作废与未进场的机会同样保留，避免只记下走对的判断。'}</p></section></div>
    <section class="status-section" aria-label="规则与数据状态"><div><h3>规则状态</h3>${renderRules(state.rules || {})}</div><div><h3>数据可用性</h3>${renderDataStatus(state.data_status || {})}</div></section>
    <section id="scoring-review" class="review-section">${renderReview(state.review)}</section>`;
  $('#overview').querySelectorAll('[data-card]').forEach(button => button.addEventListener('click', () => openCard(button.dataset.card)));
  $('#advance-demo')?.addEventListener('click', () => mutate('/api/demo/advance', {}, '已推进到下一交易日。'));
  $('#reset-demo')?.addEventListener('click', () => {
    if (confirm('重置会清除本次演示中的操作，恢复初始演示。是否继续？')) mutate('/api/demo/reset', {}, '演示已重置。', true);
  });
}

function renderRules(rules) {
  const enabled = rules.enabled || [];
  const blocked = rules.blocked || [];
  return `<p class="status-line"><strong>${enabled.length ? esc(enabled.join('、')) : '正式规则未开启'}</strong>${enabled.length ? '已启用' : ''}</p>${blocked.length ? `<p class="status-line">待就绪：${esc(blocked.join('、'))}</p>` : ''}${rules.note ? `<p class="status-line">${esc(rules.note)}</p>` : ''}`;
}

function renderDataStatus(data) {
  return `<p class="status-line"><strong>收盘基准</strong>${data.benchmark_ready === true ? '可用' : '尚未就绪'}<span class="footer-dot">·</span><strong>策略研究</strong>${data.research_ready === true ? '输入可用' : '尚未就绪'}</p>${data.note ? `<p class="status-line">${esc(data.note)}</p>` : ''}`;
}

function renderReview(report) {
  if (!report) return '';
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
  $('#loading').hidden = true;
  $('#mode-label').textContent = state.mode === 'demo' ? '演示数据' : '正式台账 · 只读';
  $('#as-of').textContent = state.mode === 'demo'
    ? `截至 ${String(state.as_of || '—').replace('T',' ')} · 北京时间`
    : `读取于 ${String(state.as_of || '—').replace('T',' ')} · 最新观测 ${state.observation_as_of || '无'} · 北京时间`;
  $('#footer-source').textContent = state.mode === 'demo' ? '隔离演示 · 非真实行情' : '正式数据 · 只读';
  $('#mode-link').textContent = state.mode === 'demo' ? '正式台账 · 只读 ↗' : '返回演示台账 ↗';
  $('#mode-link').href = state.mode === 'demo' ? '/?mode=readonly' : '/';
  $('#mode-link').hidden = state.mode === 'readonly' && state.demo_available === false;
  $('#mode-link').nextElementSibling.hidden = $('#mode-link').hidden;
  renderOverview();
  $('#overview').hidden = selectedId !== null;
  $('#detail').hidden = selectedId === null;
  if (!selectedId) $('#breadcrumb').textContent = '机会台账';
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

function renderDetail(data) {
  const card = data.card, daily = data.daily || [], last = daily.at(-1), scores = data.scores || {}, actions = data.actions || {};
  const value = last?.r_current ?? data.exit?.realized_r;
  const expectation = card.expectation_target_r != null ? `以 ${signed(card.expectation_target_r)}R 为达标刻度` : `在 ${esc(card.expectation_horizon_days)} 个交易日内，超额目标 ${number(card.expectation_target_excess_pct)}%`;
  $('#breadcrumb').innerHTML = `<button id="breadcrumb-back">机会台账</button><span>›</span><strong>${esc(data.status)} · ${esc(card.container)}</strong>`;
  $('#breadcrumb-back').addEventListener('click', showHome);
  $('#detail').innerHTML = `<header class="detail-header"><div><div class="eyebrow">${esc(data.status)} · ${esc(card.instrument_code)} · ${esc(card.trigger_type)}</div><h1 id="detail-title" tabindex="-1">${esc(card.container)}</h1><p class="detail-thesis">${esc(card.thesis)}</p></div><div class="detail-metric"><div class="metric ${direction(value)}">${signed(value)}<span class="metric-unit"> R</span></div><div class="metric-caption">${data.exit ? '出场后跟踪' : '当前浮动'} · ${shortDate(last?.date || card.close_date)} 收盘</div></div></header>
    <div class="detail-grid"><div>
      <section class="detail-section"><div class="section-heading"><h2>当时如何约定</h2><span class="eyebrow">创建时冻结</span></div><dl class="fact-list">${fact('关注时点', `${time(card.created_at)} · 对应 ${esc(card.close_date)} 收盘`)}${fact('量化预期', `${expectation} · 对照 ${esc(card.expectation_benchmark)}`)}${fact('价格失效位', `<span class="mono">${number(card.invalidation_price,3)}</span> · 创建时锁定`)}${fact('风险刻度', `1R = <span class="mono">${number(card.r_unit_per_share,3)}</span> / 份 · 计划仓位 ${number(card.planned_size_pct)}%`)}${fact('跟踪约定', `出场后继续跟踪 ${esc(card.tracking_days)} 个交易日`)}${card.thesis_inval_statement ? fact('论点失效', `${esc(card.thesis_inval_statement)}${card.thesis_inval_deadline ? ` · ${time(card.thesis_inval_deadline)}` : ''}`) : ''}${card.supersedes ? fact('重建自', esc(card.supersedes)) : ''}</dl></section>
      <section class="detail-section"><div class="section-heading"><h2>现在发生了什么</h2><span class="eyebrow">逐日观测</span></div>${chart(daily)}${daily.length ? `<details class="disclosure"><summary>查看 ${daily.length} 条每日记录</summary><div class="observations"><div class="observation-row observation-heading"><span>日期</span><span>收盘</span><span>浮动 R</span><span>当前止损</span></div>${daily.map(row=>`<div class="observation-row mono"><span>${esc(row.date)}</span><span>${number(row.close,3)}</span><span class="${direction(row.r_current)}">${signed(row.r_current)}</span><span>${number(row.stop_now,3)}</span></div>`).join('')}</div></details>` : ''}</section>
      ${renderCounterfactual(data.counterfactual)}
      <section class="detail-section"><div class="section-heading"><h2>判断从何而来</h2><span class="eyebrow">${esc(card.evidence_status)}</span></div>${(data.evidence || []).length ? data.evidence.map(e => `<article class="evidence-item"><p>${esc(e.summary)}</p><div class="evidence-meta mono">${esc(e.source_id)} · 发布 ${time(e.published_at)}<br>首次看到 ${time(e.first_seen_at)} · 可得 ${time(e.available_at)}</div>${/^https?:\/\//.test(e.url || '') ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a>` : ''}</article>`).join('') : `<p class="empty">${card.evidence_status === '未检索' ? '这是一条机械触发的记录，创建时未检索外部证据。' : '创建时已检索，没有登记可用证据。'}</p>`}</section>
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
}

function renderScores(scores, actions, card) {
  const scoreRow = (label, score) => `<div class="score-record"><div><span class="small muted">${label}</span><div class="score-value">${esc(score.score)}<span class="small muted"> / 5</span></div></div><div><p>${esc(score.reason)}</p><span class="small muted">${time(score.scored_at)}</span></div></div>`;
  return `<section class="action-section"><h2>独立评分</h2>${scores.owner ? scoreRow('我的评分', scores.owner) : `<p>${actions.can_score ? '先只看冻结判断，独立给出你的证据强度。' : '本次未记录独立评分。'}</p>`}${scores.agent_hidden ? '<p class="space-top">另一份评分保持封存。</p>' : scores.agent ? scoreRow('Agent 评分', scores.agent) : ''}${actions.can_score && state.writable ? `<form id="score-form" class="action-form"><fieldset class="score-fieldset"><legend class="field-label">证据强度</legend><div class="score-options">${[0,1,2,3,4,5].map(score=>`<label><input type="radio" name="score" value="${score}" required aria-label="${score} 分"><span>${score}</span></label>`).join('')}</div><div class="score-endpoints"><span>0 · 最弱</span><span>5 · 最强</span></div></fieldset><label class="field-label" for="score-reason">一句话理由</label><textarea id="score-reason" name="reason" required maxlength="1000" placeholder="哪些事前证据支持你的判断？"></textarea><p class="score-deadline">截至 ${time(actions.score_deadline || card.owner_score_deadline)} · 提交后锁定</p><button class="primary-button" type="submit">封存我的评分</button></form>` : ''}</section>`;
}

function renderActions(data) {
  if (!state.writable) return '<p class="readonly-note">正式台账仅供查看。</p>';
  const actions = data.actions || {};
  if (actions.can_void) return `<section class="action-section"><h2>作废这次候选</h2><p>原判断与评分继续保留，也计入全部记录。</p><form id="void-form" class="action-form"><label class="field-label" for="void-reason">作废理由</label><textarea id="void-reason" name="reason" required maxlength="1000" placeholder="记录为什么不再等待入场。"></textarea><button class="primary-button" type="submit">记录作废</button></form></section>`;
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

async function openCard(id, focus = true) {
  try {
    const data = await api(`/api/cards/${encodeURIComponent(id)}`);
    selectedId = id;
    renderDetail(data);
    $('#overview').hidden = true;
    $('#detail').hidden = false;
    if (focus) { window.scrollTo({top:0}); $('#detail-title').focus({preventScroll:true}); }
  } catch (error) { notify(error.message); }
}

function showHome() {
  selectedId = null;
  renderShell();
  window.scrollTo({top:0});
  $('#main').focus({preventScroll:true});
}

async function mutate(path, body, message, returnHome = false) {
  if (busy || !state.writable) return;
  busy = true;
  document.querySelectorAll('form button, #advance-demo, #reset-demo').forEach(button => {button.disabled = true;});
  try {
    state = await api(path, body);
    if (returnHome) selectedId = null;
    renderShell();
    if (selectedId) await openCard(selectedId, false);
    notify(message);
  } catch (error) {
    if (error.status === 409) {
      state = await api('/api/state');
      renderShell();
      if (selectedId) await openCard(selectedId, false);
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
try { setTheme(localStorage.getItem('etf-ledger-theme') === 'light' ? 'light' : 'dark'); } catch (_) { setTheme('dark'); }
$('#theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
$('#home-button').addEventListener('click', () => { if (state) showHome(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && selectedId) showHome(); });
api('/api/state').then(data => {state = data; renderShell();}).catch(error => {
  $('#loading').textContent = `暂时无法读取台账。${error.message}`;
  $('#mode-label').textContent = mode === 'demo' ? '演示数据 · 未连接' : '正式台账 · 未连接';
});
