'use strict';

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, observation, selectedId = new URLSearchParams(location.search).get('card'), busy = false, noticeTimer, loadSequence = 0;
const page = () => location.pathname === '/rotation' ? 'rotation' : 'home';
const params = () => new URLSearchParams(location.search);
const route = (path, changes = {}) => {
  const search = params();
  if (state?.mode) search.set('mode', state.mode);
  for (const [key, value] of Object.entries(changes)) value == null ? search.delete(key) : search.set(key, value);
  return path + (search.size ? `?${search}` : '');
};
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
  const mode = state?.mode || params().get('mode');
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

function renderLedgerOverview() {
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
  return `<a data-route href="${esc(route('/rotation', {theme, as_of:date || observation?.requested_date, card:null, ...extra}))}">${text}</a>`;
}
function renderOverview() {
  if (page() === 'rotation') { renderRotation(); return; }
  if (state.mode !== 'market') renderLedgerOverview();
  else {
    $('#overview').innerHTML = `<section class="intro"><div><div class="eyebrow">今天 · 真实观察</div><h1>先看见变化，再等待判断。</h1><p>此观察入口不载入正式判断／扫描结果，不能据此确认今天有无机会。</p></div>${observationLink(params().get('theme'), observation?.requested_date, '进入轮动全景 ↗')}</section>
      <section class="timeline observation-timeline" aria-label="过去、当下与未来">${[0,1,2].map(renderPublicLane).join('')}</section>`;
  }
  const section = document.createElement('section'); section.id = 'current-observation'; section.className = 'current-observation';
  section.innerHTML = renderObservationHome();
  if (state.mode === 'market') $('#overview').append(section);
  else $('#overview').querySelector('.flow-caption')?.after(section);
  if (state.mode === 'market') {
    const lower = document.createElement('div'); lower.innerHTML = `<section class="limits-section"><div class="section-heading"><h2>今天，哪些判断还不能做</h2><span class="eyebrow">条件欠缺，不是投资禁入</span></div>${renderEvidenceGaps()}</section><section class="rules-worth"><div class="section-heading"><h2>这套规则值多少</h2><span class="eyebrow">需要前向证据</span></div><p class="lead">价格读数不能回答规则是否有效。</p><p class="summary-note">本入口不载入正式台账、规则配置与扫描记录。没有可引用的前向样本，就不展示胜率、预期收益或旧回放成绩。</p></section>${renderRegistry()}`; $('#overview').append(lower);
  } else {
    const limits=document.createElement('section'); limits.className='limits-section';
    limits.innerHTML=`<div class="section-heading"><h2>今天，哪些判断还不能做</h2><span class="eyebrow">条件欠缺，不是投资禁入</span></div>${renderEvidenceGaps()}`;
    section.after(limits);
  }
  wireNavigation();
}
function renderPublicLane(index) {
  const detail=observation?.detail, row=observation?.containers?.find(item=>item.theme_id === detail?.theme_id), fields=detail?.fields || row?.fields || {}, identity=detail?.identity || row?.identity;
  const previous=observation?.rotation?.find(item=>item.theme_id === row?.theme_id)?.cells?.at(-2);
  const value=index===0 ? reading(previous?.rs_1m,'rs_1m') : index===1 ? reading(fields.close,'close') : reading(fields.state,'state');
  const captions=[`研究序列前周相对强弱 · ${previous?.date || '无截面'}`,`${row?.container || '观察容器'} · 原生收盘 ${detail?.native_date || row?.native_date || '—'}`,`${kindNames[detail?.series_kind] || '所选序列'} · 不生成入场信号`];
  const conclusions=['上一笔判断仍需原记录验证。',fields.close?.available ? '价格已经可见，判断仍需证据。' : '当前序列的价格条件尚不完整。','先补齐条件，再形成新判断。'];
  const explanation=index===0 ? '本入口不读取正式评分与出场记录。这里只回看同一容器选定研究序列的价格变化。' : index===1 ? `${kindNames[detail?.series_kind] || '所选序列'} · ${basisText(identity)} · ${identity?.code || '未选定'}。正式持仓和扫描结果不在本入口载入范围内。` : fieldReason(fields.state);
  return `<section class="lane ${index === 1 ? 'present' : ''}"><div class="lane-heading"><h2>${['过去','当下','未来'][index]}</h2><span class="eyebrow">${['上一次对不对','当下在跑什么','下一个还差什么'][index]}</span></div><p class="lane-conclusion">${conclusions[index]}</p><div class="public-reading mono ${index===0 ? direction(fieldValue(previous?.rs_1m)) : ''}">${value}</div><p class="metric-caption">${esc(captions[index])}</p>${index===1 && detail ? `<div class="home-price">${priceChart(detail.chart || [],45,detail.identity)}</div>` : ''}<p class="lane-context">${esc(explanation)}</p>${observationLink(row?.theme_id,index===0?previous?.date:observation?.requested_date,index===0?'回看价格依据 ↗':index===1?'查看容器与窗口 ↗':'查看仍缺的条件 ↗',index===0?{series:'research'}:{})}</section>`;
}
function renderObservationHome() {
  if (!observation) return '<p class="empty">观察尚未读取。</p>';
  const rows = observation.containers || [], comparison = observation.comparison || {};
  const available = rows.filter(row => row.fields?.close?.available);
  const chosen = rows.find(row => row.theme_id === params().get('theme')) || available[0] || rows[0];
  return `<div class="section-heading"><h2>今天能看见什么</h2><span class="eyebrow">截至 ${esc(observation.effective_date || '未能确定')} · ${state.mode === 'demo' ? '合成观察' : '真实观察'}</span></div>
    <div class="observation-lead"><div><p class="lead">${comparison.comparison_complete ? comparison.valid > 0 ? '可比较相对强弱，仍需独立判断。' : '尚无完成相对强弱预热的容器。' : `${state.mode === 'demo' ? '展示合成价格' : available.length ? '已有真实价格' : '当前价格资格未确定'}，跨容器比较仍有缺口。`}</p><p class="summary-note">${esc(observation.reason || `选定研究序列中，${available.length} 个容器可读收盘，${comparison.valid ?? 0} 个容器具有合格相对强弱。`)}${comparison.comparison_complete ? '' : ' 全池排名暂不提供，容器按原登记顺序保留。'}</p></div><span class="availability-reading mono">${available.length}<small>/ ${rows.length} 可读收盘</small></span></div>
    ${chosen ? `<div class="observation-focus"><div><span class="eyebrow">${esc(chosen.theme_id)} · ${esc(chosen.native_date || '无原生日期')}</span><h3>${observationLink(chosen.theme_id, observation.requested_date, `${esc(chosen.container)} <span aria-hidden="true">↗</span>`)}</h3><p class="summary-note">${esc(basisText(chosen.identity))} · ${esc(identityText(chosen.identity))}</p></div><div class="focus-reading"><span class="mono">${reading(chosen.fields?.close,'close')}</span><small>原生收盘 · ${esc(chosen.native_date || '—')}</small></div><div class="focus-explanation"><span>${chosen.fields?.state?.available ? reading(chosen.fields.state,'state') : '形态条件尚不完整'}</span><p>${esc(chosen.fields?.state?.reason || '价格形态是观察量，不直接形成买卖判断。')}</p></div></div>` : ''}
    <p class="comparison-basis">下列读数 = 选定研究序列的 21 交易日收益 − H00300 全收益指数同窗收益；价格与全收益口径分别标明，不是绝对收益。</p>
    <div class="container-links" aria-label="全部观察容器">${rows.map(row => observationLink(row.theme_id, observation.requested_date, `<span>${esc(row.container)}<small>${esc(basisText(row.identity))}</small></span><span class="mono ${direction(fieldValue(row.fields?.rs_1m))}">${reading(row.fields?.rs_1m,'rs_1m')}</span>`)).join('')}</div>
    <p class="comparison-basis">${state.mode === 'demo' ? '合成观察不判定正式收盘基准与研究资格。' : `收盘基准：${observation.benchmark_ready === true ? '可用' : '尚未就绪'} · 正式研究输入：${observation.research_ready === true ? '就绪' : '尚未就绪'}。逐字段可观察，不代表全池可进入正式研究。`}</p>
    <div class="observation-bottom"><span>${esc(observation.history_note || '历史观察按当前库版本重建，不代表当时已抓取或已扫描。')}</span>${observationLink(chosen?.theme_id, observation.requested_date, '比较各周变化 →')}</div>`;
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
function renderRotation() {
  const data = observation, rows = data?.containers || [], weeks = data?.weeks || [], comparison = data?.comparison || {};
  const selected = params().get('theme') || data?.detail?.theme_id;
  $('#overview').innerHTML = `<section class="intro rotation-intro"><div><div class="eyebrow">轮动 · 同一个时间截面</div><h1>变化放在一起，缺口也留在原位。</h1><p>${rows.length} 个容器 · ${weeks.length} 个周截面 · ${comparison.comparison_complete ? comparison.valid > 0 ? '全池名次可用' : '尚无完成相对强弱预热的容器' : '比较池不完整，保留相对强弱，不给全池排名'}</p></div></section>
    <div class="rotation-meta"><span>格内：21 交易日收益 − H00300 全收益指数同窗收益 / 形态<br>价格与全收益口径逐行标明 · 周五为界，周内最后官方交易日</span><span>红 <span class="positive">＋</span> · 绿 <span class="negative">−</span> · — 不可用</span></div>
    ${data?.reason ? `<p class="observation-warning">${esc(data.reason)}</p>` : ''}
    <div class="rotation-scroll" tabindex="0" role="region" aria-label="容器与周截面，可横向滚动"><table class="rotation-table"><caption class="visually-hidden">全部 ${rows.length} 个容器的周截面，点击格子追溯原生序列</caption><thead><tr><th scope="col">容器 / 选定研究</th>${weeks.map(week => `<th scope="col"><span class="mono">${esc(week.date?.slice(5))}</span><small>${week.partial ? '截至当日' : '周截面'}</small></th>`).join('')}</tr></thead><tbody>${rows.map(row => {
      const cells = data.rotation?.find(item => item.theme_id === row.theme_id)?.cells || [];
      return `<tr class="${selected === row.theme_id ? 'selected-row' : ''}"><th scope="row">${observationLink(row.theme_id, data.requested_date, `${esc(row.container)}<small class="mono">${esc(row.theme_id)} · ${esc(row.identity?.code || '未选定')}</small><small>${esc(basisText(row.identity))}</small>`)}</th>${weeks.map(week => {const cell = cells.find(item => item.date === week.date); const rs = fieldValue(cell?.rs_1m); return `<td><a data-route class="matrix-cell ${direction(rs)}" href="${esc(route('/rotation',{theme:row.theme_id,as_of:week.date,card:null}))}" aria-label="${esc(row.container)} ${esc(week.date)} 相对强弱 ${reading(cell?.rs_1m,'rs_1m')}，${esc(cell?.state?.state_label || cell?.state?.reason || '形态不可用')}"><span class="mono">${reading(cell?.rs_1m,'rs_1m')}</span><small>${cell?.state?.available ? reading(cell.state,'state') : '条件不足'}</small>${fieldValue(cell?.rank) != null ? `<em>#${reading(cell.rank,'rank')}</em>` : ''}</a></td>`;}).join('')}</tr>`;
    }).join('')}</tbody></table></div>
    <div class="observation-bottom"><span>比较池 ${esc(comparison.pool ?? rows.length)} · 合格 ${esc(comparison.valid ?? 0)} · 缺失 ${(comparison.missing || []).length} · 边界排除 ${(comparison.excluded || []).length}；筛选不改变分母。</span><span>${esc(data?.effective_date || '—')}</span></div>
    ${(comparison.missing || []).length || (comparison.excluded || []).length ? `<details class="disclosure comparison-gaps"><summary>查看比较池缺口与边界</summary>${[...(comparison.missing || []),...(comparison.excluded || [])].map(item=>`<p><span class="mono">${esc(item.theme_id)}</span> ${esc(item.reason)}</p>`).join('')}</details>` : ''}
    <section id="series-detail" class="series-detail" aria-label="所选容器详情">${renderSeriesDetail(data?.detail)}</section>
    <section class="limits-section"><div class="section-heading"><h2>从价格到判断，还缺什么</h2><span class="eyebrow">每项证据各有归属</span></div>${renderEvidenceGaps()}</section>${renderRegistry()}`;
  wireNavigation();
  $('#series-kind')?.addEventListener('change', event => navigate(route('/rotation',{series:event.target.value,card:null}), true));
  $('#chart-window')?.addEventListener('change', event => {$('#native-price-chart').innerHTML = priceChart(data.detail.chart || [], Number(event.target.value), data.detail.identity);});
}
function renderSeriesDetail(detail) {
  if (!detail) return '<p class="empty">尚无可追溯的序列详情。</p>';
  const row = observation.containers?.find(item=>item.theme_id === detail.theme_id), fields = detail.fields || {};
  return `<div class="section-heading"><div><div class="eyebrow">${esc(detail.theme_id)} · 截至 ${esc(observation.effective_date || '—')}</div><h2 id="series-title" tabindex="-1">${esc(row?.container || detail.container || detail.theme_id)}</h2></div><select id="series-kind" aria-label="选择价格序列">${(detail.options || []).map(option => `<option value="${esc(option.kind)}" ${option.kind === detail.series_kind ? 'selected' : ''}>${kindNames[option.kind] || option.kind} · ${esc(option.identity?.code || '未选定')}</option>`).join('')}</select></div>
    <p class="series-basis">${esc(kindNames[detail.series_kind] || detail.series_kind)} · <strong>${esc(basisText(detail.identity))}</strong><span>${esc(priceUnit(detail.identity))}</span><span class="mono">${esc(identityText(detail.identity))}</span></p>
    <div class="price-heading"><h3>价格与窗口</h3><label>显示 <select id="chart-window" aria-label="价格显示窗口"><option value="90">最近 90 行</option><option value="30">最近 30 行</option><option value="0">全部已载入</option></select></label></div>
    <div id="native-price-chart">${priceChart(detail.chart || [],90,detail.identity)}</div>
    <details class="disclosure"><summary>逐日价格与原始来源</summary><div class="market-scroll" tabindex="0" role="region" aria-label="原生价格及获取时间"><table class="native-records"><thead><tr><th scope="col">原生日期</th><th scope="col">O / H / L / C</th><th scope="col">来源 / 获取时间</th><th scope="col">字段限制</th></tr></thead><tbody>${(detail.chart || []).map(row=>`<tr><th scope="row" class="mono">${esc(row.date)}</th><td class="mono">${[row.open,row.high,row.low,row.close].map(value=>number(value,3)).join(' / ')}</td><td>${esc(row.source || '—')}<small>${esc(row.fetched_at || '未登记')}</small></td><td>${esc(row.close_reason || row.ohlc_reason || 'OHLC 完整')}</td></tr>`).join('')}</tbody></table></div></details>
    <p class="volume-qualification"><span>成交量资格</span>${esc(detail.volume?.reason || '尚无已核定单位的同源成交量，不绘制量柱。')} · 单位 ${esc(detail.volume?.unit || '未核定')}</p>
    <div class="indicator-grid">${Object.entries(labels).map(([key,label])=>`<details class="indicator-fact"><summary><span>${label}${key === 'z_month' && fields[key]?.value_date ? ` <small class="muted mono">${esc(fields[key].value_date.slice(0,7))}</small>` : ''}</span><span class="mono ${key === 'rs_1m' || key === 'z_month' ? direction(fieldValue(fields[key])) : ''}">${reading(fields[key],key)}</span></summary><p>${esc(fields[key]?.reason || '满足当前字段所需条件。')}</p><dl>${fact('截至',`${esc(fields[key]?.observation_date || observation.effective_date)} · 原生 ${esc(fields[key]?.native_date || '—')}`)}${fields[key]?.value_date ? fact('实际值日期',esc(fields[key].value_date)) : ''}${fact('计算窗口',esc(windowText(fields[key])))}${fact('序列身份',`<span class="mono">${esc(identityText(fields[key]))}</span>`)}${fact('价格口径',esc(basisText(fields[key])))}${fact('抓取时间',esc(fields[key]?.fetched_at || '未登记'))}</dl></details>`).join('')}</div>
    <p class="chart-caption">显示窗口只裁图，不重置指标起点。量源：${esc(detail.volume_source || row?.volume_source || 'none')}；没有完整量条件时，形态须结合其限制阅读。</p>
    ${detail.unavailable ? `<div class="auxiliary-gaps">${[['nav','净值 NAV'],['premium','折溢价'],['shares','ETF 份额'],['amount','成交额']].map(([key,label])=>`<div><span>${label}</span><p>${esc(detail.unavailable[key] || '尚无合格输入')}</p></div>`).join('')}</div>` : ''}
    ${(detail.excluded_non_trading_dates || []).length ? `<details class="disclosure"><summary>原库保留的 ${(detail.excluded_non_trading_dates || []).length} 个非交易日</summary><p class="history-note">${detail.excluded_non_trading_dates.map(esc).join('、')}。计算视图按官方日历排除，原记录没有删除或修改。</p></details>` : ''}
    ${(detail.gaps || []).length ? `<details class="disclosure"><summary>${detail.gaps.length} 条缺口 / 异常日期说明</summary><div class="gap-list">${detail.gaps.map(item=>`<p><span class="mono">${esc(item.date)}</span> ${esc(item.reason)}</p>`).join('')}</div></details>` : ''}
    <p class="history-note">${esc(observation.history_note || '当前库版本重建截至该日的行情。抓取时间不等于历史可得时点。')}</p>`;
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
  $('#loading').hidden = true;
  $('#mode-label').textContent = state.mode === 'market' ? '真实观察 · 只读' : state.mode === 'demo' ? '演示数据 · 合成观察' : '正式台账 · 只读';
  $('#as-of').textContent = `观察 ${observation?.effective_date || '未能确定'} · ${state.mode === 'market' ? '不载入正式台账' : `台账记账截至 ${String(state.observation_as_of || state.as_of || '—').replace('T',' ')}`}`;
  $('#footer-source').textContent = state.mode === 'market' ? '真实观察 · 保留来源与口径' : state.mode === 'demo' ? '隔离演示 · 全部为合成数据' : '正式数据 · 只读';
  $('#mode-link').textContent = state.mode === 'demo' ? '正式台账 · 只读 ↗' : '返回演示台账 ↗';
  $('#mode-link').href = route(location.pathname, {mode:state.mode === 'demo' ? 'readonly' : 'demo',card:null});
  $('#mode-link').hidden = state.mode === 'market' || state.mode === 'demo' && state.readonly_available === false || state.mode === 'readonly' && state.demo_available === false;
  $('#mode-link').nextElementSibling.hidden = $('#mode-link').hidden;
  $('#nav-home').href = route('/', {card:null});
  $('#nav-rotation').href = route('/rotation', {card:null});
  $('#nav-home').setAttribute('aria-current',page() === 'home' ? 'page' : 'false');
  $('#nav-rotation').setAttribute('aria-current',page() === 'rotation' ? 'page' : 'false');
  $('#observation-controls').hidden = !observation;
  if (observation) {
    $('#observation-date').value = params().get('as_of') || observation.requested_date || '';
    if (observation.completed_date) $('#observation-date').max = observation.completed_date;
    if (observation.calendar?.first) $('#observation-date').min = observation.calendar.first;
    $('#observation-theme').innerHTML = (observation.containers || []).map(row=>`<option value="${esc(row.theme_id)}" ${row.theme_id === (params().get('theme') || observation.detail?.theme_id) ? 'selected' : ''}>${esc(row.container)} · ${esc(row.theme_id)}</option>`).join('');
    $('#observation-context').textContent = `有效日 ${observation.effective_date || '未确定'} · 库内行情末日 ${observation.actual_data_end || '无'}${observation.requested_date !== observation.effective_date ? ` · 请求 ${observation.requested_date}` : ''}`;
  }
  renderOverview();
  $('#overview').hidden = selectedId !== null;
  $('#detail').hidden = selectedId === null;
  if (!selectedId) $('#breadcrumb').textContent = page() === 'rotation' ? '机会台账 › 轮动观察' : '机会台账 › 机会';
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
    <p class="ledger-time-note">这张卡保留台账记账截至 ${time(state.observation_as_of || state.as_of)} 的记录。页面观察日期不回写卡片，也不把后来结果解释为当时已知。</p>
    <div class="detail-grid"><div>
      <section class="detail-section"><div class="section-heading"><h2>当时如何约定</h2><span class="eyebrow">创建时冻结</span></div><dl class="fact-list">${fact('关注时点', `${time(card.created_at)} · 对应 ${esc(card.close_date)} 收盘`)}${fact('量化预期', `${expectation} · 对照 ${esc(card.expectation_benchmark)}`)}${fact('价格失效位', `<span class="mono">${number(card.invalidation_price,3)}</span> · 创建时锁定`)}${fact('风险刻度', `1R = <span class="mono">${number(card.r_unit_per_share,3)}</span> / 份 · 计划仓位 ${number(card.planned_size_pct)}%`)}${fact('跟踪约定', `出场后继续跟踪 ${esc(card.tracking_days)} 个交易日`)}${card.thesis_inval_statement ? fact('论点失效', `${esc(card.thesis_inval_statement)}${card.thesis_inval_deadline ? ` · ${time(card.thesis_inval_deadline)}` : ''}`) : ''}${card.supersedes ? fact('重建自', esc(card.supersedes)) : ''}</dl></section>
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
    const search=params();
    const observationQuery=new URLSearchParams({weeks:'12'});
    ['as_of','theme','series'].forEach(key=>{if(search.get(key)) observationQuery.set(key,search.get(key));});
    let currentObservation;
    try { currentObservation=await api(`/api/observation?${observationQuery}`); }
    catch(error) { currentObservation={reason:error.message,containers:[],weeks:[],rotation:[],detail:null}; notify(error.message); }
    if (sequence !== loadSequence) return;
    observation=currentObservation;
    const normalized=params(); normalized.set('mode',state.mode);
    if (!normalized.get('as_of') && observation.requested_date) normalized.set('as_of',observation.requested_date);
    if (!normalized.get('theme') && observation.detail?.theme_id) normalized.set('theme',observation.detail.theme_id);
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
try { setTheme(localStorage.getItem('etf-ledger-theme') === 'light' ? 'light' : 'dark'); } catch (_) { setTheme('dark'); }
$('#theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
$('#home-button').addEventListener('click', () => { if (state) navigate(route('/',{card:null})); });
['nav-home','nav-rotation'].forEach(id=>$('#'+id).addEventListener('click',event=> {if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button!==0)return;event.preventDefault();navigate(route(id==='nav-home'?'/':'/rotation',{card:null}));}));
$('#observation-controls').addEventListener('submit',event=> {event.preventDefault();navigate(route(location.pathname,{as_of:$('#observation-date').value,theme:$('#observation-theme').value,card:null}));});
window.addEventListener('popstate',()=> {selectedId=params().get('card');loadPage();});
document.addEventListener('keydown', event => { if (event.key === 'Escape' && selectedId) showHome(); });
loadPage();
