(() => {
  'use strict';

  // Read by the fallback loader in index.html.
  window.__SUPERAGENTIC_UI__ = true;

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MINUS = '−';
  const DASH = '—';
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const THEME_KEY = 'superagentic.theme';
  const THEMES = ['auto', 'light', 'dark'];
  const THEME_LABEL = { auto: 'Auto', light: 'Light', dark: 'Dark' };

  const TABS = [
    { id: 'team', label: 'Team' },
    { id: 'agents', label: 'Agents' },
    { id: 'checks', label: 'Checks' },
    { id: 'risk', label: 'Risk' },
    { id: 'approvals', label: 'Approvals' },
    { id: 'report', label: 'Report' },
    { id: 'log', label: 'Log' },
  ];

  const LANES = [
    { id: 'data', name: 'Data', icon: 'database', desc: () => 'Checks where prices come from, gaps and spreads.' },
    { id: 'research', name: 'Research', icon: 'flask', desc: () => 'Each agent tests one fixed trading rule.' },
    { id: 'validation', name: 'Validation', icon: 'gauge', desc: (bar) => `Runs the ${bar} gate: never-seen months, costs, random entries.` },
    { id: 'risk', name: 'Risk', icon: 'scale', desc: () => 'One risk and margin limit for all agents together.' },
    { id: 'monitor', name: 'Monitor', icon: 'eye', desc: () => 'Kill switch, forward tests and run health.' },
    { id: 'report', name: 'Report', icon: 'doc', desc: () => 'Writes the daily summary for you.' },
  ];

  const AGENT_STATUS = {
    ok: { label: 'OK', icon: 'check', cls: 'ok' },
    warn: { label: 'Needs a look', icon: 'warn', cls: 'warn' },
    fail: { label: 'Problem', icon: 'cross', cls: 'fail' },
    idle: { label: 'Idle', icon: 'idle', cls: 'idle' },
    planned: { label: 'Planned', icon: 'planned', cls: 'planned' },
  };
  const CHECK_STATUS = {
    fail: { label: 'FAIL', icon: 'cross', cls: 'fail' },
    warn: { label: 'WARN', icon: 'warn', cls: 'warn' },
    pass: { label: 'PASS', icon: 'check', cls: 'pass' },
    info: { label: 'INFO', icon: 'info', cls: 'info' },
  };
  const SEVERITY = { fail: 0, warn: 1, info: 2, pass: 3 };
  const LOG_LEVEL = {
    error: { label: 'ERROR', icon: 'cross', cls: 'fail' },
    warn: { label: 'WARN', icon: 'warn', cls: 'warn' },
    info: { label: 'INFO', icon: 'info', cls: 'info' },
    debug: { label: 'DEBUG', icon: 'idle', cls: 'idle' },
  };
  const GATE = {
    qualified: { label: 'Qualified', icon: 'check', cls: 'qualified' },
    failed: { label: 'Failed the gate', icon: 'cross', cls: 'failed' },
    insufficient: { label: 'Too few trades', icon: 'clock', cls: 'insufficient' },
    blocked: { label: 'Blocked', icon: 'stop', cls: 'blocked' },
  };
  const NOT_TESTED = { label: 'Not tested yet', icon: 'idle', cls: 'idle' };
  const KIND = {
    code: { label: 'Code', icon: 'code' },
    llm: { label: 'AI', icon: 'spark' },
    'code+llm': { label: 'Code + AI', icon: 'spark' },
  };
  const STAGES = [
    { id: 'research', label: 'Research' },
    { id: 'shadow', label: 'Shadow test' },
    { id: 'forward_test', label: 'Forward test' },
    { id: 'live_eligible', label: 'Eligible for money' },
  ];

  const ICONS = {
    check: [['path', { d: 'M3.5 8.5l3 3 6-7' }]],
    cross: [['path', { d: 'M4.5 4.5l7 7M11.5 4.5l-7 7' }]],
    warn: [['path', { d: 'M8 2.2l6.6 11.3H1.4z' }], ['path', { d: 'M8 6.4v3.3' }], ['circle', { cx: 8, cy: 11.7, r: 0.4 }]],
    info: [['circle', { cx: 8, cy: 8, r: 6.3 }], ['path', { d: 'M8 7.3v4.1' }], ['circle', { cx: 8, cy: 4.9, r: 0.4 }]],
    stop: [['path', { d: 'M5.5 1.8h5l3.7 3.7v5l-3.7 3.7h-5l-3.7-3.7v-5z' }], ['path', { d: 'M5.3 8h5.4' }]],
    clock: [['circle', { cx: 8, cy: 8, r: 6.3 }], ['path', { d: 'M8 4.6V8l2.4 1.6' }]],
    idle: [['circle', { cx: 8, cy: 8, r: 2.6, fill: 'currentColor', stroke: 'none' }]],
    planned: [['circle', { cx: 8, cy: 8, r: 5.6, 'stroke-dasharray': '2.2 2.2' }]],
    shield: [['path', { d: 'M8 1.8l5.2 2v4.1c0 3-2.2 5.3-5.2 6.3-3-1-5.2-3.3-5.2-6.3V3.8z' }], ['path', { d: 'M5.6 8.1l1.7 1.7 3.2-3.5' }]],
    database: [['ellipse', { cx: 8, cy: 4, rx: 5, ry: 2 }], ['path', { d: 'M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2' }]],
    flask: [['path', { d: 'M5.8 1.8h4.4M6.7 1.8v4.3L2.8 12.6c-.5.9.1 1.9 1.1 1.9h8.2c1 0 1.6-1 1.1-1.9L9.3 6.1V1.8M4.6 10h6.8' }]],
    gauge: [['path', { d: 'M2.4 11.8a5.6 5.6 0 1 1 11.2 0' }], ['path', { d: 'M8 11.8l2.7-3.6' }]],
    scale: [['path', { d: 'M8 2v12M4.5 14h7M3 4.5h10' }], ['path', { d: 'M3 4.5L1.2 9a2 2 0 0 0 3.6 0zM13 4.5L11.2 9a2 2 0 0 0 3.6 0z' }]],
    eye: [['path', { d: 'M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z' }], ['circle', { cx: 8, cy: 8, r: 2 }]],
    doc: [['path', { d: 'M4 1.8h5.2l3.3 3.2v9.2H4z' }], ['path', { d: 'M9 1.8V5h3.5M6 8.2h4.4M6 10.8h4.4' }]],
    play: [['path', { d: 'M5 3.2v9.6L12.6 8z', fill: 'currentColor' }]],
    power: [['path', { d: 'M8 1.8v6' }], ['path', { d: 'M4.6 4.2a5.2 5.2 0 1 0 6.8 0' }]],
    sun: [['circle', { cx: 8, cy: 8, r: 2.8 }], ['path', { d: 'M8 1.3v1.6M8 13.1v1.6M1.3 8h1.6M13.1 8h1.6M3.3 3.3l1.1 1.1M11.6 11.6l1.1 1.1M3.3 12.7l1.1-1.1M11.6 4.4l1.1-1.1' }]],
    moon: [['path', { d: 'M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z' }]],
    auto: [['circle', { cx: 8, cy: 8, r: 6 }], ['path', { d: 'M8 2v12a6 6 0 0 0 0-12z', fill: 'currentColor' }]],
    chevron: [['path', { d: 'M4.5 6.2L8 9.8l3.5-3.6' }]],
    target: [['circle', { cx: 8, cy: 8, r: 6.2 }], ['circle', { cx: 8, cy: 8, r: 3.2 }], ['circle', { cx: 8, cy: 8, r: 0.5 }]],
    plug: [['path', { d: 'M6 1.8v3M10 1.8v3M4.5 4.8h7v2.6a3.5 3.5 0 0 1-7 0zM8 10.9v3.3' }]],
    spark: [['path', { d: 'M8 1.8l1.5 4.7L14.2 8l-4.7 1.5L8 14.2 6.5 9.5 1.8 8l4.7-1.5z' }]],
    code: [['path', { d: 'M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5' }]],
    logo: [['circle', { cx: 8, cy: 8.6, r: 2.3, fill: 'currentColor' }], ['circle', { cx: 8, cy: 2.6, r: 1.4 }], ['circle', { cx: 13.1, cy: 12.2, r: 1.4 }], ['circle', { cx: 2.9, cy: 12.2, r: 1.4 }], ['path', { d: 'M8 4v2.2M11.9 11.4l-1.9-1.3M4.1 11.4L6 10.1' }]],
  };

  const ui = {
    state: null,
    snapshot: false,
    busy: false,
    tab: 'team',
    expanded: new Set(),
    histWindow: {},
    checkFilter: 'all',
    logFilter: 'all',
    observers: [],
    agentNodes: new Map(),
  };

  // ---------------------------------------------------------------- DOM helpers

  function append(node, kids) {
    for (const kid of kids) {
      if (kid == null || kid === false || kid === true) continue;
      if (Array.isArray(kid)) append(node, kid);
      else node.append(kid instanceof Node ? kid : String(kid));
    }
    return node;
  }

  function setProps(node, props) {
    if (!props) return;
    for (const [key, value] of Object.entries(props)) {
      if (value == null || value === false) continue;
      if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
  }

  function h(tag, props, ...kids) {
    const node = document.createElement(tag);
    setProps(node, props);
    return append(node, kids);
  }

  function s(tag, props, ...kids) {
    const node = document.createElementNS(SVG_NS, tag);
    setProps(node, props);
    return append(node, kids);
  }

  function icon(name, cls) {
    const svg = s('svg', {
      class: cls ? 'icon ' + cls : 'icon', viewBox: '0 0 16 16', 'aria-hidden': 'true', focusable: 'false',
      fill: 'none', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    });
    for (const [tag, attrs] of ICONS[name] || ICONS.idle) svg.append(s(tag, attrs));
    return svg;
  }

  const chip = (def, label) => h('span', { class: 'chip ' + def.cls }, icon(def.icon), label || def.label);
  const statusChip = (status) => chip(AGENT_STATUS[status] || AGENT_STATUS.idle);
  const gateChip = (status) => chip(GATE[status] || NOT_TESTED);
  const controlChip = () => h('span', { class: 'chip control', title: 'A planted pattern that proves the gate can detect a real edge. Never traded.' }, icon('target'), 'CONTROL');

  function kindChip(kind) {
    const def = KIND[kind];
    return def ? h('span', { class: 'chip outline' }, icon(def.icon), def.label) : null;
  }

  function stageChip(stage) {
    if (!stage) return null;
    const known = STAGES.find((st) => st.id === stage);
    if (stage === 'blocked') return null;
    return h('span', { class: 'chip outline' }, 'Stage: ' + (known ? known.label : titleCase(stage)));
  }

  const emptyBox = (message) => h('p', { class: 'empty' }, message);
  const chartEmpty = (message) => h('p', { class: 'chart-empty' }, message);

  function panelHead(title, intro) {
    return h('div', { class: 'panel-head' }, h('h2', null, title), intro ? h('p', null, intro) : null);
  }

  function blockHead(title, intro, id) {
    return h('div', { class: 'block-head' }, h('h3', { id }, title), intro ? h('p', null, intro) : null);
  }

  function setWidth(node, fraction) {
    node.style.width = clamp(fraction, 0, 1) * 100 + '%';
    return node;
  }

  // ---------------------------------------------------------------- formatting

  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const list = (v) => (Array.isArray(v) ? v : []);
  const rec = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
  const str = (v) => (v == null ? '' : String(v));
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const numbers = (v) => list(v).map(num).filter((x) => x != null);
  const r1 = (v) => Math.round(v * 10) / 10;
  const two = (n) => String(n).padStart(2, '0');

  function signed(n, digits) {
    const abs = Math.abs(n).toFixed(digits);
    if (Number(abs) === 0) return abs;
    return (n < 0 ? MINUS : '+') + abs;
  }

  const fmtR = (v, digits = 2) => (num(v) == null ? DASH : signed(v, digits) + 'R');
  const fmtPct = (v, digits = 0) => (num(v) == null ? DASH : (v * 100).toFixed(digits) + '%');
  const fmtPts = (v, digits = 1) => (num(v) == null ? DASH : v.toFixed(digits) + '%');
  const fmtInt = (v) => (num(v) == null ? DASH : Math.round(v).toLocaleString('en-US'));
  const fmtLot = (v) => (num(v) == null ? DASH : v.toFixed(2));
  const fmtCorr = (v) => (v < 0 ? MINUS : '') + Math.abs(v).toFixed(2);

  function fmtWin(v) {
    if (num(v) == null) return DASH;
    return fmtPct(v, Math.abs(v - accuracyBar()) < 0.01 ? 1 : 0);
  }

  function fmtP(v) {
    if (num(v) == null) return DASH;
    if (v < 0.001) return 'p < 0.001';
    return 'p = ' + (v < 0.1 ? v.toFixed(3) : v.toFixed(2));
  }

  function fmtShare(p) {
    return p < 0.01 ? (p * 100).toFixed(1) + '%' : Math.round(p * 100) + '%';
  }

  function fmtTickR(t) {
    if (Math.abs(t) < 1e-9) return '0R';
    const digits = Number.isInteger(t) ? 0 : Number.isInteger(Math.round(t * 1e6) / 1e5) ? 1 : 2;
    return signed(t, digits) + 'R';
  }

  function fmtMoney(v, currency) {
    if (num(v) == null) return DASH;
    try {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD' }).format(v);
    } catch {
      return v.toFixed(2) + ' ' + str(currency);
    }
  }

  function fmtValue(v) {
    if (Array.isArray(v)) return v.map(fmtValue).join(', ');
    if (v && typeof v === 'object') return JSON.stringify(v);
    return str(v);
  }

  function toDate(iso) {
    if (!iso) return null;
    let t = String(iso);
    if (/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(t)) t += 'Z';
    const d = new Date(t);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function fmtDate(iso, withYear = true) {
    const d = toDate(iso);
    if (!d) return DASH;
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}` + (withYear ? ` ${d.getUTCFullYear()}` : '');
  }

  function fmtDateTime(iso) {
    const d = toDate(iso);
    return d ? `${fmtDate(iso)}, ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} UTC` : DASH;
  }

  function fmtClock(iso) {
    const d = toDate(iso);
    return d ? `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}` : DASH;
  }

  function fmtRange(w) {
    const a = toDate(w.start), b = toDate(w.end);
    if (!a || !b) return DASH;
    return `${fmtDate(w.start, a.getUTCFullYear() !== b.getUTCFullYear())} – ${fmtDate(w.end)}`;
  }

  function titleCase(id) {
    return str(id).replace(/[_-]+/g, ' ').trim().replace(/^\w/, (c) => c.toUpperCase());
  }

  function ciOf(w) {
    const ci = w.win_rate_ci;
    if (Array.isArray(ci)) return [num(ci[0]), num(ci[1])];
    if (ci && typeof ci === 'object') return [num(ci.lo), num(ci.hi)];
    return [null, null];
  }

  function accuracyBar() {
    const bar = num(rec(ui.state && ui.state.meta).accuracy_bar);
    return bar == null ? 0.8 : bar;
  }

  function normCheck(status) {
    const k = str(status).toLowerCase();
    if (k === 'ok' || k === 'passed') return 'pass';
    if (k === 'error' || k === 'failed') return 'fail';
    if (k === 'warning') return 'warn';
    return CHECK_STATUS[k] ? k : 'info';
  }

  function normLevel(level) {
    const k = str(level).toLowerCase();
    if (k === 'warning') return 'warn';
    if (k === 'critical' || k === 'fatal') return 'error';
    return LOG_LEVEL[k] ? k : 'info';
  }

  function agentNames(s) {
    const names = new Map(LANES.map((l) => [l.id, l.name + ' lane']).concat([['supervisor', 'Supervisor'], ['research', 'Research agents']]));
    list(s.agents).map(rec).forEach((a) => names.set(a.id, str(a.name) || str(a.id)));
    return names;
  }

  // ---------------------------------------------------------------- data + actions

  function looksLikeState(data) {
    return Boolean(data && typeof data === 'object' && data.meta && typeof data.meta === 'object');
  }

  function errorMessage(status, data) {
    const detail = data && data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) {
      const msgs = detail.map((d) => d && d.msg).filter(Boolean);
      if (msgs.length) return msgs.join('; ');
    }
    if (data && typeof data.message === 'string') return data.message;
    if (data && typeof data.error === 'string') return data.error;
    return `The server answered with an error (HTTP ${status}).`;
  }

  async function api(path, options = {}) {
    const init = { method: options.method || 'GET', headers: { Accept: 'application/json' } };
    if (options.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.body);
    }
    let res;
    try {
      res = await fetch(path, init);
    } catch {
      throw new Error('Cannot reach the local server. Is it still running?');
    }
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) throw new Error(errorMessage(res.status, data));
    return data;
  }

  function setState(data, first = false) {
    if (!looksLikeState(data)) throw new Error('The state data has an unexpected shape (no "meta" section).');
    ui.state = data;
    render(first);
  }

  async function applyResult(data) {
    if (looksLikeState(data)) return setState(data);
    if (data && looksLikeState(data.state)) return setState(data.state);
    return setState(await api('/api/state'));
  }

  async function loadState() {
    try {
      setState(await api('/api/state'), true);
    } catch (err) {
      renderLoadError(err);
    }
  }

  function setBusy(on) {
    ui.busy = on;
    document.body.classList.toggle('is-busy', on);
    const main = document.getElementById('main');
    if (main) main.setAttribute('aria-busy', String(on));
    document.querySelectorAll('.action').forEach((btn) => {
      btn.disabled = on || ui.snapshot;
    });
    const label = document.querySelector('#run-btn .label');
    if (label) label.textContent = on ? 'Running…' : 'Run pipeline';
  }

  function lockAction(btn) {
    btn.classList.add('action');
    if (ui.snapshot) {
      btn.disabled = true;
      btn.title = 'Static snapshot: actions are turned off.';
    } else if (ui.busy) {
      btn.disabled = true;
    }
    return btn;
  }

  async function runPipeline() {
    if (ui.snapshot || ui.busy) return;
    setBusy(true);
    toast('info', 'Running the pipeline. This can take a minute…');
    try {
      await applyResult(await api('/api/run', { method: 'POST' }));
      toast('ok', 'Run finished. You are looking at the new results.');
    } catch (err) {
      toast('error', 'The run failed: ' + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function killSwitchOn() {
    if (ui.snapshot || ui.busy) return;
    setBusy(true);
    try {
      await applyResult(await api('/api/killswitch', { method: 'POST', body: { on: true, confirm: null } }));
      toast('ok', 'Kill switch is ON. Everything is stopped.');
    } catch (err) {
      toast('error', 'Could not turn the kill switch on: ' + err.message);
    } finally {
      setBusy(false);
    }
  }

  function killSwitchOff() {
    if (ui.snapshot || ui.busy) return;
    const ks = rec(rec(ui.state.meta).kill_switch);
    openDialog({
      title: 'Turn the kill switch off?',
      body: [
        h('p', null, 'Agents and the bridge will be allowed to run again.'),
        ks.reason ? h('p', null, 'It was turned on because: ' + str(ks.reason)) : null,
      ],
      requireYes: true,
      confirmLabel: 'Turn off',
      run: async (confirm) => {
        await applyResult(await api('/api/killswitch', { method: 'POST', body: { on: false, confirm } }));
        toast('ok', 'Kill switch is OFF.');
      },
    });
  }

  function approveChange(item) {
    if (ui.snapshot || ui.busy) return;
    openDialog({
      title: 'Approve this change?',
      body: [h('p', null, h('strong', null, str(item.summary) || str(item.id))), diffList(list(item.diff)), h('p', null, 'It takes effect as soon as you confirm.')],
      requireYes: true,
      confirmLabel: 'Approve',
      run: async (confirm) => {
        await applyResult(await api('/api/approvals/' + encodeURIComponent(str(item.id)), { method: 'POST', body: { decision: 'approve', confirm } }));
        toast('ok', 'Change approved.');
      },
    });
  }

  function rejectChange(item) {
    if (ui.snapshot || ui.busy) return;
    openDialog({
      title: 'Reject this change?',
      body: [h('p', null, h('strong', null, str(item.summary) || str(item.id))), h('p', null, 'Nothing changes. The request moves to the history list.')],
      requireYes: false,
      confirmLabel: 'Reject',
      run: async () => {
        await applyResult(await api('/api/approvals/' + encodeURIComponent(str(item.id)), { method: 'POST', body: { decision: 'reject', confirm: null } }));
        toast('ok', 'Change rejected. Nothing was changed.');
      },
    });
  }

  // ---------------------------------------------------------------- shell

  function render(first) {
    const app = document.getElementById('app');
    const scrollY = window.scrollY;
    const focusedId = document.activeElement && document.activeElement.id;
    ui.observers.forEach((o) => o.disconnect());
    ui.observers = [];
    try {
      const s = ui.state;
      app.replaceChildren(renderHeader(s), renderNotices(s), h('div', { class: 'tabs-anchor' }), renderTabs(s), renderMain(s));
    } catch (err) {
      console.error(err);
      renderLoadError(new Error('The page could not be drawn: ' + err.message));
      return;
    }
    app.removeAttribute('aria-busy');
    if (first) applyRoute(false);
    else selectTab(ui.tab);
    if (!first) window.scrollTo(0, scrollY);
    if (focusedId) document.getElementById(focusedId)?.focus({ preventScroll: true });
    document.documentElement.setAttribute('data-ready', 'true');
  }

  function renderLoadError(err) {
    const app = document.getElementById('app');
    app.removeAttribute('aria-busy');
    document.documentElement.setAttribute('data-ready', 'error');
    const retry = h('button', {
      type: 'button', class: 'btn btn-primary btn-sm',
      onclick: () => {
        app.replaceChildren(h('p', { class: 'boot' }, 'Loading the agent desk…'));
        loadState();
      },
    }, 'Try again');
    app.replaceChildren(h('div', { class: 'wrap notices' },
      h('div', { class: 'banner banner-error', role: 'alert' }, icon('warn'),
        h('div', { class: 'banner-body' },
          h('span', { class: 'banner-tag' }, 'Could not load the agent desk'),
          h('p', null, err.message),
          h('p', null, 'Start the local server (see the README), or open a snapshot file that has the data inside.'),
          h('div', null, retry)))));
  }

  function renderHeader(s) {
    const meta = rec(s.meta);
    return h('header', { class: 'top' },
      h('div', { class: 'wrap top-row' },
        h('div', { class: 'brand' },
          h('span', { class: 'brand-mark' }, icon('logo')),
          h('div', null,
            h('h1', null, str(meta.app) || 'Superagentic', meta.version ? h('span', { class: 'ver' }, 'v' + meta.version) : null),
            h('p', { class: 'brand-sub' }, 'Agent desk · last run ', h('time', { datetime: str(meta.generated_at) }, fmtDateTime(meta.generated_at))))),
        h('div', { class: 'top-status' }, dataBadge(meta), llmBadge(meta)),
        h('div', { class: 'top-actions' }, killSwitchControl(meta), runButton()),
        themeButton()));
  }

  function dataBadge(meta) {
    if (meta.data_mode === 'mt5') {
      return h('span', { class: 'badge live', title: 'Prices come from your broker’s MT5 export.' }, icon('check'), 'MT5 broker data');
    }
    return h('span', { class: 'badge demo', title: str(meta.data_note) }, icon('flask'), 'DEMO DATA');
  }

  function llmBadge(meta) {
    const on = meta.llm_mode === 'claude';
    return h('span', { class: 'badge' + (on ? ' ai-on' : ''), title: str(meta.llm_note) }, icon(on ? 'spark' : 'plug'), on ? 'Claude on' : 'AI offline');
  }

  function killSwitchControl(meta) {
    const on = rec(meta.kill_switch).on === true;
    const pill = h('span', { class: 'ks-pill ' + (on ? 'on' : 'off') }, icon(on ? 'stop' : 'check'), on ? 'Kill switch ON' : 'Kill switch OFF');
    const btn = on
      ? h('button', { type: 'button', class: 'btn btn-sm', id: 'ks-btn', onclick: killSwitchOff }, 'Turn off…')
      : h('button', { type: 'button', class: 'btn btn-sm btn-stop', id: 'ks-btn', onclick: killSwitchOn }, icon('power'), 'Stop everything');
    return h('div', { class: 'ks', role: 'group', 'aria-label': 'Kill switch' }, pill, lockAction(btn));
  }

  function runButton() {
    return lockAction(h('button', { type: 'button', class: 'btn btn-primary btn-sm', id: 'run-btn', onclick: runPipeline },
      icon('play'), h('span', { class: 'label' }, ui.busy ? 'Running…' : 'Run pipeline')));
  }

  function themeButton() {
    const mode = currentTheme();
    const next = THEMES[(THEMES.indexOf(mode) + 1) % THEMES.length];
    return h('button', {
      type: 'button', class: 'btn btn-sm btn-icon theme-btn', id: 'theme-btn', title: 'Theme: ' + THEME_LABEL[mode],
      'aria-label': `Theme: ${THEME_LABEL[mode]}. Switch to ${THEME_LABEL[next]}.`, onclick: () => setTheme(next),
    }, icon(mode === 'auto' ? 'auto' : mode === 'light' ? 'sun' : 'moon'), h('span', null, THEME_LABEL[mode]));
  }

  function renderNotices(s) {
    const meta = rec(s.meta);
    const ks = rec(meta.kill_switch);
    const safe = rec(meta.safe_mode);
    const items = [];
    if (ks.on === true) {
      items.push(banner('kill', 'stop', 'Kill switch is on', [
        'Everything is stopped: no agent output reaches the bridge.',
        ks.reason ? 'Reason: ' + ks.reason : null,
        ks.changed_at ? 'Since ' + fmtDateTime(ks.changed_at) + '.' : null,
      ]));
    }
    if (safe.on === true) {
      items.push(banner('safe', 'warn', 'Safe mode', [
        'Settings or test plans changed without your YES. Nothing is sent to the bridge until you approve or undo the change.',
        safe.reason ? 'Reason: ' + safe.reason : null,
      ]));
    }
    if (meta.data_mode !== 'mt5') {
      items.push(banner('demo', 'flask', 'Demo data', [meta.data_note || 'Synthetic demo data.', meta.eligible_note]));
    }
    if (ui.snapshot) {
      items.push(banner('static', 'info', 'Static snapshot', ['Buttons are off here. Use the local server to run, approve changes or stop everything.']));
    }
    items.push(callout());
    return h('div', { class: 'wrap notices' }, items);
  }

  function banner(kind, iconName, tag, lines) {
    return h('div', { class: 'banner banner-' + kind }, icon(iconName),
      h('div', { class: 'banner-body' },
        h('span', { class: 'banner-tag' }, tag),
        lines.filter(Boolean).map((line) => h('p', null, str(line)))));
  }

  function callout() {
    const bar = fmtPct(accuracyBar());
    return h('aside', { class: 'callout', 'aria-label': 'How an agent qualifies' }, icon('target'),
      h('p', null,
        h('strong', null, `The ${bar} bar. `),
        `An agent qualifies only if it wins at least ${bar} of its trades in months it has never seen, still makes money after costs, and beats random entries. Break-even trades don’t count as wins. `,
        h('strong', null, '1R'), ' = the amount risked on one trade.'));
  }

  function renderTabs(s) {
    const pending = list(rec(s.approvals).pending).length;
    const tablist = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Sections' }, TABS.map((t) => {
      const btn = h('button', {
        type: 'button', class: 'tab', role: 'tab', id: 'tab-' + t.id,
        'aria-controls': 'panel-' + t.id, 'aria-selected': 'false', tabindex: '-1',
        onclick: () => goTab(t.id), onkeydown: onTabKey,
      }, t.label);
      if (t.id === 'approvals' && pending > 0) {
        btn.append(h('span', { class: 'count' }, h('span', { 'aria-hidden': 'true' }, String(pending)), h('span', { class: 'sr-only' }, `, ${pending} waiting for your YES`)));
      }
      return btn;
    }));
    return h('div', { class: 'tabs-bar' }, h('div', { class: 'wrap' }, tablist));
  }

  function renderMain(s) {
    const builders = { team: renderTeam, agents: renderAgents, checks: renderChecks, risk: renderRisk, approvals: renderApprovals, report: renderReport, log: renderLog };
    const main = h('main', { id: 'main', class: 'wrap', tabindex: '-1' });
    for (const t of TABS) {
      const panel = h('section', { class: 'panel', role: 'tabpanel', id: 'panel-' + t.id, 'aria-labelledby': 'tab-' + t.id, hidden: true });
      try {
        append(panel, [builders[t.id](s)]);
      } catch (err) {
        console.error(err);
        panel.replaceChildren(emptyBox('This section could not be shown: ' + err.message));
      }
      main.append(panel);
    }
    return main;
  }

  // ---------------------------------------------------------------- routing + theme

  function parseHash() {
    let raw = location.hash.replace(/^#/, '');
    try {
      raw = decodeURIComponent(raw);
    } catch {
      raw = '';
    }
    const [tab, ...rest] = raw.split('/');
    return { tab: TABS.some((t) => t.id === tab) ? tab : null, sub: rest.join('/') || null };
  }

  function applyRoute(fromNavigation) {
    const { tab, sub } = parseHash();
    selectTab(tab || ui.tab, fromNavigation);
    if (tab === 'agents' && sub) setExpanded(sub, true, true);
  }

  function goTab(id, focus) {
    const route = parseHash();
    if (route.tab !== id || route.sub) {
      try {
        history.pushState(null, '', '#' + id);
      } catch {
        location.hash = id;
      }
    }
    selectTab(id, true);
    if (focus) document.getElementById('tab-' + id)?.focus();
  }

  function selectTab(id, scrollUp) {
    ui.tab = id;
    for (const t of TABS) {
      const btn = document.getElementById('tab-' + t.id);
      const panel = document.getElementById('panel-' + t.id);
      if (!btn || !panel) continue;
      const on = t.id === id;
      btn.setAttribute('aria-selected', String(on));
      btn.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
      if (on) revealTab(btn);
    }
    const anchor = document.querySelector('.tabs-anchor');
    if (scrollUp && anchor && window.scrollY > anchor.offsetTop) window.scrollTo(0, anchor.offsetTop);
  }

  function revealTab(btn) {
    const strip = btn.parentElement;
    const left = btn.offsetLeft;
    const right = left + btn.offsetWidth;
    if (left < strip.scrollLeft) strip.scrollLeft = left - 16;
    else if (right > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = right - strip.clientWidth + 16;
  }

  function onTabKey(e) {
    const index = TABS.findIndex((t) => 'tab-' + t.id === e.currentTarget.id);
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 };
    if (!(e.key in moves)) return;
    e.preventDefault();
    goTab(TABS[(moves[e.key] + TABS.length) % TABS.length].id, true);
  }

  function storedTheme() {
    try {
      const value = localStorage.getItem(THEME_KEY);
      return THEMES.includes(value) ? value : 'auto';
    } catch {
      return 'auto';
    }
  }

  function currentTheme() {
    const value = document.documentElement.getAttribute('data-theme');
    return value === 'light' || value === 'dark' ? value : 'auto';
  }

  function applyTheme(mode) {
    if (mode === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', mode);
  }

  function setTheme(mode) {
    applyTheme(mode);
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch {
      /* storage can be blocked; the theme still applies for this visit */
    }
    const old = document.querySelector('.theme-btn');
    if (old) {
      const btn = themeButton();
      old.replaceWith(btn);
      btn.focus();
    }
  }

  // ---------------------------------------------------------------- team

  function renderTeam(s) {
    const agents = list(s.agents).map(rec);
    const supervisor = agents.find((a) => a.lane === 'supervisor') || null;
    const others = agents.filter((a) => a.lane !== 'supervisor');
    const planned = others.filter((a) => a.lane === 'planned');
    return [
      supervisorCard(s, supervisor),
      h('h2', { class: 'section-title' }, 'Today’s pipeline'),
      stageStrip(list(s.pipeline).map(rec)),
      h('p', { class: 'oversight' }, h('span', null, icon('shield'), 'The supervisor checks every lane below')),
      laneBoard(s, others.filter((a) => a.lane !== 'planned')),
      planned.length ? plannedSection(planned) : null,
    ];
  }

  function supervisorCard(s, sup) {
    const research = list(s.research).map(rec);
    const qualified = research.filter((r) => rec(r.gate).status === 'qualified');
    const real = qualified.filter((r) => !r.control).length;
    const checks = list(s.checks).map(rec);
    const fails = checks.filter((c) => normCheck(c.status) === 'fail').length;
    const warns = checks.filter((c) => normCheck(c.status) === 'warn').length;
    const pending = list(rec(s.approvals).pending).length;
    const meta = rec(s.meta);
    const a = sup || { name: 'Supervisor', role: 'Checks every stage, decides which agents qualify. Never trades.' };
    return h('article', { class: 'card sup', 'aria-labelledby': 'sup-title' },
      h('div', { class: 'sup-head' },
        h('div', { class: 'sup-title' },
          h('span', { class: 'agent-icon' }, icon('shield')),
          h('div', null, h('h2', { id: 'sup-title' }, str(a.name) || 'Supervisor'), a.role ? h('p', { class: 'sup-role' }, str(a.role)) : null)),
        h('div', { class: 'chips' }, kindChip(a.kind), sup ? statusChip(a.status) : null)),
      a.summary ? h('p', { class: 'sup-summary' }, str(a.summary)) : null,
      h('dl', { class: 'kpis' },
        kpi('Qualified (passed every check)', `${qualified.length} of ${research.length}`,
          qualified.length && !real ? 'self-test only' : `${real} real rule${real === 1 ? '' : 's'}`),
        kpi('Eligible for money', meta.eligible_for_money === true ? 'Yes' : 'No', meta.eligible_note),
        kpi('Checks to look at', `${fails} fail · ${warns} warn`, `${checks.length} checks in total`),
        kpi('Waiting for your YES', pending === 1 ? '1 change' : `${pending} changes`, 'Nothing changes without it')));
  }

  function kpi(label, value, sub) {
    return h('div', { class: 'kpi' }, h('dt', null, label), h('dd', null, value, sub ? h('small', null, str(sub)) : null));
  }

  function stageStrip(stages) {
    if (!stages.length) return emptyBox('No pipeline stages reported yet.');
    const strip = h('ol', { class: 'stages' }, stages.map((st, i) => h('li', { class: 'stage' },
      h('span', { class: 'stage-num', 'aria-hidden': 'true' }, String(i + 1)),
      h('div', { class: 'stage-body' },
        h('span', { class: 'stage-name' }, str(st.name) || titleCase(st.id)),
        h('span', null, statusChip(st.status)),
        st.summary ? h('p', null, str(st.summary)) : null))));
    strip.style.setProperty('--n', String(stages.length));
    return strip;
  }

  function laneBoard(s, agents) {
    const bar = fmtPct(accuracyBar());
    const known = new Set(LANES.map((l) => l.id));
    const extras = [...new Set(agents.map((a) => str(a.lane)).filter((id) => id && !known.has(id)))]
      .map((id) => ({ id, name: titleCase(id), icon: 'idle', desc: () => '' }));
    const research = new Map(list(s.research).map(rec).map((r) => [r.rule_id, r]));
    return h('div', { class: 'lanes' }, LANES.concat(extras).map((lane, i) => {
      const members = agents.filter((a) => str(a.lane) === lane.id);
      const headId = 'lane-h-' + i;
      const desc = lane.desc(bar);
      return h('section', { class: known.has(lane.id) ? 'lane lane-' + lane.id : 'lane', 'aria-labelledby': headId },
        h('header', { class: 'lane-head' },
          h('h3', { class: 'lane-title', id: headId }, icon(lane.icon), lane.name,
            h('span', { class: 'n' }, String(members.length), h('span', { class: 'sr-only' }, members.length === 1 ? ' agent' : ' agents'))),
          desc ? h('p', { class: 'lane-desc' }, desc) : null),
        h('div', { class: 'lane-cards' }, members.length
          ? members.map((a) => (a.rule_id ? researchCard(a, rec(research.get(a.rule_id))) : agentCard(a)))
          : h('p', { class: 'lane-empty' }, 'No agent here yet.')));
    }));
  }

  function agentCard(a) {
    const planned = a.status === 'planned';
    return h('article', { class: planned ? 'agent is-planned' : 'agent' },
      h('div', { class: 'agent-top' }, h('h4', { class: 'agent-name' }, str(a.name) || str(a.id)), kindChip(a.kind)),
      h('div', { class: 'chips' }, statusChip(a.status)),
      a.role ? h('p', { class: 'agent-role' }, str(a.role)) : null,
      a.summary ? h('p', { class: 'agent-summary' }, str(a.summary)) : null);
  }

  function researchCard(a, r) {
    const gate = a.gate_status || rec(r.gate).status;
    const href = '#agents/' + encodeURIComponent(str(a.rule_id));
    return h('article', { class: 'agent research' },
      h('h4', { class: 'agent-name' }, h('a', { class: 'agent-link', href }, str(a.name) || str(a.rule_id))),
      h('div', { class: 'chips' }, a.control ? controlChip() : null, gateChip(gate)),
      accuracyMeter(num(a.accuracy), gate, {}),
      a.summary ? h('p', { class: 'agent-summary' }, str(a.summary)) : null);
  }

  function accuracyMeter(value, gate, opts) {
    const bar = accuracyBar();
    const untrusted = gate === 'blocked';
    const label = 'Wins on never-seen months';
    const valueText = value == null ? 'not measured' : fmtWin(value) + (untrusted ? ' (not trusted)' : '');
    const box = h('div', { class: 'acc' + (untrusted ? ' untrusted' : '') + (opts.large ? ' lg' : '') });
    if (!opts.large) {
      box.append(h('p', { class: 'acc-line' }, h('strong', null, value == null ? 'Not measured' : fmtWin(value)), ' wins on never-seen months',
        untrusted ? h('span', { class: 'acc-flag' }, ' — not trusted') : null));
    }
    const track = h('div', { class: 'acc-bar', role: 'img', 'aria-label': `${label}: ${valueText}. The bar is ${fmtPct(bar)}.` });
    if (value != null) track.append(setWidth(h('span', { class: 'acc-fill' }), value));
    const mark = h('span', { class: 'acc-mark' });
    mark.style.left = clamp(bar, 0, 1) * 100 + '%';
    track.append(mark);
    box.append(track);
    const [lo, hi] = opts.ci || [];
    if (lo != null && hi != null) {
      const seg = setWidth(h('span'), hi - lo);
      seg.style.left = clamp(lo, 0, 1) * 100 + '%';
      box.append(h('div', { class: 'acc-ci', 'aria-hidden': 'true', title: 'Likely range (95%)' }, seg));
    }
    const tick = h('span', null, fmtPct(bar) + ' bar');
    tick.style.left = clamp(bar, 0, 1) * 100 + '%';
    box.append(h('div', { class: 'acc-scale', 'aria-hidden': 'true' }, tick));
    return box;
  }

  function plannedSection(agents) {
    return h('section', { class: 'planned-section', 'aria-labelledby': 'planned-h' },
      h('h2', { class: 'section-title', id: 'planned-h' }, 'Planned — not built yet'),
      h('div', { class: 'planned-cards' }, agents.map(agentCard)));
  }

  // ---------------------------------------------------------------- agents

  function renderAgents(s) {
    const research = list(s.research).map(rec);
    const summaries = new Map(list(s.agents).map(rec).filter((a) => a.rule_id).map((a) => [a.rule_id, a.summary]));
    const bar = fmtPct(accuracyBar());
    ui.agentNodes = new Map();
    return [
      panelHead('Research agents', `Each agent tests one fixed rule. The headline numbers come from months the rule never saw while it was built; ${bar} wins there is the bar.`),
      glossary(bar),
      research.length
        ? h('div', { class: 'agent-list' }, research.map((r) => researchRow(r, summaries.get(r.rule_id))))
        : emptyBox('No research agents have run yet.'),
    ];
  }

  function glossary(bar) {
    const terms = [
      ['Wins on never-seen months', `Share of trades that made money in the months kept hidden while the rule was built. Break-evens don’t count. The bar is ${bar}.`],
      ['Likely range', 'With few trades the true win rate is uncertain. The range shows where it probably is (95% Wilson interval).'],
      ['Hit full stop', 'Share of trades that lost the full amount risked. A high win rate with many full stops can still lose money.'],
      ['Profit per trade (R)', 'Average result per trade after spread, commission and slippage. 1R = the amount risked on a trade.'],
      ['Better than random?', 'The same trades were re-run 1,000 times with random entries and the same stop, target and costs. p is the share of random runs that did as well. Yes means p ≤ 0.05.'],
      ['Last 3 months', 'A second check on the most recent months, so a rule that stopped working is caught.'],
    ];
    return h('details', { class: 'glossary' }, h('summary', null, 'What do these words mean?'),
      h('dl', null, terms.map(([term, text]) => h('div', null, h('dt', null, term), h('dd', null, text)))));
  }

  function slug(id) {
    return str(id).replace(/[^a-zA-Z0-9_-]/g, '-');
  }

  function researchRow(r, summary) {
    const id = str(r.rule_id);
    const key = 'ra-' + slug(id);
    const gate = rec(r.gate);
    const windows = rec(r.windows);
    const meta = [list(r.symbols).join(' · '), str(r.timeframe), num(r.signals) != null ? fmtInt(r.signals) + ' signals' : null].filter(Boolean).join(' · ');
    const lead = summary || niceMinus(list(gate.reasons)[0] || '');
    const title = h('h3', { id: key + '-title', tabindex: '-1' }, str(r.name) || id);
    const toggle = h('button', { type: 'button', class: 'btn btn-ghost btn-sm expand', id: key + '-toggle', 'aria-expanded': 'false', 'aria-controls': key + '-details' },
      h('span', null, 'Show details'), icon('chevron'));
    const details = h('div', { class: 'ra-details', id: key + '-details', hidden: true });
    const card = h('article', { class: 'card ra', 'aria-labelledby': key + '-title' },
      h('div', { class: 'ra-head' },
        h('div', { class: 'ra-title' }, title, h('div', { class: 'chips' }, r.control ? controlChip() : null, gateChip(gate.status), stageChip(r.stage))),
        meta ? h('p', { class: 'ra-meta' }, meta) : null),
      lead ? h('p', { class: 'ra-summary' }, str(lead)) : null,
      trustAlert(gate.status),
      statsGrid(rec(windows.holdout), rec(windows.recent), gate),
      h('div', { class: 'ra-actions' }, toggle),
      details);
    toggle.addEventListener('click', () => setExpanded(id, toggle.getAttribute('aria-expanded') !== 'true', false));
    ui.agentNodes.set(id, { card, toggle, details, title, r });
    if (ui.expanded.has(id)) openDetails(ui.agentNodes.get(id));
    return card;
  }

  function openDetails(node) {
    node.toggle.setAttribute('aria-expanded', 'true');
    node.toggle.firstChild.textContent = 'Hide details';
    if (!node.details.childElementCount) append(node.details, agentDetails(node.r));
    node.details.hidden = false;
  }

  function setExpanded(id, open, scroll) {
    const node = ui.agentNodes.get(id);
    if (!node) return;
    if (open) {
      ui.expanded.add(id);
      openDetails(node);
    } else {
      ui.expanded.delete(id);
      node.toggle.setAttribute('aria-expanded', 'false');
      node.toggle.firstChild.textContent = 'Show details';
      node.details.hidden = true;
    }
    if (scroll) {
      node.card.scrollIntoView({ block: 'start' });
      node.title.focus({ preventScroll: true });
    }
  }

  function trustAlert(status) {
    if (status === 'blocked') return h('p', { class: 'ra-alert blocked' }, icon('stop'), 'These numbers are not real: the rule used future prices. The supervisor blocked it.');
    if (status === 'insufficient') return h('p', { class: 'ra-alert insufficient' }, icon('clock'), 'Too few trades to judge. Treat these numbers as noise for now.');
    return null;
  }

  function randomVerdict(gate, p) {
    const check = list(gate.checks).map(rec).find((c) => /^beats random entries \(never-seen/i.test(str(c.name)));
    if (check && typeof check.passed === 'boolean') return check.passed;
    return p == null ? null : p <= 0.05;
  }

  function statsGrid(hold, recent, gate) {
    const [lo, hi] = ciOf(hold);
    const p = num(rec(hold.random).p_value);
    const beats = randomVerdict(gate, p);
    return h('dl', { class: 'stats' },
      h('div', { class: 'stat stat-main' },
        h('dt', null, 'Wins on never-seen months'),
        h('dd', null,
          h('div', { class: 'stat-line' }, h('span', null, fmtWin(hold.win_rate)),
            lo != null && hi != null ? h('small', { title: 'Wilson 95% interval' }, `likely ${fmtPct(lo)}–${fmtPct(hi)}`) : null),
          accuracyMeter(num(hold.win_rate), gate.status, { large: true, ci: [lo, hi] }))),
      stat('Wins, last 3 months', fmtWin(recent.win_rate), `${fmtInt(recent.trades)} trades`),
      stat('Hit full stop', fmtPct(hold.full_stop_rate), 'never-seen months'),
      stat('Profit per trade (R)', fmtR(hold.expectancy_r), 'after costs'),
      stat('Trades', fmtInt(hold.trades), 'never-seen months'),
      stat('Better than random?', beats == null ? DASH : beats ? 'Yes' : 'No', fmtP(p)));
  }

  function stat(label, value, sub) {
    return h('div', { class: 'stat' }, h('dt', null, label), h('dd', null, value, sub ? h('small', null, sub) : null));
  }

  function agentDetails(r) {
    const id = str(r.rule_id);
    const windows = rec(r.windows);
    const hold = rec(windows.holdout);
    const recent = rec(windows.recent);
    const dev = rec(windows.development);
    const gate = rec(r.gate);
    return [
      h('p', { class: 'windows-line' }, [['Never-seen months', hold], ['Last 3 months', recent], ['Built on', dev]]
        .map(([label, w]) => h('span', null, `${label}: ${fmtRange(w)}`))),
      h('div', { class: 'chart-pair' }, equityFigure(hold, recent), randomFigure(id, hold, recent)),
      h('div', { class: 'detail-grid' },
        detail('Gate checks', [
          gate.status === 'blocked' ? h('p', { class: 'ra-alert blocked small' }, icon('stop'), 'Blocked: the problem under “Why” overrides every check below.') : null,
          gateChecks(list(gate.checks)),
        ]),
        detail('Why', reasonsList(list(gate.reasons))),
        detail('Path to money', pathToMoney(r)),
        detail('Test plan', planBlock(r, dev)),
        detail('Risk at minimum lot', minLotNote(rec(r.risk_at_min_lot))),
        detail('About this rule', [
          r.description ? h('p', null, str(r.description)) : null,
          r.demo_note ? h('p', null, h('strong', null, 'Why this demo exists: '), str(r.demo_note)) : null,
        ])),
    ];
  }

  function detail(title, body) {
    return h('section', { class: 'detail' }, h('h4', null, title), body);
  }

  function equityFigure(hold, recent) {
    const holdEq = numbers(hold.equity_r);
    const recentEq = numbers(recent.equity_r);
    const base = holdEq.length ? holdEq[holdEq.length - 1] : 0;
    const pts = [{ i: 0, v: 0, w: null }];
    holdEq.forEach((v, k) => pts.push({ i: k + 1, v, w: 'hold' }));
    recentEq.forEach((v, k) => pts.push({ i: holdEq.length + k + 1, v: base + v, w: 'recent' }));
    const hasData = pts.length > 1;
    return h('figure', { class: 'fig' },
      h('div', { class: 'fig-head' }, h('div', null,
        h('h4', null, 'Profit over time'),
        h('p', null, 'Total R after each trade: never-seen months, then the last 3 months.'))),
      hasData ? chartBox((w) => drawEquity(w, pts, holdEq.length, recentEq.length)) : chartEmpty('No trades in these months yet.'),
      hasData ? h('p', { class: 'fig-note' }, equitySentence(pts)) : null,
      hasData ? tableView(['Trade', 'Months', 'Total'], pts.slice(1).map((p) => [String(p.i), p.w === 'hold' ? 'Never-seen' : 'Last 3 months', fmtR(p.v)])) : null);
  }

  function equitySentence(pts) {
    let peak = 0;
    let dip = 0;
    for (const p of pts) {
      peak = Math.max(peak, p.v);
      dip = Math.max(dip, peak - p.v);
    }
    const last = pts[pts.length - 1];
    return `Ends at ${fmtR(last.v, 1)} after ${fmtInt(last.i)} trades. Deepest drop from a high: ${fmtR(-dip, 1)}.`;
  }

  function randomFigure(id, hold, recent) {
    const body = h('div', { class: 'fig-body' });
    const fill = (key) => body.replaceChildren(...histogramBody(key === 'recent' ? recent : hold));
    const current = ui.histWindow[id] === 'recent' ? 'recent' : 'holdout';
    const buttons = [['holdout', 'Never-seen'], ['recent', 'Last 3 months']].map(([key, label]) =>
      h('button', { type: 'button', 'aria-pressed': String(key === current), 'data-key': key }, label));
    buttons.forEach((btn) => btn.addEventListener('click', () => {
      ui.histWindow[id] = btn.dataset.key;
      buttons.forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
      fill(btn.dataset.key);
    }));
    fill(current);
    return h('figure', { class: 'fig' },
      h('div', { class: 'fig-head' },
        h('div', null, h('h4', null, 'This agent vs random entries'), h('p', null, 'Bars: random-entry runs with the same stop, target and costs.')),
        h('div', { class: 'seg', role: 'group', 'aria-label': 'Which months' }, buttons)),
      body);
  }

  function histogramBody(win) {
    const rb = rec(win.random);
    const hist = rec(rb.hist);
    const edges = numbers(hist.bin_edges);
    const counts = numbers(hist.counts);
    if (!counts.length || edges.length !== counts.length + 1) return [chartEmpty('No random comparison for these months.')];
    const obs = num(win.expectancy_r);
    const runs = num(rb.runs) ?? counts.reduce((a, b) => a + b, 0);
    return [
      chartBox((w) => drawHistogram(w, edges, counts, obs, runs)),
      h('p', { class: 'fig-note' }, randomSentence(rb, obs)),
      tableView(['Profit per trade', 'Random runs'], counts.map((c, i) => [`${fmtR(edges[i])} to ${fmtR(edges[i + 1])}`, fmtInt(c)])),
    ];
  }

  function randomSentence(rb, obs) {
    const p = num(rb.p_value);
    const parts = [`This agent: ${fmtR(obs)} per trade. Random entries averaged ${fmtR(rb.expectancy_mean)}.`];
    if (p != null) {
      parts.push(`${fmtShare(p)} of random runs did as well (${fmtP(p)}): ${p <= 0.05 ? 'better than random.' : 'no better than random.'}`);
    }
    return parts.join(' ');
  }

  function gateChecks(checks) {
    if (!checks.length) return h('p', { class: 'muted' }, 'No gate checks recorded.');
    return h('ul', { class: 'gate-checks' }, checks.map(rec).map((c) => {
      const ok = c.passed === true;
      const value = [c.value ? niceMinus(c.value) : null, c.required ? 'needs ' + lowerFirst(str(c.required)) : null].filter(Boolean).join(' · ');
      return h('li', { class: 'gate-check ' + (ok ? 'pass' : 'fail') },
        h('span', { class: 'mark' }, icon(ok ? 'check' : 'cross')),
        h('span', null, h('span', { class: 'sr-only' }, ok ? 'Passed: ' : 'Failed: '), str(c.name), value ? h('span', { class: 'val' }, value) : null));
    }));
  }

  function niceMinus(t) {
    return str(t).replace(/(^|[\s(])-(?=\d)/g, '$1' + MINUS);
  }

  function lowerFirst(t) {
    return /^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t;
  }

  function reasonsList(reasons) {
    if (!reasons.length) return h('p', { class: 'muted' }, 'No reasons recorded.');
    return h('ul', { class: 'reasons' }, reasons.map((text) => h('li', null, niceMinus(text))));
  }

  function pathToMoney(r) {
    const stage = str(r.stage);
    const index = STAGES.findIndex((st) => st.id === stage);
    const fwd = rec(r.forward);
    const range = `${fmtInt(fwd.target_min)}–${fmtInt(fwd.target_max)}`;
    return [
      h('ol', { class: 'stepper', 'aria-label': 'Stages from research to money' }, STAGES.map((st, i) => {
        const cls = i === index ? ' current' : stage === 'blocked' && i === 0 ? ' blocked' : '';
        return h('li', { class: 'step' + cls, 'aria-current': i === index ? 'step' : null },
          h('span', { class: 'n' }, String(i + 1)), stage === 'blocked' && i === 0 ? 'Research (blocked)' : st.label);
      })),
      r.stage_note ? h('p', null, str(r.stage_note)) : null,
      h('p', { class: 'small muted' }, `Forward test: ${fmtInt(fwd.trades)} of ${range} trades at minimum lot.` + (fwd.note ? ' ' + str(fwd.note) : '')),
    ];
  }

  function planBlock(r, dev) {
    const plan = rec(r.plan);
    const sha = str(plan.sha256);
    const params = Object.entries(rec(plan.params));
    const valid = sha && plan.valid !== false;
    return [
      h('dl', { class: 'kv' },
        h('dt', null, 'Plan'), h('dd', null, sha ? h('code', { class: 'hash', title: sha }, sha.slice(0, 12)) : 'none'),
        h('dt', null, 'Locked'), h('dd', null, fmtDateTime(plan.locked_at)),
        h('dt', null, 'Status'), h('dd', null, h('span', { class: 'fits ' + (valid ? 'yes' : 'no') }, icon(valid ? 'check' : 'cross'),
          valid ? 'Unchanged since lock' : sha ? 'Changed after lock' + (plan.reason ? ': ' + str(plan.reason) : '') : 'No locked plan')),
        params.length ? [h('dt', null, 'Settings'), h('dd', { class: 'params' }, params.map(([k, v]) => {
          const pair = `${k} = ${fmtValue(v)}`;
          return h('span', { title: pair }, pair);
        }))] : null),
      num(dev.trades) != null
        ? h('p', { class: 'small muted' }, `Development months (used to build the rule): ${fmtInt(dev.trades)} trades, ${fmtPct(dev.win_rate)} wins. Not used for the gate.`)
        : null,
    ];
  }

  function minLotNote(m) {
    if (!Object.keys(m).length) return h('p', { class: 'muted' }, 'Not calculated yet.');
    const risk = rec(ui.state.risk);
    const limit = num(rec(risk.limits).risk_per_trade_pct);
    const currency = str(rec(risk.account).currency) || 'USD';
    const fits = m.ok !== false;
    return [
      h('p', null, `Median stop ${fmtInt(m.median_stop_points)} points → risks ${fmtMoney(m.risk, currency)} (${fmtPts(m.risk_pct, 2)} of the account) at the minimum lot.`),
      h('p', null, h('span', { class: 'fits ' + (fits ? 'yes' : 'no') }, icon(fits ? 'check' : 'cross'),
        (fits ? 'Fits the per-trade limit' : 'Too big for the per-trade limit') + (limit != null ? ` (${fmtPts(limit)})` : ''))),
    ];
  }

  // ---------------------------------------------------------------- checks

  function renderChecks(s) {
    const checks = list(s.checks).map(rec).map((c) => Object.assign({}, c, { norm: normCheck(c.status) }));
    const counts = { all: checks.length, fail: 0, warn: 0, pass: 0, info: 0 };
    checks.forEach((c) => { counts[c.norm] += 1; });
    const box = h('div', { class: 'stack' });
    const draw = () => box.replaceChildren(...checkGroups(s, checks.filter((c) => ui.checkFilter === 'all' || c.norm === ui.checkFilter)));
    const options = [['all', 'All', null]].concat(Object.keys(CHECK_STATUS).map((k) => [k, titleCase(k), CHECK_STATUS[k]]));
    draw();
    return [
      panelHead('Supervisor checks', 'Every stage is checked before anything can move toward money. Problems are listed first.'),
      filterBar('Filter checks by status', options, counts, () => ui.checkFilter, (v) => { ui.checkFilter = v; draw(); }),
      box,
    ];
  }

  function checkGroups(s, checks) {
    if (!checks.length) return [emptyBox(ui.checkFilter === 'all' ? 'No checks have run yet.' : 'No checks with this status.')];
    const stageNames = new Map(list(s.pipeline).map(rec).map((p) => [p.id, str(p.name)]));
    const order = [...stageNames.keys()];
    const rank = (id) => (order.indexOf(id) === -1 ? order.length : order.indexOf(id));
    const stages = [...new Set(checks.map((c) => str(c.stage)))].sort((a, b) => rank(a) - rank(b));
    const names = agentNames(s);
    return stages.map((stage, i) => {
      const items = checks.filter((c) => str(c.stage) === stage).sort((a, b) => SEVERITY[a.norm] - SEVERITY[b.norm]);
      return h('section', { class: 'check-group', 'aria-labelledby': 'cg-' + i },
        h('h3', { id: 'cg-' + i }, stageNames.get(stage) || titleCase(stage) || 'Other', h('span', { class: 'n' }, String(items.length))),
        h('ul', { class: 'check-list' }, items.map((c) => h('li', { class: 'check' },
          chip(CHECK_STATUS[c.norm]),
          h('div', null,
            h('div', { class: 'check-name' }, str(c.name)),
            h('div', { class: 'check-meta' }, [str(c.subject), names.get(c.agent_id) || str(c.agent_id)].filter(Boolean).join(' · ')),
            c.detail ? h('p', { class: 'check-detail' }, str(c.detail)) : null)))));
    });
  }

  function filterBar(label, options, counts, get, set) {
    const buttons = options.map(([value, text, def]) => h('button', {
      type: 'button', class: 'filter', 'aria-pressed': String(get() === value), 'data-value': value,
    }, def ? icon(def.icon) : null, text, h('span', { class: 'n' }, String(counts[value] || 0))));
    buttons.forEach((btn) => btn.addEventListener('click', () => {
      set(btn.dataset.value);
      buttons.forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
    }));
    return h('div', { class: 'filters', role: 'group', 'aria-label': label }, buttons);
  }

  // ---------------------------------------------------------------- risk

  function renderRisk(s) {
    const risk = rec(s.risk);
    const head = panelHead('Portfolio risk', 'One limit for all agents together. Symbols that move together count as one bet, not several.');
    if (!Object.keys(risk).length) return [head, emptyBox('No risk data yet.')];
    const account = rec(risk.account);
    const limits = rec(risk.limits);
    const usage = rec(risk.usage);
    const currency = str(account.currency) || 'USD';
    const demo = rec(s.meta).data_mode !== 'mt5';
    return [
      head,
      h('div', { class: 'gauges' },
        gauge('Open risk', usage.open_risk_pct, limits.max_open_risk_pct, 'What you could lose if every open trade hit its stop.'),
        gauge('Margin in use', usage.margin_use_pct, limits.max_margin_use_pct, 'Share of the account held as margin by open trades.'),
        gauge('Loss today', usage.daily_loss_pct, limits.max_daily_loss_pct, 'Everything stops for the day at this limit.')),
      h('dl', { class: 'card facts' },
        fact('Risk per trade', fmtPts(limits.risk_per_trade_pct)),
        fact('Open positions', fmtInt(usage.open_positions)),
        fact('Max positions per group', fmtInt(limits.max_positions_per_group)),
        fact(demo ? 'Demo account size (placeholder)' : 'Account size used', fmtMoney(account.balance, currency)),
        fact('Leverage', num(account.leverage) != null ? '1:' + account.leverage : DASH)),
      groupsBlock(list(risk.groups).map(rec), limits),
      h('div', { class: 'risk-split' }, minLotTable(list(risk.min_lot).map(rec), currency, limits), correlationBlock(rec(risk.correlation))),
      bridgeBlock(rec(s.bridge)),
    ];
  }

  function gauge(label, used, limit, help) {
    const u = num(used);
    const l = num(limit);
    const ratio = u != null && l ? u / l : null;
    const level = ratio == null ? 'ok' : ratio >= 1 ? 'over' : ratio >= 0.7 ? 'warn' : 'ok';
    const words = ratio == null ? 'No limit set' : level === 'over' ? 'At the limit: new trades are blocked' : level === 'warn' ? 'Close to the limit' : 'Within the limit';
    const meter = h('div', { class: 'meter ' + level, role: 'img', 'aria-label': `${label}: ${fmtPts(u)} of a ${fmtPts(l)} limit. ${words}.` });
    if (ratio) meter.append(setWidth(h('span'), Math.max(ratio, 0.02)));
    return h('div', { class: 'card gauge' },
      h('div', { class: 'gauge-top' }, h('span', { class: 'gauge-label' }, label),
        h('span', { class: 'gauge-val' }, fmtPts(u), ' ', h('small', null, 'of ' + fmtPts(l) + ' limit'))),
      meter,
      h('p', { class: 'gauge-status ' + level }, icon(level === 'ok' ? 'check' : level === 'warn' ? 'warn' : 'stop'), words),
      h('p', { class: 'small muted' }, help));
  }

  function fact(label, value) {
    return h('div', null, h('dt', null, label), h('dd', null, value));
  }

  function groupsBlock(groups, limits) {
    const max = num(limits.max_positions_per_group);
    const intro = 'Symbols in a group move together, so they count as one bet' +
      (max != null ? `: at most ${fmtInt(max)} open position${max === 1 ? '' : 's'} per group.` : '.');
    return h('section', { class: 'card block', 'aria-labelledby': 'groups-h' },
      blockHead('Exposure by group', intro, 'groups-h'),
      groups.length ? h('div', { class: 'groups' }, groups.map(groupCard)) : h('p', { class: 'muted' }, 'No groups configured.'));
  }

  function groupCard(g) {
    const members = Object.entries(rec(g.members));
    const withGroup = members.filter(([, d]) => Number(d) > 0).map(([sym]) => sym);
    const against = members.filter(([, d]) => Number(d) < 0).map(([sym]) => sym);
    const used = num(g.risk_pct);
    const limit = num(g.limit_pct);
    const meter = h('div', { class: 'meter sm', role: 'img', 'aria-label': `Group risk ${fmtPts(used)} of ${fmtPts(limit)}` });
    if (used && limit) meter.append(setWidth(h('span'), Math.max(used / limit, 0.02)));
    const symList = (syms) => syms.map((sym) => h('span', { class: 'sym' }, sym));
    return h('article', { class: 'detail group' },
      h('div', { class: 'group-top' }, h('h4', null, str(g.name) || str(g.id)), h('span', { class: 'small muted' }, `${fmtInt(g.positions)} open`)),
      h('dl', { class: 'members' },
        withGroup.length ? [h('dt', null, 'Moves with the group'), h('dd', null, symList(withGroup))] : null,
        against.length ? [h('dt', null, 'Moves against it'), h('dd', null, symList(against))] : null),
      h('div', { class: 'risk-row' }, h('span', null, `Risk ${fmtPts(used)} of ${fmtPts(limit)} group limit`), meter));
  }

  function minLotTable(rows, currency, limits) {
    const intro = 'With the typical stop, one minimum lot must not risk more than ' + fmtPts(limits.risk_per_trade_pct) + ' of the account.';
    const headers = ['Symbol', 'Min lot', 'Typical stop', 'Risk at min lot', 'Margin at min lot', 'Fits?'];
    const cell = (label, content, cls) => h('td', { 'data-label': label, class: cls }, h('span', null, content));
    const body = rows.map((r) => {
      const fits = r.ok !== false;
      return h('tr', null,
        cell('Symbol', str(r.symbol), 'lead'),
        cell('Min lot', fmtLot(r.min_lot), 'num'),
        cell('Typical stop', fmtInt(r.median_stop_points) + ' pts', 'num'),
        cell('Risk at min lot', `${fmtMoney(r.risk_at_min_lot, currency)} (${fmtPts(r.risk_pct, 2)})`, 'num'),
        cell('Margin at min lot', fmtMoney(r.margin_at_min_lot, currency), 'num'),
        cell('Fits?', [h('span', { class: 'fits ' + (fits ? 'yes' : 'no') }, icon(fits ? 'check' : 'cross'), fits ? 'Fits' : 'Too big'),
          r.note ? h('span', { class: 'note' }, str(r.note)) : null]));
    });
    return h('section', { class: 'card block', 'aria-labelledby': 'minlot-h' },
      blockHead('Can this account trade the minimum lot?', intro, 'minlot-h'),
      rows.length
        ? h('div', { class: 'table-wrap' }, h('table', { class: 'tbl cards' },
          h('thead', null, h('tr', null, headers.map((t, i) => h('th', { scope: 'col', class: i > 0 && i < 5 ? 'num' : null }, t)))),
          h('tbody', null, body)))
        : h('p', { class: 'muted' }, 'No symbols yet.'));
  }

  function correlationBlock(c) {
    const syms = list(c.symbols).map(str);
    const matrix = list(c.matrix);
    const ok = syms.length > 1 && matrix.length === syms.length && matrix.every((row) => Array.isArray(row) && row.length === syms.length);
    const intro = 'From −1 (move opposite) to +1 (move together). Strongly linked symbols are one bet, not two.' + (c.window ? ' Window: ' + str(c.window) + '.' : '');
    return h('section', { class: 'card block', 'aria-labelledby': 'corr-h' },
      blockHead('How symbols move together', intro, 'corr-h'),
      ok ? chartBox((w) => drawHeatmap(w, syms, matrix)) : chartEmpty('No correlation data yet.'),
      ok ? h('div', { class: 'hm-legend', 'aria-hidden': 'true' }, h('div', { class: 'hm-ramp' }),
        h('div', { class: 'hm-ends' }, h('span', null, '−1 opposite'), h('span', null, '0 unrelated'), h('span', null, '+1 together'))) : null);
  }

  function bridgeBlock(b) {
    const signals = list(b.signals);
    return h('section', { class: 'card block', 'aria-labelledby': 'bridge-h' },
      blockHead('Bridge to the MT5 EA', 'The only way a signal leaves this system: a file that a fixed-rule EA on your PC or VPS reads. No order is ever placed from here.', 'bridge-h'),
      h('dl', { class: 'kv' },
        h('dt', null, 'File'), h('dd', null, h('code', null, str(b.file) || DASH)),
        h('dt', null, 'Signals written'), h('dd', null, fmtInt(b.written))),
      b.note ? h('p', null, str(b.note)) : null,
      signals.length ? h('ul', { class: 'bridge-list' }, signals.map(signalLine)) : null);
  }

  function signalLine(signal) {
    const o = rec(signal);
    const side = (v) => (Number(v) > 0 ? 'buy' : Number(v) < 0 ? 'sell' : str(v));
    const parts = ['rule_id', 'symbol', 'side', 'time', 'entry', 'stop', 'target', 'lots']
      .filter((k) => o[k] != null)
      .map((k) => `${k}: ${k === 'side' ? side(o[k]) : fmtValue(o[k])}`);
    return h('li', null, parts.length ? parts.join(' · ') : JSON.stringify(signal));
  }

  // ---------------------------------------------------------------- approvals

  function renderApprovals(s) {
    const approvals = rec(s.approvals);
    const pending = list(approvals.pending).map(rec);
    const history = list(approvals.history).map(rec);
    return [
      panelHead('Waiting for your YES', 'No lot, rule or settings change takes effect until you approve it here by typing YES.'),
      pending.length ? h('div', { class: 'agent-list' }, pending.map(approvalCard)) : emptyBox('Nothing is waiting for your YES.'),
      h('h3', { class: 'section-title' }, 'History'),
      history.length ? h('ul', { class: 'history' }, history.map(historyRow)) : emptyBox('No decisions yet.'),
    ];
  }

  function approvalCard(item) {
    return h('article', { class: 'card approval' },
      h('div', { class: 'approval-head' }, h('h3', null, str(item.summary) || str(item.id)), h('span', { class: 'chip outline' }, titleCase(item.kind) || 'Change')),
      h('p', { class: 'small muted' }, `${str(item.id)} · requested ${fmtDateTime(item.created_at)}`),
      diffList(list(item.diff)),
      h('div', { class: 'approval-actions' },
        lockAction(h('button', { type: 'button', class: 'btn btn-primary', id: 'approve-' + slug(item.id), onclick: () => approveChange(item) }, icon('check'), 'Approve…')),
        lockAction(h('button', { type: 'button', class: 'btn', id: 'reject-' + slug(item.id), onclick: () => rejectChange(item) }, icon('cross'), 'Reject…'))));
  }

  function diffList(lines) {
    if (!lines.length) return null;
    return h('ul', { class: 'diff', 'aria-label': 'What changes' }, lines.map((line) => {
      const m = /^(.*?):\s*(.*?)\s*(?:→|->)\s*(.*)$/.exec(str(line));
      if (!m) return h('li', null, h('code', null, str(line)));
      return h('li', null, h('code', null, m[1]),
        h('span', { class: 'old' }, h('span', { class: 'sr-only' }, 'from '), m[2]),
        h('span', { 'aria-hidden': 'true' }, '→'),
        h('span', { class: 'new' }, h('span', { class: 'sr-only' }, 'to '), m[3]));
    }));
  }

  function historyRow(item) {
    const decision = str(item.decision).toLowerCase();
    const approved = decision === 'approved' || decision === 'approve';
    const def = approved ? { label: 'Approved', icon: 'check', cls: 'approved' } : { label: titleCase(decision) || 'Rejected', icon: 'cross', cls: 'rejected' };
    return h('li', null, chip(def), h('span', { class: 'what' }, str(item.summary) || str(item.id)),
      h('span', { class: 'small muted' }, `${str(item.id)} · ${fmtDateTime(item.decided_at)}`));
  }

  // ---------------------------------------------------------------- report

  function renderReport(s) {
    const report = rec(s.report);
    const by = str(report.generated_by).toLowerCase();
    const byText = by === 'template'
      ? 'Written by the built-in template (AI offline).'
      : by === 'claude' || by === 'llm'
        ? 'Written with Claude. The AI only writes text; it cannot change rules, lots, settings or gate results.'
        : by ? 'Written by: ' + by : '';
    const title = str(report.title) || 'Daily report';
    return [
      panelHead(title, byText),
      report.markdown ? h('article', { class: 'card md' }, renderMarkdown(str(report.markdown), title)) : emptyBox('No report yet.'),
    ];
  }

  const MD = {
    blank: (l) => /^\s*$/.test(l),
    fence: (l) => /^\s*```/.test(l),
    heading: (l) => /^\s{0,3}#{1,6}\s+/.test(l),
    rule: (l) => /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(l),
    quote: (l) => /^\s{0,3}>/.test(l),
    item: (l) => /^\s*([-*+]|\d{1,9}[.)])\s+/.test(l),
    tableSep: (l) => l.includes('|') && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l),
  };

  function renderMarkdown(source, skipTitle) {
    const lines = source.replace(/\r\n?/g, '\n').split('\n');
    const first = lines.findIndex((l) => !MD.blank(l));
    if (first !== -1 && skipTitle) {
      const m = /^\s{0,3}#\s+(.*?)\s*#*\s*$/.exec(lines[first]);
      if (m && m[1].trim() === skipTitle.trim()) lines.splice(first, 1);
    }
    return mdBlocks(lines);
  }

  function mdBlocks(lines) {
    const out = [];
    let i = 0;
    const isTable = (k) => lines[k].includes('|') && k + 1 < lines.length && MD.tableSep(lines[k + 1]);
    while (i < lines.length) {
      const line = lines[i];
      if (MD.blank(line)) {
        i += 1;
      } else if (MD.fence(line)) {
        const code = [];
        i += 1;
        while (i < lines.length && !MD.fence(lines[i])) code.push(lines[i++]);
        i += 1;
        out.push(h('pre', null, h('code', null, code.join('\n'))));
      } else if (MD.heading(line)) {
        const m = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
        out.push(h('h' + Math.min(6, m[1].length + 2), null, mdInline(m[2])));
        i += 1;
      } else if (MD.rule(line)) {
        out.push(h('hr'));
        i += 1;
      } else if (isTable(i)) {
        const header = mdRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes('|') && !MD.blank(lines[i])) rows.push(mdRow(lines[i++]));
        out.push(h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, header.map((c) => h('th', { scope: 'col' }, mdInline(c))))),
          h('tbody', null, rows.map((row) => h('tr', null, header.map((_, k) => h('td', null, mdInline(row[k] || '')))))))));
      } else if (MD.quote(line)) {
        const inner = [];
        while (i < lines.length && MD.quote(lines[i])) inner.push(lines[i++].replace(/^\s{0,3}>\s?/, ''));
        out.push(h('blockquote', null, mdBlocks(inner)));
      } else if (MD.item(line)) {
        const ordered = /^\s*\d/.test(line);
        const items = [];
        while (i < lines.length && MD.item(lines[i]) && /^\s*\d/.test(lines[i]) === ordered) {
          let text = lines[i].replace(/^\s*([-*+]|\d{1,9}[.)])\s+/, '');
          i += 1;
          while (i < lines.length && !MD.blank(lines[i]) && !MD.item(lines[i]) && /^\s{2,}\S/.test(lines[i])) text += ' ' + lines[i++].trim();
          items.push(h('li', null, mdInline(text)));
        }
        const start = ordered ? parseInt(line, 10) : 1;
        out.push(h(ordered ? 'ol' : 'ul', start > 1 ? { start } : null, items));
      } else {
        const para = [line.trim()];
        i += 1;
        while (i < lines.length && !MD.blank(lines[i]) && !MD.fence(lines[i]) && !MD.heading(lines[i]) && !MD.quote(lines[i])
          && !MD.item(lines[i]) && !MD.rule(lines[i]) && !isTable(i)) para.push(lines[i++].trim());
        out.push(h('p', null, mdInline(para.join(' '))));
      }
    }
    return out;
  }

  function mdRow(line) {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|')) t = t.slice(0, -1);
    return t.split('|').map((c) => c.trim());
  }

  function mdInline(text) {
    const out = [];
    const re = /`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|\*([^*\s](?:[^*]*[^*\s])?)\*|(?<![\w])_([^_\s](?:[^_]*[^_\s])?)_(?![\w])|\[([^\]]+)\]\(([^)\s]+)\)/g;
    let last = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1] != null) out.push(h('code', null, m[1]));
      else if (m[2] != null || m[3] != null) out.push(h('strong', null, mdInline(m[2] ?? m[3])));
      else if (m[4] != null || m[5] != null) out.push(h('em', null, mdInline(m[4] ?? m[5])));
      else if (/^https?:\/\//i.test(m[7])) out.push(h('a', { href: m[7], rel: 'noopener noreferrer', target: '_blank' }, mdInline(m[6])));
      else out.push(...mdInline(m[6]));
      last = re.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  // ---------------------------------------------------------------- log

  function renderLog(s) {
    const time = (iso) => toDate(iso)?.getTime() ?? 0;
    const rows = list(s.log).map(rec).map((l, i) => Object.assign({}, l, { i, lvl: normLevel(l.level) }))
      .sort((a, b) => time(b.time) - time(a.time) || b.i - a.i);
    const days = new Set(rows.map((r) => fmtDate(r.time)));
    const names = agentNames(s);
    const counts = { all: rows.length, error: 0, warn: 0, info: 0, debug: 0 };
    rows.forEach((r) => { counts[r.lvl] += 1; });
    const options = [['all', 'All', null], ['error', 'Errors', LOG_LEVEL.error], ['warn', 'Warnings', LOG_LEVEL.warn], ['info', 'Info', LOG_LEVEL.info]];
    if (counts.debug) options.push(['debug', 'Debug', LOG_LEVEL.debug]);
    const box = h('div');
    const draw = () => {
      const shown = rows.filter((r) => ui.logFilter === 'all' || r.lvl === ui.logFilter);
      box.replaceChildren(shown.length ? h('ol', { class: 'log' }, shown.map((r) => h('li', { class: 'log-row' },
        h('time', { datetime: str(r.time), title: fmtDateTime(r.time) }, (days.size > 1 ? fmtDate(r.time, false) + ' ' : '') + fmtClock(r.time)),
        chip(LOG_LEVEL[r.lvl]),
        h('span', { class: 'log-agent' }, names.get(r.agent_id) || str(r.agent_id)),
        h('span', { class: 'log-msg' }, str(r.msg))))) : emptyBox(rows.length ? 'No log lines at this level.' : 'No log lines yet.'));
    };
    draw();
    return [
      panelHead('Log', 'What every agent did in the last run. Newest first.'),
      filterBar('Filter log by level', options, counts, () => ui.logFilter, (v) => { ui.logFilter = v; draw(); }),
      box,
    ];
  }

  // ---------------------------------------------------------------- charts

  function chartBox(draw) {
    const box = h('div', { class: 'chart' });
    let width = 0;
    const observer = new ResizeObserver((entries) => {
      const w = Math.floor(entries[entries.length - 1].contentRect.width);
      if (w > 0 && w !== width) {
        width = w;
        box.replaceChildren(...draw(w));
      }
    });
    observer.observe(box);
    ui.observers.push(observer);
    return box;
  }

  function tooltip() {
    const node = h('div', { class: 'tip', hidden: true });
    return {
      node,
      show(lines, x, y, maxWidth) {
        node.replaceChildren(...lines);
        node.hidden = false;
        const w = node.offsetWidth;
        let left = x + 14;
        if (left + w > maxWidth) left = x - 14 - w;
        node.style.left = Math.max(0, left) + 'px';
        node.style.top = Math.max(0, y) + 'px';
      },
      hide() {
        node.hidden = true;
      },
    };
  }

  function chartKeys(e, current, max, show, hide) {
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (step) {
      e.preventDefault();
      show(current < 0 ? (step > 0 ? 0 : max) : current + step);
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      show(e.key === 'Home' ? 0 : max);
    } else if (e.key === 'Escape') {
      hide();
    }
  }

  function niceTicks(lo, hi, count) {
    if (!(hi > lo)) {
      lo -= 1;
      hi += 1;
    }
    const raw = (hi - lo) / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / mag;
    const step = (f >= 7.5 ? 10 : f >= 3.5 ? 5 : f >= 1.5 ? 2 : 1) * mag;
    const start = Math.floor(lo / step) * step;
    const end = Math.ceil(hi / step) * step;
    const ticks = [];
    for (let k = 0; start + k * step <= end + step / 2; k += 1) ticks.push(Math.round((start + k * step) / step) * step);
    return { lo: start, hi: end, ticks };
  }

  const textWidth = (t, size = 11.5) => t.length * size * 0.58;

  function drawEquity(w, pts, nHold, nRecent) {
    const H = w < 480 ? 200 : 228;
    const m = { t: 26, r: 60, b: 28, l: 48 };
    const pw = Math.max(60, w - m.l - m.r);
    const ph = H - m.t - m.b;
    const N = pts.length - 1;
    const values = pts.map((p) => p.v);
    const yt = niceTicks(Math.min(0, ...values), Math.max(0, ...values), 4);
    const x = (i) => m.l + (i / N) * pw;
    const y = (v) => m.t + (1 - (v - yt.lo) / (yt.hi - yt.lo)) * ph;
    const last = pts[N];
    const svg = s('svg', {
      width: w, height: H, viewBox: `0 0 ${w} ${H}`, role: 'img', tabindex: '0',
      'aria-label': `Profit over time: ${fmtR(last.v, 1)} after ${N} trades. Use the arrow keys to read each trade.`,
    });
    if (nHold && nRecent) svg.append(s('rect', { class: 'c-region', x: r1(x(nHold)), y: m.t, width: r1(x(N) - x(nHold)), height: ph }));
    for (const t of yt.ticks) {
      svg.append(s('line', { class: Math.abs(t) < 1e-9 ? 'c-zero' : 'c-grid', x1: m.l, x2: m.l + pw, y1: r1(y(t)), y2: r1(y(t)) }));
      svg.append(s('text', { class: 'c-tick', x: m.l - 8, y: r1(y(t) + 4), 'text-anchor': 'end' }, fmtTickR(t)));
    }
    niceTicks(0, N, w < 480 ? 3 : 6).ticks.filter((t) => t >= 0 && t <= N && Number.isInteger(t))
      .forEach((t) => svg.append(s('text', { class: 'c-tick', x: r1(x(t)), y: m.t + ph + 18, 'text-anchor': 'middle' }, String(t))));
    if (nHold && nRecent) svg.append(s('line', { class: 'c-divider', x1: r1(x(nHold)), x2: r1(x(nHold)), y1: m.t, y2: m.t + ph }));
    regionLabels(svg, x, m, w, nHold, nRecent, N);
    svg.append(s('path', { class: 'c-line', d: pts.map((p, k) => `${k ? 'L' : 'M'}${r1(x(p.i))} ${r1(y(p.v))}`).join('') }));
    svg.append(s('circle', { class: 'c-dot', cx: r1(x(N)), cy: r1(y(last.v)), r: 4 }));
    svg.append(s('text', { class: 'c-end', x: r1(x(N) + 9), y: r1(y(last.v) + 4) }, fmtR(last.v, 1)));

    const cross = s('line', { class: 'c-cross', y1: m.t, y2: m.t + ph, visibility: 'hidden' });
    const dot = s('circle', { class: 'c-dot', r: 4.5, visibility: 'hidden' });
    const hit = s('rect', { class: 'c-hit', x: m.l - 6, y: 0, width: pw + 12, height: H });
    svg.append(cross, dot, hit);
    const tip = tooltip();
    let current = -1;
    const show = (k) => {
      current = clamp(k, 0, N);
      const p = pts[current];
      const px = r1(x(p.i));
      cross.setAttribute('x1', px);
      cross.setAttribute('x2', px);
      cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', px);
      dot.setAttribute('cy', r1(y(p.v)));
      dot.setAttribute('visibility', 'visible');
      const lines = [h('div', { class: 'tip-val' }, fmtR(p.v) + ' total')];
      if (p.i === 0) lines.push(h('div', { class: 'tip-lab' }, 'Start'));
      else {
        lines.push(h('div', { class: 'tip-lab' }, `Trade ${p.i} · ${p.w === 'hold' ? 'never-seen months' : 'last 3 months'}`));
        lines.push(h('div', { class: 'tip-lab' }, 'This trade: ' + fmtR(p.v - pts[current - 1].v)));
      }
      tip.show(lines, px, m.t, w);
    };
    const hide = () => {
      current = -1;
      cross.setAttribute('visibility', 'hidden');
      dot.setAttribute('visibility', 'hidden');
      tip.hide();
    };
    const fromPointer = (e) => {
      const box = svg.getBoundingClientRect();
      show(Math.round(((e.clientX - box.left - m.l) / pw) * N));
    };
    hit.addEventListener('pointermove', fromPointer);
    hit.addEventListener('pointerdown', fromPointer);
    hit.addEventListener('pointerleave', hide);
    svg.addEventListener('keydown', (e) => chartKeys(e, current, N, show, hide));
    svg.addEventListener('blur', hide);
    return [svg, tip.node];
  }

  function regionLabels(svg, x, m, w, nHold, nRecent, N) {
    const y = m.t - 10;
    let recentLeft = Infinity;
    if (nRecent) {
      const label = 'Last 3 months';
      const start = nHold ? x(nHold) + 6 : m.l + 4;
      const fitsStart = start + textWidth(label) <= w - 4;
      const anchorX = fitsStart ? start : w - 4;
      recentLeft = fitsStart ? start : w - 4 - textWidth(label);
      svg.append(s('text', { class: 'c-label', x: r1(anchorX), y, 'text-anchor': fitsStart ? 'start' : 'end' }, label));
    }
    if (nHold) {
      const room = recentLeft - (m.l + 4) - 10;
      const label = textWidth('Never-seen months') <= room ? 'Never-seen months' : textWidth('Never-seen') <= room ? 'Never-seen' : null;
      if (label) svg.append(s('text', { class: 'c-label', x: m.l + 4, y }, label));
    }
  }

  function topRounded(x, y, w, hgt, r) {
    const rr = Math.max(0, Math.min(r, w / 2, hgt));
    return `M${r1(x)} ${r1(y + hgt)}V${r1(y + rr)}Q${r1(x)} ${r1(y)} ${r1(x + rr)} ${r1(y)}H${r1(x + w - rr)}Q${r1(x + w)} ${r1(y)} ${r1(x + w)} ${r1(y + rr)}V${r1(y + hgt)}Z`;
  }

  function drawHistogram(w, edges, counts, obs, runs) {
    const H = w < 480 ? 190 : 210;
    const m = { t: 30, r: 14, b: 28, l: 14 };
    const pw = Math.max(60, w - m.l - m.r);
    const ph = H - m.t - m.b;
    let lo = Math.min(edges[0], 0);
    let hi = Math.max(edges[edges.length - 1], 0);
    if (obs != null) {
      lo = Math.min(lo, obs);
      hi = Math.max(hi, obs);
    }
    const pad = (hi - lo) * 0.06 || 0.05;
    lo -= pad;
    hi += pad;
    const x = (v) => m.l + ((v - lo) / (hi - lo)) * pw;
    const base = m.t + ph;
    const maxCount = Math.max(1, ...counts);
    const svg = s('svg', {
      width: w, height: H, viewBox: `0 0 ${w} ${H}`, role: 'img', tabindex: '0',
      'aria-label': `${fmtInt(runs)} random-entry runs. This agent: ${fmtR(obs)} per trade. Use the arrow keys to read each bar.`,
    });
    if (lo < 0 && hi > 0) svg.append(s('line', { class: 'c-grid', x1: r1(x(0)), x2: r1(x(0)), y1: m.t, y2: base }));
    niceTicks(lo, hi, w < 480 ? 4 : 6).ticks.filter((t) => t >= lo && t <= hi)
      .forEach((t) => svg.append(s('text', { class: 'c-tick', x: r1(x(t)), y: base + 18, 'text-anchor': 'middle' }, fmtTickR(t))));
    const bars = counts.map((c, i) => {
      const x0 = x(edges[i]);
      const x1 = x(edges[i + 1]);
      const bh = (c / maxCount) * ph;
      const bar = s('path', { class: 'c-bar', d: c > 0 ? topRounded(x0 + 1, base - bh, Math.max(1, x1 - x0 - 2), bh, 3) : '' });
      svg.append(bar);
      return { bar, x0, x1, c };
    });
    svg.append(s('line', { class: 'c-zero', x1: m.l, x2: m.l + pw, y1: base, y2: base }));
    if (obs != null) {
      const ox = r1(x(obs));
      const label = 'This agent ' + fmtR(obs);
      const half = textWidth(label, 12) / 2;
      const anchor = ox + half > w ? 'end' : ox - half < 0 ? 'start' : 'middle';
      svg.append(s('line', { class: 'c-marker', x1: ox, x2: ox, y1: m.t - 6, y2: base }));
      svg.append(s('text', { class: 'c-marker-label', x: ox, y: m.t - 12, 'text-anchor': anchor }, label));
    }
    const tip = tooltip();
    let current = -1;
    const show = (k) => {
      current = clamp(k, 0, counts.length - 1);
      bars.forEach((b, j) => b.bar.classList.toggle('on', j === current));
      const b = bars[current];
      tip.show([
        h('div', { class: 'tip-val' }, `${fmtInt(b.c)} of ${fmtInt(runs)} runs`),
        h('div', { class: 'tip-lab' }, `averaged ${fmtR(edges[current])} to ${fmtR(edges[current + 1])} per trade`),
      ], (b.x0 + b.x1) / 2, m.t, w);
    };
    const hide = () => {
      current = -1;
      bars.forEach((b) => b.bar.classList.remove('on'));
      tip.hide();
    };
    bars.forEach((b, j) => {
      const target = s('rect', { class: 'c-hit', x: r1(b.x0), y: m.t - 10, width: r1(Math.max(4, b.x1 - b.x0)), height: ph + 10 });
      target.addEventListener('pointerenter', () => show(j));
      target.addEventListener('pointerdown', () => show(j));
      svg.append(target);
    });
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('keydown', (e) => chartKeys(e, current, counts.length - 1, show, hide));
    svg.addEventListener('blur', hide);
    return [svg, tip.node];
  }

  function corrWords(v) {
    const a = Math.abs(v);
    const strength = a < 0.2 ? 'barely linked' : a < 0.5 ? 'somewhat linked' : a < 0.75 ? 'strongly linked' : 'very strongly linked';
    return a < 0.2 ? strength : `${strength}, move ${v > 0 ? 'together' : 'opposite'}`;
  }

  function drawHeatmap(w, syms, matrix) {
    const n = syms.length;
    const labelW = 66;
    const cell = clamp(Math.floor((w - labelW - 4) / n), 26, 64);
    const rotate = cell < 60;
    const headH = rotate ? 60 : 26;
    const width = Math.min(w, labelW + cell * n + (rotate ? 26 : 0));
    const height = headH + cell * n + 2;
    const fontSize = cell < 40 ? 10 : 11.5;
    const svg = s('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'How symbols move together. Each cell shows the correlation value.' });
    syms.forEach((sym, j) => {
      const cx = labelW + j * cell + cell / 2;
      svg.append(rotate
        ? s('text', { class: 'c-sym', transform: `translate(${r1(cx - 3)} ${headH - 6}) rotate(-45)` }, sym)
        : s('text', { class: 'c-sym', x: r1(cx), y: headH - 9, 'text-anchor': 'middle' }, sym));
    });
    const tip = tooltip();
    matrix.forEach((row, i) => {
      svg.append(s('text', { class: 'c-sym', x: labelW - 8, y: r1(headH + i * cell + cell / 2 + 4), 'text-anchor': 'end' }, syms[i]));
      row.forEach((raw, j) => {
        const v = num(raw);
        const x0 = labelW + j * cell;
        const y0 = headH + i * cell;
        const diag = i === j;
        const rect = s('rect', { class: diag ? 'c-cell diag' : 'c-cell', x: x0 + 1, y: y0 + 1, width: cell - 2, height: cell - 2, rx: 3 });
        if (!diag && v != null) {
          const pole = v >= 0 ? '--hm-pos' : '--hm-neg';
          rect.style.fill = `color-mix(in oklab, var(${pole}) ${Math.round(Math.min(1, Math.abs(v)) * 100)}%, var(--hm-mid))`;
          rect.append(s('title', null, `${syms[i]} and ${syms[j]}: ${fmtCorr(v)}`));
          rect.addEventListener('pointerenter', () => {
            rect.classList.add('on');
            tip.show([h('div', { class: 'tip-val' }, fmtCorr(v)), h('div', { class: 'tip-lab' }, `${syms[i]} and ${syms[j]}: ${corrWords(v)}`)], x0 + cell / 2, y0 + cell, width);
          });
          rect.addEventListener('pointerleave', () => {
            rect.classList.remove('on');
            tip.hide();
          });
        }
        svg.append(rect);
        svg.append(s('text', { class: 'c-cell-text', x: r1(x0 + cell / 2), y: r1(y0 + cell / 2 + fontSize * 0.36), 'text-anchor': 'middle', 'font-size': fontSize }, v == null ? DASH : fmtCorr(v)));
      });
    });
    return [svg, tip.node];
  }

  function tableView(headers, rows) {
    return h('details', { class: 'table-view' }, h('summary', null, 'Show the numbers'),
      h('div', { class: 'table-wrap' }, h('table', { class: 'tbl' },
        h('thead', null, h('tr', null, headers.map((t) => h('th', { scope: 'col' }, t)))),
        h('tbody', null, rows.map((row) => h('tr', null, row.map((c) => h('td', null, c))))))));
  }

  // ---------------------------------------------------------------- dialog + toasts

  const dialog = { node: null };

  function buildDialog() {
    const title = h('h2', { id: 'dlg-title' });
    const body = h('div', { class: 'dlg-body', id: 'dlg-body' });
    const input = h('input', { id: 'dlg-input', class: 'dlg-input', type: 'text', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', 'aria-describedby': 'dlg-hint' });
    const field = h('div', { class: 'dlg-field' }, h('label', { for: 'dlg-input' }, 'Type YES to confirm'), input,
      h('p', { class: 'dlg-hint', id: 'dlg-hint' }, 'Capital letters. This is your explicit approval.'));
    const error = h('p', { class: 'dlg-error', role: 'alert', hidden: true });
    const cancel = h('button', { type: 'button', class: 'btn' }, 'Cancel');
    const confirm = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Confirm');
    const form = h('form', { class: 'dlg-form', method: 'dialog' }, title, body, field, error, h('div', { class: 'dlg-actions' }, cancel, confirm));
    const node = h('dialog', { class: 'dlg', 'aria-labelledby': 'dlg-title', 'aria-describedby': 'dlg-body' }, form);
    Object.assign(dialog, { node, title, body, input, field, error, cancel, confirm, current: null, busy: false, opener: null });
    const sync = () => {
      const needsYes = dialog.current && dialog.current.requireYes;
      confirm.disabled = dialog.busy || Boolean(needsYes && input.value.trim() !== 'YES');
      cancel.disabled = dialog.busy;
    };
    dialog.sync = sync;
    input.addEventListener('input', sync);
    cancel.addEventListener('click', () => node.close());
    node.addEventListener('cancel', (e) => {
      if (dialog.busy) e.preventDefault();
    });
    node.addEventListener('close', () => {
      dialog.current = null;
      const opener = dialog.opener;
      const target = opener && opener.isConnected ? opener : (opener && opener.id && document.getElementById(opener.id)) || document.getElementById('tab-' + ui.tab);
      if (target) target.focus();
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const job = dialog.current;
      if (!job || confirm.disabled) return;
      dialog.busy = true;
      error.hidden = true;
      confirm.textContent = 'Working…';
      sync();
      try {
        await job.run(job.requireYes ? 'YES' : null);
        dialog.busy = false;
        node.close();
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
      } finally {
        dialog.busy = false;
        confirm.textContent = job.confirmLabel;
        sync();
      }
    });
    document.body.append(node);
  }

  function openDialog(job) {
    if (!dialog.node) buildDialog();
    dialog.current = job;
    dialog.opener = document.activeElement;
    dialog.title.textContent = job.title;
    dialog.body.replaceChildren(...job.body.filter(Boolean));
    dialog.field.hidden = !job.requireYes;
    dialog.input.value = '';
    dialog.error.hidden = true;
    dialog.confirm.textContent = job.confirmLabel;
    dialog.sync();
    dialog.node.showModal();
    (job.requireYes ? dialog.input : dialog.confirm).focus();
  }

  function toast(kind, message) {
    let host = document.querySelector('.toasts');
    if (!host) {
      host = h('div', { class: 'toasts', 'aria-live': 'polite' });
      document.body.append(host);
    }
    const close = h('button', { type: 'button', class: 'toast-x', 'aria-label': 'Dismiss' }, icon('cross'));
    const node = h('div', { class: 'toast ' + kind, role: kind === 'error' ? 'alert' : 'status' },
      icon(kind === 'error' ? 'warn' : kind === 'ok' ? 'check' : 'info'), h('p', null, message), close);
    close.addEventListener('click', () => node.remove());
    host.append(node);
    if (kind !== 'error') setTimeout(() => node.remove(), 6000);
  }

  // ---------------------------------------------------------------- boot

  function boot() {
    applyTheme(storedTheme());
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.skip-link')) return;
      e.preventDefault();
      const main = document.getElementById('main');
      if (main) {
        main.focus({ preventScroll: true });
        main.scrollIntoView();
      }
    });
    window.addEventListener('hashchange', () => applyRoute(true));
    const injected = window.__STATE__;
    if (injected && typeof injected === 'object') {
      ui.snapshot = true;
      try {
        setState(injected, true);
      } catch (err) {
        renderLoadError(err);
      }
    } else {
      loadState();
    }
  }

  boot();
})();
