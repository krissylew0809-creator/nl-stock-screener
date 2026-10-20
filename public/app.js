const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let state = { conditions: [], levels: {}, result: null, tab: 'selected', sel: new Set(), metrics: {} };
const OPS = { gte: '≥', lte: '≤', gt: '>', lt: '<', between: '介于' };
const EXAMPLES = ['经营改善、估值合理、走势相对稳定', '高成长、估值合理', '低负债、现金流健康、低估值', '高弹性、走势稳定', '稳赚不赔的股票，明天涨停'];

async function api(path, body, method) {
  try {
    const r = await fetch(path, body !== undefined ? { method: method || 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : method ? { method } : undefined);
    const j = await r.json(); if (!r.ok) throw new Error(j.error ? j.error + (j.details ? '：' + j.details.join('；') : '') : 'HTTP ' + r.status); return j;
  } catch (e) { throw new Error(e.message || '网络错误'); }
}
const banner = (cls, html) => `<div class="banner ${cls}">${html}</div>`;
const fmtV = v => Array.isArray(v) ? v.join(' ~ ') : v;

async function init() {
  $('examples').innerHTML = EXAMPLES.map(e => `<button data-q="${esc(e)}">${esc(e)}</button>`).join('');
  $('examples').onclick = e => { if (e.target.dataset.q) { $('q').value = e.target.dataset.q; parse(); } };
  try {
    const s = await api('/api/status'); state.metrics = s.metrics; $('disc').textContent = s.disclaimer;
    $('modeBanner').innerHTML = s.mode === 'demo' ? banner('b-warn', '⚠ 当前为<b>示例数据模式</b>（未配置 FUYAO_API_KEY）：所有数值为合成数据，仅用于演示流程，不代表真实行情或财务。') : banner('b-ok', `已连接扶摇真实数据 · 股票池 ${s.universeSize} 只${s.llm ? ' · LLM 解析已启用' : ' · 规则解析'}`);
  } catch (e) { $('modeBanner').innerHTML = banner('b-bad', '后端不可用：' + esc(e.message)); }
  loadSaved();
}

async function parse() {
  const text = $('q').value.trim(); if (!text) return;
  $('btnParse').disabled = true; $('parseInfo').textContent = '解析中…'; $('compliance').innerHTML = '';
  try {
    const r = await api('/api/parse', { text, levels: state.levels });
    $('parseInfo').textContent = `解析器：${r.parser}`;
    if (r.compliance.blocked) { $('condCard').hidden = $('resCard').hidden = $('sensCard').hidden = true; $('compliance').innerHTML = banner('b-bad', `<b>无法按该描述生成选股：</b>${esc(r.compliance.reason)}。本工具不预测涨跌、不承诺收益、不给出买卖建议。你可以改为描述可量化的特征，如“估值合理、业绩改善、走势稳定”。`); return; }
    if (!r.conditions.length) { $('condCard').hidden = true; $('compliance').innerHTML = banner('b-warn', '没能把这段描述转成可执行条件。请换成如“经营改善 / 估值合理 / 走势稳定 / 现金流健康 / 低负债 / 高成长”等表述，或直接在下方手动添加条件。') + (r.llmNote ? banner('b-warn', esc(r.llmNote)) : ''); state.conditions = []; renderCond(r); $('condCard').hidden = false; return; }
    state.conditions = r.conditions; renderCond(r); $('condCard').hidden = false;
  } catch (e) { $('compliance').innerHTML = banner('b-bad', esc(e.message)); } finally { $('btnParse').disabled = false; }
}

function renderCond(r) {
  r = r || {};
  $('clar').innerHTML = (r.clarifications || []).map(c => `<div class="opt"><b>${esc(c.question)}</b>` + c.options.map(o => `<label><input type="radio" name="lv_${esc(c.term)}" data-term="${esc(c.term)}" value="${o.level}" ${o.level === c.level ? 'checked' : ''}> ${{ strict: '严格', standard: '标准', loose: '宽松' }[o.level]}：<span class="sub">${esc(o.desc)}</span></label>`).join('') + '</div>').join('');
  $('clar').onchange = async e => { if (e.target.dataset.term) { state.levels[e.target.dataset.term] = e.target.value; await parse(); } };
  $('conflicts').innerHTML = (r.conflicts || []).map(c => banner(c.severity === 'hard' ? 'b-bad' : 'b-warn', (c.severity === 'hard' ? '⛔ 条件冲突：' : '⚠ 注意：') + esc(c.message))).join('');
  $('unmatched').innerHTML = (r.unmatched || []).length ? banner('b-warn', '以下表述未能量化，<b>未参与筛选</b>：' + r.unmatched.map(esc).join('、')) : '';
  if (r.llmNote) $('unmatched').innerHTML += banner('b-warn', esc(r.llmNote));
  drawConds();
}
function drawConds() {
  $('condRows').innerHTML = state.conditions.map((c, i) => {
    const m = state.metrics[c.metric] || {};
    const val = c.op === 'between' ? `<input size="4" data-i="${i}" data-k="lo" value="${c.value[0]}"> ~ <input size="4" data-i="${i}" data-k="hi" value="${c.value[1]}">` : `<input size="6" data-i="${i}" data-k="v" value="${c.value}">`;
    return `<tr><td><input type="checkbox" data-i="${i}" data-k="en" ${c.enabled ? 'checked' : ''}></td><td>${esc(c.label)}</td>
    <td><select data-i="${i}" data-k="op">${Object.entries(OPS).map(([k, s]) => `<option value="${k}" ${k === c.op ? 'selected' : ''}>${s}</option>`).join('')}</select> ${val} ${esc(c.unit)}</td>
    <td>${esc(c.term)}</td><td class="sub">${esc(m.source || '')}${m.note ? '<br>' + esc(m.note) : ''}</td><td><button data-i="${i}" data-k="del">删</button></td></tr>`;
  }).join('') || '<tr><td colspan="6" class="sub">暂无条件</td></tr>';
}
$('condRows').addEventListener('change', e => { const t = e.target, i = +t.dataset.i, c = state.conditions[i]; if (!c) return; const k = t.dataset.k;
  if (k === 'en') c.enabled = t.checked;
  else if (k === 'op') { c.op = t.value; c.value = t.value === 'between' ? [0, +(Array.isArray(c.value) ? c.value[1] : c.value) || 0] : (Array.isArray(c.value) ? c.value[0] : c.value); drawConds(); }
  else if (k === 'v') c.value = t.value;
  else if (k === 'lo') c.value = [t.value, c.value[1]]; else if (k === 'hi') c.value = [c.value[0], t.value];
  c.level = 'custom'; });
$('condRows').addEventListener('click', e => { if (e.target.dataset.k === 'del') { state.conditions.splice(+e.target.dataset.i, 1); drawConds(); } });
$('btnAdd').onclick = () => { const keys = Object.keys(state.metrics); const k = prompt('指标代码（' + keys.map(x => x + '=' + state.metrics[x].label).join('，') + '）', 'pe_ttm'); if (!state.metrics[k]) return; state.conditions.push({ id: 'u' + Date.now(), term: '自定义', metric: k, op: 'lte', value: 30, enabled: true, label: state.metrics[k].label, unit: state.metrics[k].unit, level: 'custom' }); drawConds(); };

async function run() {
  $('btnRun').disabled = true; $('btnRun').textContent = '筛选中…（真实数据首次约需数十秒）';
  try {
    const r = await api('/api/screen', { conditions: state.conditions, missingPolicy: $('policy').value }); state.result = r; state.sel.clear();
    state.tab = r.summary.selected ? 'selected' : 'excluded'; renderResult(); $('resCard').hidden = $('sensCard').hidden = false; $('resCard').scrollIntoView({ behavior: 'smooth' });
  } catch (e) { alert('筛选失败：' + e.message); } finally { $('btnRun').disabled = false; $('btnRun').textContent = '运行筛选'; }
}
$('btnRun').onclick = run; $('btnParse').onclick = parse;

function renderResult() {
  const r = state.result, d = r.dataStatus;
  $('status').innerHTML = d.warnings.map(w => banner(d.mode === 'demo' ? 'b-warn' : 'b-bad', esc(w))).join('') + (d.asofRange ? `<div class="sub">数据时点范围：${d.asofRange[0]} ~ ${d.asofRange[1]}（各指标时点见每条明细）</div>` : '');
  const s = r.summary;
  $('summary').innerHTML = `股票池 <b>${s.total}</b> 只 → 入选 <b>${s.selected}</b> · 排除 <b>${s.excluded}</b> · 待定(数据缺失) <b>${s.undetermined}</b>` + (r.conflicts.length ? r.conflicts.map(c => banner(c.severity === 'hard' ? 'b-bad' : 'b-warn', esc(c.message))).join('') : '') + (r.zeroResultHint ? banner('b-warn', esc(r.zeroResultHint)) : '');
  const tabs = [['selected', `入选 ${s.selected}`], ['excluded', `已排除 ${s.excluded}`], ['undetermined', `待定 ${s.undetermined}`]];
  $('tabs').innerHTML = tabs.map(([k, l]) => `<button data-t="${k}" class="${state.tab === k ? 'on' : ''}">${l}</button>`).join('');
  $('tabs').onclick = e => { if (e.target.dataset.t) { state.tab = e.target.dataset.t; renderResult(); } };
  const pick = row => state.tab === 'selected' ? row.verdict.startsWith('selected') : row.verdict === state.tab;
  let rows = r.rows.filter(pick); if (state.tab === 'excluded') rows.sort((a, b) => a.failCount - b.failCount);
  $('list').innerHTML = rows.map(stockHtml).join('') || '<div class="sub">此分组没有股票。</div>';
  $('list').onchange = e => { const c = e.target.dataset.code; if (c) { e.target.checked ? state.sel.add(c) : state.sel.delete(c); } };
  $('list').onclick = e => { if (e.target.type === 'checkbox') e.stopPropagation(); };
  $('actions').innerHTML = `<button id="aCmp">比较所选</button><button id="aBt">历史回看</button><button id="aSave">保存本次筛选</button><button id="aMon">转为监控任务</button><span class="sub">先在列表中勾选股票（比较/回看用）</span>`;
  $('aCmp').onclick = compare; $('aBt').onclick = backtest; $('aSave').onclick = saveRun; $('aMon').onclick = monitor;
  renderSens();
}
function stockHtml(row) {
  const label = { selected: '入选', selected_incomplete: '入选(数据不完整)', excluded: '排除', undetermined: '待定' }[row.verdict];
  const why = row.verdict === 'excluded' ? row.checks.filter(c => c.status === 'fail').map(c => `${c.label} ${c.value}${c.unit} 不满足 ${c.rule}`).join('；') : row.verdict === 'undetermined' ? '缺少：' + row.checks.filter(c => c.status === 'missing').map(c => c.label).join('、') : row.verdict === 'selected_incomplete' ? '缺少：' + row.checks.filter(c => c.status === 'missing').map(c => c.label).join('、') + '（已按忽略缺失入选）' : `${row.checks.length} 项条件全部满足`;
  return `<details class="stock"><summary><input type="checkbox" data-code="${row.code}" ${state.sel.has(row.code) ? 'checked' : ''}><b>${esc(row.name)}</b><span class="mono">${row.code}</span><span class="tag ${row.verdict.startsWith('selected') ? 't-pass' : row.verdict === 'excluded' ? 't-fail' : 't-missing'}">${label}</span><span class="sub">${esc(why)}</span></summary>
  <div class="body"><table><thead><tr><th>条件</th><th>要求</th><th>实际值</th><th>时点 · 来源字段</th><th>结果</th></tr></thead><tbody>${row.checks.map(c => `<tr><td>${esc(c.label)}</td><td class="num">${esc(c.rule)}</td><td class="num">${c.status === 'missing' ? '—' : esc(c.value) + esc(c.unit)}</td>
  <td class="sub">${c.status === 'missing' ? esc(c.reason) : esc(c.asof) + ' · ' + esc(c.src) + '<br>' + esc(c.field)}</td><td><span class="tag t-${c.status}">${{ pass: '满足', fail: '未满足', missing: '数据缺失' }[c.status]}</span>${c.status === 'fail' ? `<div class="sub">差 ${c.gap}${esc(c.unit)}；放宽到 ${esc(fmtV(c.need))} 即满足</div>` : ''}</td></tr>`).join('')}</tbody></table></div></details>`;
}
function renderSens() {
  const s = state.result.sensitivity;
  $('sens').innerHTML = `<div class="sub">基于当前数据，逐条去掉某个条件后重新计算（当前入选 ${s.baseSelected} 只）。</div><table><thead><tr><th>如果去掉</th><th>入选数变化</th><th>新增入选</th></tr></thead><tbody>` +
    s.perCondition.map(p => `<tr><td>${esc(p.label)} ${esc(p.rule)}</td><td class="num">${p.ifRemoved.selected}（${p.ifRemoved.delta >= 0 ? '+' : ''}${p.ifRemoved.delta}）</td><td>${p.ifRemoved.added.slice(0, 8).map(a => esc(a.name)).join('、') || '—'}${p.ifRemoved.added.length > 8 ? ' 等' : ''}</td></tr>`).join('') + '</tbody></table>' +
    `<h2 style="margin-top:14px">差一点入选（仅差 1 项条件）</h2>` + (s.nearMiss.length ? `<table><thead><tr><th>股票</th><th>未满足</th><th>实际值</th><th>放宽到即可入选</th></tr></thead><tbody>${s.nearMiss.slice(0, 15).map(n => `<tr><td>${esc(n.name)} <span class="mono">${n.code}</span></td><td>${esc(n.label)} ${esc(n.rule)}</td><td class="num">${n.value}${esc(n.unit)}</td><td class="num">${esc(fmtV(n.need))}${esc(n.unit)}</td></tr>`).join('')}</tbody></table>` : '<div class="sub">没有。</div>');
}
function codes() { return [...state.sel]; }
function compare() {
  const c = codes(); if (c.length < 2) return alert('请至少勾选 2 只股票');
  const rows = state.result.rows.filter(r => c.includes(r.code)); const labels = [...new Set(rows.flatMap(r => r.checks.map(k => k.label)))];
  show(`<table><thead><tr><th>指标</th>${rows.map(r => `<th>${esc(r.name)}</th>`).join('')}</tr></thead><tbody>${labels.map(l => `<tr><td>${esc(l)}</td>${rows.map(r => { const k = r.checks.find(x => x.label === l); return `<td class="num">${!k ? '' : k.status === 'missing' ? '<span class="tag t-missing">缺失</span>' : esc(k.value) + esc(k.unit) + ` <span class="tag t-${k.status}">${k.status === 'pass' ? '✓' : '✗'}</span>`}</td>`; }).join('')}</tr>`).join('')}<tr><td>结论</td>${rows.map(r => `<td>${r.verdict.startsWith('selected') ? '入选' : r.verdict === 'excluded' ? '排除' : '待定'}</td>`).join('')}</tr></tbody></table>`);
}
async function backtest() {
  const c = codes().length ? codes() : state.result.rows.filter(r => r.verdict.startsWith('selected')).map(r => r.code); if (!c.length) return alert('没有可回看的股票');
  show('计算中…');
  try {
    const r = await api('/api/backtest', { codes: c, days: 60 }); const W = 640, H = 200, all = [...r.portfolio.curve, ...r.baseline.curve], lo = Math.min(...all), hi = Math.max(...all);
    const path = cv => cv.map((v, i) => (i ? 'L' : 'M') + (i / (cv.length - 1) * W).toFixed(1) + ' ' + (H - (v - lo) / (hi - lo || 1) * (H - 10) - 5).toFixed(1)).join('');
    show(`${r.dataStatus.warnings.map(w => banner('b-warn', esc(w))).join('')}<div class="sub">过去 ${r.days} 个交易日 · 所选 ${r.n} 只等权 vs 股票池 ${r.baselineN} 只等权（${r.dates[0]} ~ ${r.dates[r.dates.length - 1]}）</div>
    <svg viewBox="0 0 ${W} ${H}" width="100%"><path d="${path(r.baseline.curve)}" fill="none" stroke="#98a2b3" stroke-width="2"/><path d="${path(r.portfolio.curve)}" fill="none" stroke="#2457d6" stroke-width="2.5"/></svg>
    <div><span style="color:#2457d6">━</span> 所选组合 ${r.portfolio.totalReturnPct}%（最大回撤 ${r.portfolio.maxDrawdownPct}%） &nbsp; <span style="color:#98a2b3">━</span> 股票池基准 ${r.baseline.totalReturnPct}%（最大回撤 ${r.baseline.maxDrawdownPct}%）</div>
    <ul class="sub">${r.caveats.map(x => '<li>' + esc(x) + '</li>').join('')}</ul>`);
  } catch (e) { show(banner('b-bad', esc(e.message))); }
}
function show(h) { $('toolCard').hidden = false; $('tool').innerHTML = h; $('toolCard').scrollIntoView({ behavior: 'smooth' }); }
async function saveRun() { const name = prompt('给这次筛选起个名字', $('q').value.slice(0, 20)); if (!name) return; await api('/api/saved', { name, text: $('q').value, conditions: state.conditions, codes: state.result.rows.filter(r => r.verdict.startsWith('selected')).map(r => r.code) }); loadSaved(); }
async function monitor() { const name = prompt('监控任务名称', $('q').value.slice(0, 20)); if (!name) return; try { await api('/api/monitors', { name, conditions: state.conditions }); loadSaved(); alert('已创建：以当前入选名单为基线，之后点“立即检查”可看到新进入/退出的股票。'); } catch (e) { alert(e.message); } }
async function loadSaved() {
  try {
    const [s, m] = await Promise.all([api('/api/saved'), api('/api/monitors')]);
    $('saved').innerHTML = (s.length ? '<b>已保存</b><ul>' + s.map(x => `<li>${esc(x.name)} · ${x.codes.length} 只 · ${esc(x.savedAt)} <button data-load="${x.id}">载入条件</button> <button data-del="saved/${x.id}">删</button></li>`).join('') + '</ul>' : '') +
      (m.length ? '<b>监控任务</b><ul>' + m.map(x => `<li>${esc(x.name)} · 基线 ${x.baseline.length} 只${x.mode === 'demo' ? '（示例数据）' : ''} <button data-run="${x.id}">立即检查</button> <button data-del="monitors/${x.id}">删</button>${x.lastRun ? `<div class="sub">${esc(x.lastRun.at)}：现入选 ${x.lastRun.count} 只；新进入 ${x.lastRun.entered.map(a => esc(a.name)).join('、') || '无'}；退出 ${x.lastRun.left.map(a => esc(a.name)).join('、') || '无'}${x.lastRun.dataStatus.warnings.length ? ' ⚠ ' + esc(x.lastRun.dataStatus.warnings[0]) : ''}</div>` : ''}</li>`).join('') + '</ul>' : '') || '暂无。';
    $('saved').onclick = async e => { const t = e.target;
      if (t.dataset.del) { await api('/api/' + t.dataset.del, undefined, 'DELETE'); loadSaved(); }
      if (t.dataset.run) { t.textContent = '检查中…'; try { await api(`/api/monitors/${t.dataset.run}/run`, {}); } catch (er) { alert(er.message); } loadSaved(); }
      if (t.dataset.load) { const it = s.find(x => x.id === t.dataset.load); $('q').value = it.text; state.conditions = it.conditions; renderCond({}); $('condCard').hidden = false; } };
  } catch (e) { $('saved').textContent = '加载失败：' + e.message; }
}
init(); parse();
