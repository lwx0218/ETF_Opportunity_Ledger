'use strict';

const assert = require('assert');
const fs = require('fs');
const {readingHref, navHref, renderDecision, heatClass, shortState, rotationHeadline, homeHeadline, pickCandidate, registryOnPage} = require('../../src/web/static/app.js');

function query(href) {
  return new URLSearchParams(href.slice(href.indexOf('?') + 1));
}

for (const series of ['research', 'execution', 'price_candidate']) {
  const search = `mode=market&as_of=2026-09-30&theme=T02&series=${series}`;
  const cell = query(readingHref(search, 'T01', '2026-09-25', series, 'market'));
  assert.strictEqual(cell.get('series'), series);
  assert.strictEqual(cell.get('theme'), 'T01');
  assert.strictEqual(cell.get('as_of'), '2026-09-25');
  assert.strictEqual(cell.get('card'), null);
  assert.strictEqual(cell.get('mode'), 'market');
  const nav = query(navHref(search, '/rotation', 'market'));
  assert.strictEqual(nav.get('series'), series);
  assert.strictEqual(nav.get('theme'), 'T02');
  assert.strictEqual(nav.get('card'), null);
  const home = query(navHref(search, '/', 'market'));
  assert.strictEqual(home.get('series'), series);
}

const mismatched = query(readingHref('mode=market&series=execution&theme=T02', 'T01', '2026-09-30', 'research', 'market'));
assert.strictEqual(mismatched.get('series'), 'research');
assert.strictEqual(mismatched.get('theme'), 'T01');

const candidate = {
  card: {state_at_entry: null, crowd_rs_1m_rank: null, trigger_type: '事件驱动', invalidation_price: 10.5,
         thesis_inval_statement: '到观察日仍无可核验证据', scoring_rule: 'schema-v1-§3'},
  evidence: [], daily: [], signals: [],
};
const holding = {
  card: {state_at_entry: 'XB', crowd_rs_1m_rank: 4, trigger_type: '事件驱动', invalidation_price: 129.6,
         thesis_inval_statement: '论点到期', scoring_rule: 'schema-v1-§3'},
  evidence: [{summary: 'a'}, {summary: 'b'}],
  daily: [{date: '2026-09-30', stop_now: 130.2}],
  signals: [],
};
const pending = {
  card: holding.card,
  evidence: holding.evidence,
  daily: holding.daily,
  signals: [{signal_date: '2026-09-30', reason: '手动', manual_reason: '先离场', signal_close: 131}],
};
const exited = {
  card: holding.card,
  evidence: holding.evidence,
  daily: [{date: '2026-09-30', stop_now: 128}],
  signals: [{signal_date: '2026-09-28', reason: '手动'}],
  exit: {exit_date: '2026-09-29', exit_reason: '手动'},
};

for (const [name, data, expected, absent] of [
  ['candidate', candidate, ['当时为何触发', '现在按什么条件退出', '事件驱动', '10.500', '到观察日仍无可核验证据', 'schema-v1-§3'], ['等待后续交易日开盘成交']],
  ['holding', holding, ['XB', '4', '冻结证据', '2', '129.600', '130.200'], ['等待后续交易日开盘成交']],
  ['pending', pending, ['待成交信号', '2026-09-30', '手动', '先离场', '等待后续交易日开盘成交', '130.200'], []],
  ['exited', exited, ['128.000', '129.600'], ['等待后续交易日开盘成交']],
]) {
  const html = renderDecision(data);
  for (const text of expected) assert.ok(html.includes(text), `${name} missing ${text}`);
  for (const text of absent) assert.ok(!html.includes(text), `${name} unexpectedly has ${text}`);
  assert.ok(html.indexOf('当时为何触发') < html.indexOf('现在按什么条件退出'));
}

const blank = renderDecision({card: {}, evidence: null, daily: []});
assert.ok(blank.includes('入场形态'));
assert.equal((blank.match(/—/g) || []).length >= 4, true);

assert.strictEqual(heatClass(0.3), 'heat-up-8');
assert.strictEqual(heatClass(-0.15), 'heat-down-4');
assert.strictEqual(heatClass(null), '');
assert.strictEqual(heatClass(0.6), 'heat-up-8');
assert.strictEqual(heatClass(0.001), '');

for (const [label, expected] of [['上升中', '上升'], ['下跌中', '下跌'], ['回踩', '回踩'], ['遇阻', '遇阻'], ['平台突破', '平台突破'], ['启动', '启动'], ['过热', '过热'], ['破位', '破位'], ['阴跌', '阴跌'], ['超跌反弹', '超跌反弹'], ['无趋势', '无趋势'], [null, '—'], ['', '—']]) {
  assert.strictEqual(shortState(label), expected, String(label));
}

function headlineFixture(complete, ranks) {
  return {
    effective_date: '2026-09-30',
    comparison: {comparison_complete: complete, valid: complete ? 37 : 10, pool: 37},
    containers: ranks.map(([id, name]) => ({theme_id: id, container: name, line: '海外'})),
    rotation: ranks.map(([id, name, rank, rs]) => ({
      theme_id: id,
      cells: [{
        date: '2026-09-30',
        rank: {available: rank != null, value: rank},
        rs_1m: {available: rs != null, value: rs},
      }],
    })),
  };
}
const full = rotationHeadline(headlineFixture(true, [['a', '纳指科技', 1, 0.189], ['b', '原油', 2, 0.1], ['c', '地产', 3, 0.05]]));
assert.strictEqual(full.title, '纳指科技最强，原油和地产跟着。');
assert.ok(full.lead.includes('+18.9%'), full.lead);
assert.ok(full.lead.includes('37 个容器里排第 1'), full.lead);
assert.ok(full.lead.includes('这是价格观察，不是进场信号。'), full.lead);
const incomplete = rotationHeadline(headlineFixture(false, [['a', '纳指科技', 1, 0.189]]));
assert.strictEqual(incomplete.title, '本周横截面不完整，不排名次。');
assert.strictEqual(incomplete.lead, '10/37 个容器有合格相对强弱；缺口原因见各格说明。');

function container(theme, name, code, stateCode, label, available, rank, rs, ext) {
  return {
    theme_id: theme,
    container: name,
    identity: {code},
    fields: {
      state: {available, value: stateCode, state_label: label},
      rank: {available: rank != null, value: rank},
      rs_1m: {available: rs != null, value: rs},
      ext: {available: ext != null, value: ext},
    },
  };
}
const five = {
  containers: [
    container('T01', '银行', '512800', 'XB', '回踩', true, 7, 0.085, 0.2),
    container('T02', '红利', '510880', 'NEUTRAL', '无趋势', true, 5, 0.01, 0),
    container('T03', '原油', '501018', 'EXH', '过热', true, 1, 0.2, 2.4),
    container('T04', '黄金', '518880', 'XB', '回踩', false, 2, null, null),
    container('T05', '地产', '512200', 'XB', '回踩', true, 3, 0.121, 0.9),
  ],
};
const picked = pickCandidate(five);
assert.strictEqual(picked.candidate.container, '地产');
assert.strictEqual(picked.candidate.code, '512200');
assert.strictEqual(picked.candidate.rank, 3);
assert.strictEqual(picked.enterable.length, 2);
assert.deepStrictEqual(picked.others.map(row => row.container), ['银行']);
assert.deepStrictEqual(picked.adverse.map(row => row.container), ['原油']);
assert.strictEqual(picked.available, 4);
assert.strictEqual(picked.unavailable, 1);
assert.strictEqual(picked.pool, 5);
assert.ok(picked.enterable.every(row => row.container !== '黄金'));
assert.ok(picked.adverse.every(row => row.container !== '红利'));

function pool(size, enterableRanks) {
  const containers = [];
  for (let index = 0; index < size; index += 1) {
    const rank = index + 1;
    const enterable = enterableRanks.includes(rank);
    containers.push(container(`T${String(rank).padStart(2, '0')}`, enterable ? `可进${rank}` : `容器${rank}`, String(510000 + rank), enterable ? 'POP' : 'NEUTRAL', enterable ? '启动' : '无趋势', true, rank, enterable ? 0.1 : 0, 0.4));
  }
  return {containers};
}
const three = homeHeadline(pool(37, [3, 8, 7]), {mode: 'market', cards: []});
assert.strictEqual(three.title, '37 个容器里 3 个处于可进态，没有在跑的判断。');
assert.ok(three.lead.startsWith('最强的一个是可进3 510003：启动，名次 3，近 1 月相对沪深300 +10.0%。'), three.lead);
assert.ok(three.lead.endsWith('规则未启用，尚未扫描；这是观察，不是进场。'), three.lead);
const none = homeHeadline(pool(37, []), {mode: 'readonly', cards: [], rules: {enabled: []}});
assert.strictEqual(none.title, '37 个容器里没有处于可进态的，没有在跑的判断。');
assert.ok(none.lead.startsWith('最强的一个是容器1 510001：无趋势，名次 1，近 1 月相对沪深300 0.0%。'), none.lead);
assert.ok(!none.lead.includes('可进态'), none.lead);
const carded = homeHeadline(five, {mode: 'demo', cards: [{status: '当下'}, {status: '当下'}, {status: '候选'}]});
assert.strictEqual(carded.title, '2 笔正在验证，1 笔等待进场。');
assert.strictEqual(carded.lead, '');

assert.strictEqual(registryOnPage('market'), true);
assert.strictEqual(registryOnPage('home'), false);
assert.strictEqual(registryOnPage('rotation'), false);
const source = fs.readFileSync(require.resolve('../../src/web/static/app.js'), 'utf8');
assert.ok(source.includes('registryOnPage(page()) ? renderRegistry()'));
assert.strictEqual(source.split('renderRegistry(').length - 1, 2);
