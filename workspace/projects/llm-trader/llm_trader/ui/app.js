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
    { id: 'data', name: 'Data', icon: 'database', desc: () => 'Checks where prices come from, gaps, spikes and spreads.' },
    { id: 'research', name: 'Research', icon: 'flask', desc: () => 'Each rule agent tests one fixed textbook rule. Self-tests have their own panel below.' },
    { id: 'context', name: 'Context', icon: 'compass', desc: () => 'Reads the calendar and the market mood. Shadow only: affects nothing yet.' },
    { id: 'validation', name: 'Validation', icon: 'gauge', desc: (bar) => `Runs the ${bar} gate: never-seen months, costs, random entries.` },
    { id: 'risk', name: 'Risk', icon: 'scale', desc: () => 'One limit in % of equity for everything together.' },
    { id: 'monitor', name: 'Monitor', icon: 'eye', desc: () => 'Kill switch, loss stops, alerts and forward tests.' },
    { id: 'report', name: 'Report', icon: 'doc', desc: () => 'Writes the morning summary for you.' },
  ];

  const CHECK_STAGES = [
    { id: 'data', name: 'Data checks' },
    { id: 'research', name: 'Research' },
    { id: 'validation', name: 'Validation (80% gate)' },
    { id: 'risk', name: 'Portfolio risk' },
    { id: 'monitor', name: 'Monitor' },
    { id: 'approvals', name: 'Approvals (your YES)' },
    { id: 'bridge', name: 'Bridge to MT5' },
    { id: 'report', name: 'Report' },
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
    alert: { label: 'ALERT', icon: 'bell', cls: 'alert' },
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
    compass: [['circle', { cx: 8, cy: 8, r: 6.3 }], ['path', { d: 'M10.6 5.4L9 9 5.4 10.6 7 7z' }]],
    bell: [['path', { d: 'M4 11.2V7.4a4 4 0 0 1 8 0v3.8l1.2 1.3H2.8z' }], ['path', { d: 'M6.6 14.2a1.5 1.5 0 0 0 2.8 0' }]],
    pause: [['path', { d: 'M5.8 3.8v8.4M10.2 3.8v8.4' }]],
    calc: [['rect', { x: 3, y: 1.8, width: 10, height: 12.4, rx: 1.6 }], ['path', { d: 'M5.4 4.6h5.2M5.6 8h.1M8 8h.1M10.4 8h.1M5.6 10.8h.1M8 10.8h.1M10.4 10.8h.1' }]],
    up: [['path', { d: 'M3 11.5l3.6-3.6 2.4 2.4L13 6.3' }], ['path', { d: 'M9.8 6.3H13v3.2' }]],
    down: [['path', { d: 'M3 4.5l3.6 3.6 2.4-2.4L13 9.7' }], ['path', { d: 'M9.8 9.7H13V6.5' }]],
    flat: [['path', { d: 'M2.5 8h11' }], ['path', { d: 'M10.5 5l3 3-3 3' }]],
    list: [['path', { d: 'M6 4.5h7.5M6 8h7.5M6 11.5h7.5' }], ['circle', { cx: 3, cy: 4.5, r: 0.5 }], ['circle', { cx: 3, cy: 8, r: 0.5 }], ['circle', { cx: 3, cy: 11.5, r: 0.5 }]],
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
    calc: { target: 0.25, stop: 1, cost: 0.025 },
  };

  const TOAST_LIMIT = 2;

  const CALC_PRESETS = [
    { label: 'Tight target', target: 0.25, stop: 1, cost: 0.025 },
    { label: 'Even 1:1', target: 1, stop: 1, cost: 0.05 },
    { label: 'Half target', target: 0.5, stop: 1, cost: 0.03 },
  ];

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

  const chip = (def, label, extra) => h('span', { class: 'chip ' + def.cls + (extra ? ' ' + extra : '') }, icon(def.icon), label || def.label);
  const statusChip = (status) => chip(AGENT_STATUS[status] || AGENT_STATUS.idle);
  function gateChip(status, r) {
    const def = GATE[status] || NOT_TESTED;
    const stage = str(rec(r).stage);
    // A pass on demo or synthetic data never moves forward, so the badge says so instead of a bare QUALIFIED.
    if (status === 'qualified' && r && stage !== 'forward_test' && stage !== 'live_eligible') {
      return h('span', { class: 'chip ' + def.cls + ' chip-wrap', title: str(rec(r).stage_note) }, icon(def.icon), 'Qualified · not eligible');
    }
    return chip(def);
  }
  const controlChip = () => h('span', { class: 'chip control', title: 'A planted pattern that proves the gate can detect a real edge. Never traded.' }, icon('target'), 'CONTROL');

  function selfTestChip(expected) {
    return h('span', { class: 'chip control chip-wrap', title: 'A rule with a known right answer, run to prove the gate works. Never traded.' },
      icon('target'), expected ? 'Self-test: ' + str(expected) : 'Self-test');
  }

  const VERDICT = {
    true: { label: 'As expected', icon: 'check', cls: 'pass' },
    false: { label: 'Wrong result', icon: 'cross', cls: 'fail' },
    null: { label: 'Not run', icon: 'idle', cls: 'idle' },
  };
  const verdictOf = (ok) => VERDICT[ok === true ? 'true' : ok === false ? 'false' : 'null'];
  const isSelfTest = (r) => Boolean(r && (r.self_test === true || r.kind === 'self_test'));

  function kindChip(kind) {
    const def = KIND[kind];
    return def ? h('span', { class: 'chip outline' }, icon(def.icon), def.label) : null;
  }

  function stageChip(stage) {
    if (!stage) return null;
    const known = STAGES.find((st) => st.id === stage);
    if (stage === 'blocked') return null;
    return h('span', { class: 'chip outline chip-wrap' }, 'Stage: ' + (known ? known.label : titleCase(stage)));
  }

  const emptyBox = (message) => h('p', { class: 'empty' }, message);
  const chartEmpty = (message) => h('p', { class: 'chart-empty' }, message);

  function panelHead(title, intro) {
    return h('div', { class: 'panel-head' }, h('h2', null, title), intro ? h('p', null, intro) : null);
  }

  function blockHead(title, intro, id) {
    return h('div', { class: 'block-head' }, h('h3', { id }, title), intro ? h('p', null, intro) : null);
  }

  function groupHead(id, title, intro, count) {
    return h('div', { class: 'group-head' },
      h('h2', { id, tabindex: '-1' }, title, count != null ? h('span', { class: 'n' }, String(count)) : null),
      intro ? h('p', null, intro) : null);
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
  const trimZero = (text) => text.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  const fmtPts = (v, digits = 1) => (num(v) == null ? DASH : trimZero(v.toFixed(digits)) + '%');
  const fmtInt = (v) => (num(v) == null ? DASH : Math.round(v).toLocaleString('en-US'));
  const fmtLot = (v) => (num(v) == null ? DASH : v.toFixed(2));
  const fmtCorr = (v) => (v < 0 ? MINUS : '') + Math.abs(v).toFixed(2);

  function fmtWin(v) {
    return num(v) == null ? DASH : fmtPct(v, 1);
  }

  function fmtP(v) {
    if (num(v) == null) return DASH;
    if (v < 0.001) return 'p < 0.001';
    return 'p = ' + v.toFixed(3);
  }

  const plural = (n, word, many) => `${fmtInt(n)} ${n === 1 ? word : many || word + 's'}`;
  // Whole sentences up to about two lines, so a card says what the rule does without the full description.
  const firstSentence = (text, max = 180) => {
    const parts = str(text).trim().split(/(?<=[.!?])\s+(?=[A-Z])/);
    let out = parts[0];
    for (const next of parts.slice(1)) {
      if ((out + ' ' + next).length > max) break;
      out += ' ' + next;
    }
    return out;
  };
  const simulatedLink = (meta) => rec(meta).guardian_connected !== true;
  const KILL_SIMULATED = 'Agent output is blocked. Your MT5 EAs are NOT connected to v1 and keep trading: to stop them, press Algo Trading in MT5.';

  function fmtShare(p) {
    return p < 0.01 ? (p * 100).toFixed(1) + '%' : Math.round(p * 100) + '%';
  }

  function fmtTickR(t) {
    if (Math.abs(t) < 1e-9) return '0R';
    const digits = Number.isInteger(t) ? 0 : Number.isInteger(Math.round(t * 1e6) / 1e5) ? 1 : 2;
    return signed(t, digits) + 'R';
  }

  function fmtMoney(v, currency, whole = false) {
    if (num(v) == null) return DASH;
    const digits = whole && Number.isInteger(v) ? 0 : 2;
    try {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
    } catch {
      return v.toFixed(digits) + ' ' + str(currency);
    }
  }

  // Three significant digits, so a Holm threshold of 0.0125 is never shown as a looser 0.013.
  const fmtThr = (v) => (num(v) == null ? DASH : String(Number(v.toPrecision(3))));
  const fmtX = (v) => (num(v) == null ? DASH : v.toFixed(2).replace(/\.?0+$/, '') + '×');

  function pairOf(v) {
    if (Array.isArray(v)) return [num(v[0]), num(v[1])];
    if (v && typeof v === 'object') return [num(v.lo), num(v.hi)];
    return [null, null];
  }

  function fmtRange2(v) {
    const [lo, hi] = pairOf(v);
    return lo == null || hi == null ? DASH : `${fmtR(lo)} to ${fmtR(hi)}`;
  }

  const signCls = (v) => (num(v) == null || Math.abs(v) < 0.005 ? null : v > 0 ? 'pos' : 'neg');

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

  const ciOf = (w) => pairOf(w.win_rate_ci);

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
    const method = options.method || 'GET';
    const init = { method, headers: { Accept: 'application/json' } };
    // The server refuses actions without this header, so another web page cannot press the buttons for you.
    if (method !== 'GET') init.headers['X-Superagentic'] = '1';
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
    if (data && typeof data.refresh_error === 'string') {
      if (looksLikeState(data)) setState(data);
      else if (ui.state && data.kill_switch) {
        rec(ui.state.meta).kill_switch = data.kill_switch;
        render(false);
      }
      toast('warn', data.refresh_error);
      return false;
    }
    if (looksLikeState(data)) setState(data);
    else if (data && looksLikeState(data.state)) setState(data.state);
    else setState(await api('/api/state'));
    return true;
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
    const running = toast('info', 'Running the pipeline. This can take a minute…', true);
    try {
      if (await applyResult(await api('/api/run', { method: 'POST' }))) toast('ok', 'Run finished. You are looking at the new results.');
    } catch (err) {
      toast('error', 'The run failed: ' + err.message);
    } finally {
      running.remove();
      setBusy(false);
    }
  }

  async function killSwitchOn() {
    if (ui.snapshot || ui.busy) return;
    setBusy(true);
    try {
      if (await applyResult(await api('/api/killswitch', { method: 'POST', body: { on: true, confirm: null } }))) {
        toast('ok', simulatedLink(rec(ui.state).meta) ? 'Kill switch ON (simulated). ' + KILL_SIMULATED : 'Kill switch is ON. Everything is stopped.');
      }
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
        if (await applyResult(await api('/api/killswitch', { method: 'POST', body: { on: false, confirm } }))) toast('ok', 'Kill switch is OFF.');
      },
    });
  }

  function approveChange(item, names) {
    if (ui.snapshot || ui.busy) return;
    const baseline = str(item.kind).toLowerCase() === 'baseline';
    openDialog({
      title: 'Approve this change?',
      body: [h('p', null, h('strong', null, str(item.summary) || str(item.id))),
        baseline ? adoptingBlock(ui.state) : diffList(list(item.diff), names), h('p', null, 'It takes effect as soon as you confirm.')],
      requireYes: true,
      confirmLabel: 'Approve',
      run: async (confirm) => {
        if (await applyResult(await api('/api/approvals/' + encodeURIComponent(str(item.id)), { method: 'POST', body: { decision: 'approve', confirm } }))) {
          toast('ok', 'Change approved.');
        }
      },
    });
  }

  function rejectChange(item) {
    if (ui.snapshot || ui.busy) return;
    const baseline = str(item.kind).toLowerCase() === 'baseline';
    openDialog({
      title: 'Reject this change?',
      body: [h('p', null, h('strong', null, str(item.summary) || str(item.id))),
        h('p', null, baseline ? 'Nothing is approved, so safe mode stays on and the bridge stays closed.' : 'The approved version is put back where possible. The request moves to the history list.')],
      requireYes: false,
      confirmLabel: 'Reject',
      run: async () => {
        if (await applyResult(await api('/api/approvals/' + encodeURIComponent(str(item.id)), { method: 'POST', body: { decision: 'reject', confirm: null } }))) {
          toast('ok', 'Change rejected. Nothing was changed.');
        }
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
      app.replaceChildren(statusStrip(rec(s.meta)), renderHeader(s), renderNotices(s), h('div', { class: 'tabs-anchor' }), renderTabs(s), renderMain(s));
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
        h('div', { class: 'top-status' }, dataBadge(meta), llmBadge(meta), killSwitchPill(meta)),
        h('div', { class: 'top-actions' }, killSwitchButton(meta), runButton()),
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
    return h('span', { class: 'badge ' + (on ? 'ai-on' : 'ai-off'), title: str(meta.llm_note) }, icon(on ? 'spark' : 'plug'), on ? 'Claude on' : 'AI offline');
  }

  function bannerWords(meta) {
    const given = list(meta.banners).map(str).filter(Boolean);
    if (given.length) return given;
    const words = [meta.data_mode === 'mt5' ? 'NOT ELIGIBLE FOR MONEY' : 'SYNTHETIC DATA'];
    if (meta.llm_mode !== 'claude') words.push('AI OFFLINE');
    words.push('NO TRADING');
    if (rec(meta.kill_switch).on === true) words.push('KILL SWITCH ON');
    if (rec(meta.safe_mode).on === true) words.push('SAFE MODE');
    return words;
  }

  function statusStrip(meta) {
    const words = bannerWords(meta);
    const tone = (w) => (/KILL/i.test(w) ? ' kill' : /SAFE MODE/i.test(w) ? ' safe' : '');
    const items = [];
    words.forEach((w, i) => {
      if (i) items.push(h('span', { class: 'strip-dot', 'aria-hidden': 'true' }, '·'));
      items.push(h('span', { class: 'strip-item' + tone(w) }, w));
    });
    return h('div', { class: 'strip', role: 'note', 'aria-label': 'Status: ' + words.join(', ') },
      h('div', { class: 'wrap strip-row' }, icon('shield'), h('p', { 'aria-hidden': 'true' }, items)));
  }

  function killSwitchPill(meta) {
    const on = rec(meta.kill_switch).on === true;
    const simulated = simulatedLink(meta);
    return h('span', {
      class: 'ks-pill ' + (on ? 'on' : 'off'), id: 'ks-pill',
      title: simulated ? 'Simulated: it blocks agent output and writes kill.flag, which nothing in MT5 reads yet. Your EAs keep trading; stop them with MT5’s Algo Trading button.' : null,
    }, icon(on ? 'stop' : 'check'), on ? 'Kill switch ON' : 'Kill switch OFF',
    simulated ? h('span', { class: 'ks-sim' }, h('span', { class: 'sr-only' }, ', '), 'simulated') : null);
  }

  function killSwitchButton(meta) {
    const on = rec(meta.kill_switch).on === true;
    const btn = on
      ? h('button', { type: 'button', class: 'btn btn-sm', id: 'ks-btn', 'aria-describedby': 'ks-pill', onclick: killSwitchOff }, 'Turn kill switch off…')
      : h('button', { type: 'button', class: 'btn btn-sm btn-stop', id: 'ks-btn', 'aria-describedby': 'ks-pill', onclick: killSwitchOn }, icon('power'),
        simulatedLink(meta) ? 'Stop agents (simulated)' : 'Stop everything');
    return lockAction(btn);
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
      items.push(banner('kill', 'stop', simulatedLink(meta) ? 'Kill switch ON (simulated)' : 'Kill switch is on', [
        simulatedLink(meta) ? KILL_SIMULATED : 'Everything is stopped: no agent output reaches the bridge.',
        ks.reason ? 'Reason: ' + ks.reason : null,
        ks.changed_at ? 'Since ' + fmtDateTime(ks.changed_at) + '.' : null,
      ]));
    }
    const rows = [];
    if (safe.on === true) {
      const review = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => goTab('approvals', true) }, 'Review');
      rows.push(noticeRow('safe', 'warn', 'Safe mode', safe.reason ? str(safe.reason) : 'Settings or test plans are not approved yet. Nothing is sent to the bridge until you decide.', review));
    }
    if (meta.data_mode !== 'mt5') rows.push(noticeRow('demo', 'flask', 'Demo data', 'Synthetic prices: never real performance, never eligible for money.'));
    if (simulatedLink(meta)) rows.push(noticeRow('link', 'plug', 'Not connected to MT5', 'Nothing in v1 watches or stops your live account. Stop your EAs with MT5’s Algo Trading button.'));
    if (ui.snapshot) {
      const local = str(rec(rec(s.risk).account).source) === 'local';
      rows.push(noticeRow('static', 'info', 'Snapshot', 'Buttons are off in this file; to act, run python -m llm_trader serve.' +
        (local ? ' It contains your own balance: share it only with people you trust.' : '')));
    }
    if (rows.length) items.push(h('div', { class: 'notice-card', role: 'note' }, rows));
    return h('div', { class: 'wrap notices' }, items);
  }

  function noticeRow(kind, iconName, tag, text, action) {
    return h('div', { class: 'notice notice-' + kind }, icon(iconName),
      h('p', null, h('strong', { class: 'notice-tag' }, tag + '. '), text), action ? h('div', { class: 'notice-action' }, action) : null);
  }

  function banner(kind, iconName, tag, lines, action) {
    return h('div', { class: 'banner banner-' + kind }, icon(iconName),
      h('div', { class: 'banner-body' },
        h('span', { class: 'banner-tag' }, tag),
        lines.filter(Boolean).map((line) => h('p', null, str(line))),
        action ? h('div', { class: 'banner-action' }, action) : null));
  }

  function callout() {
    const bar = fmtPct(accuracyBar());
    const open = ui.calloutOpen ?? window.innerWidth >= 600;
    const box = h('details', { class: 'callout', open: open ? '' : null }, h('summary', null, icon('target'), h('strong', null, `What is the ${bar} bar?`)),
      h('p', null,
        `Your “${bar} accuracy” is measured, never claimed: the share of trades a rule agent won in months it never saw while it was built. It qualifies only if it wins at least ${bar} there, still makes money after costs (even at 1.5× costs), and beats random entries. Break-even trades (−0.1R to +0.1R) don’t count as wins; `,
        h('strong', null, '1R'), ' = the amount risked on one trade. Code agents are checked by tests instead; AI agents stay UNMEASURED until 30+ scored calls.'));
    box.addEventListener('toggle', () => { ui.calloutOpen = box.open; });
    return box;
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
    const demo = rec(s.meta).data_mode !== 'mt5' ? h('span', { class: 'tabs-demo', title: str(rec(s.meta).data_note) }, 'DEMO') : null;
    return h('div', { class: 'tabs-bar' }, h('div', { class: 'wrap tabs-row' }, tablist, demo));
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
    if (tab !== 'agents' || !sub) return;
    if (ui.agentNodes.has(sub)) {
      setExpanded(sub, true, true);
      return;
    }
    const section = document.getElementById('sec-' + slug(sub));
    if (section) {
      section.scrollIntoView({ block: 'start' });
      section.querySelector('h2')?.focus({ preventScroll: true });
    }
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
    const panel = document.getElementById('panel-' + id);
    // Bring the new panel into view when it starts below most of the screen, so a tap visibly does something.
    const below = panel && panel.getBoundingClientRect().top > window.innerHeight * 0.6;
    if (scrollUp && anchor && (window.scrollY > anchor.offsetTop || below)) window.scrollTo(0, anchor.offsetTop);
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
    const research = researchMap(s);
    const tests = list(s.self_tests).map(rec);
    const inPanel = (a) => tests.length > 0 && isSelfTest(research.get(a.rule_id));
    const supervisor = agents.find((a) => a.lane === 'supervisor') || null;
    const others = agents.filter((a) => a.lane !== 'supervisor');
    const planned = others.filter((a) => a.lane === 'planned');
    return [
      callout(),
      supervisorCard(s, supervisor),
      picksCard(s),
      h('h2', { class: 'section-title' }, 'Today’s pipeline'),
      stageStrip(list(s.pipeline).map(rec)),
      h('p', { class: 'oversight' }, h('span', null, icon('shield'), 'The supervisor checks every lane below')),
      laneBoard(s, others.filter((a) => a.lane !== 'planned' && !inPanel(a))),
      selfTestPanel(s, tests),
      planned.length ? plannedSection(planned) : null,
    ];
  }

  function researchMap(s) {
    return new Map(list(s.research).map(rec).map((r) => [r.rule_id, r]));
  }

  function supervisorCard(s, sup) {
    const research = list(s.research).map(rec);
    const rules = research.filter((r) => !isSelfTest(r) && !r.control);
    const passed = rules.filter((r) => rec(r.gate).status === 'qualified').length;
    const tests = list(s.self_tests).map(rec);
    const asExpected = tests.filter((t) => t.ok === true).length;
    const wrong = tests.filter((t) => t.ok === false).length;
    const checks = list(s.checks).map(rec);
    const fails = checks.filter((c) => normCheck(c.status) === 'fail').length;
    const warns = checks.filter((c) => normCheck(c.status) === 'warn').length;
    const pending = list(rec(s.approvals).pending).length;
    const meta = rec(s.meta);
    const bar = fmtPct(accuracyBar());
    const a = sup || { name: 'Supervisor', role: 'Checks every stage, decides which agents qualify. Never trades.' };
    const todo = pending
      ? h('a', { class: 'kpi-link', href: '#approvals', onclick: (e) => { e.preventDefault(); goTab('approvals', true); } },
        `${plural(pending, 'change')} ${pending === 1 ? 'waits' : 'wait'} for your YES`)
      : 'Nothing';
    return h('article', { class: 'card sup', 'aria-labelledby': 'sup-title' },
      h('div', { class: 'sup-head' },
        h('div', { class: 'sup-title' },
          h('span', { class: 'agent-icon' }, icon('shield')),
          h('div', null, h('h2', { id: 'sup-title' }, str(a.name) || 'Supervisor'), a.role ? h('p', { class: 'sup-role' }, str(a.role)) : null)),
        h('div', { class: 'chips' }, kindChip(a.kind), sup ? statusChip(a.status) : null)),
      a.summary ? h('p', { class: 'sup-summary' }, str(a.summary)) : null,
      h('dl', { class: 'kpis' },
        kpi('To do today', todo, pending ? 'Nothing changes without it' : 'Nothing waits for your YES', pending ? 'todo' : null),
        kpi('Rule agents past the gate', `${passed} of ${rules.length}`, `the ${bar} gate on never-seen months`),
        tests.length ? kpi('Self-tests as expected', `${asExpected} of ${tests.length}`,
          wrong ? 'fix the harness before trusting any result' : 'so the gate itself works') : null,
        kpi('Eligible for money', meta.eligible_for_money === true ? 'Yes' : 'No', meta.eligible_note),
        kpi('Checks to look at', `${fails} fail · ${warns} warn`, `${checks.length} checks in total; failed gates are results, not faults`)));
  }

  function forwardRange(s) {
    const fwd = list(s.research).map(rec).map((r) => rec(r.forward)).find((f) => num(f.target_min) != null && num(f.target_max) != null);
    return fwd ? `${fmtInt(fwd.target_min)}–${fmtInt(fwd.target_max)}` : '30–40';
  }

  function picksCard(s) {
    const picks = rec(s.picks_today);
    const items = list(picks.picks).map(rec);
    const bar = fmtPct(accuracyBar());
    return h('section', { class: 'card picks' + (items.length ? ' has-picks' : ''), 'aria-labelledby': 'picks-h' },
      h('span', { class: 'agent-icon' }, icon(items.length ? 'check' : 'target')),
      h('div', { class: 'picks-body' },
        h('h2', { id: 'picks-h' }, 'Qualified picks today: ', h('span', { class: 'picks-n' }, items.length ? fmtInt(items.length) : 'none')),
        picks.reason ? h('p', null, str(picks.reason)) : null,
        items.length ? h('ul', { class: 'picks-list' }, items.map(pickLine)) : null,
        h('p', { class: 'small muted' }, `A pick needs a rule agent that passed the ${bar} gate on your broker’s data, then a ${forwardRange(s)} trade forward test at minimum lot. “No pick today” is the usual answer.`)));
  }

  function pickLine(p) {
    const parts = ['name', 'rule_id', 'symbol', 'note'].filter((k) => p[k] != null && p[k] !== '').map((k) => fmtValue(p[k]));
    return h('li', null, parts.length ? parts.join(' · ') : fmtValue(p));
  }

  function kpi(label, value, sub, cls) {
    return h('div', { class: 'kpi' + (cls ? ' ' + cls : '') }, h('dt', null, label), h('dd', null, value, sub ? h('small', null, str(sub)) : null));
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
    const research = researchMap(s);
    const tagger = rec(rec(s.context).event_tagger);
    return h('div', { class: 'lanes' }, LANES.concat(extras).map((lane, i) => {
      const members = agents.filter((a) => str(a.lane) === lane.id);
      const headId = 'lane-h-' + i;
      const desc = lane.desc(bar);
      return h('section', { class: known.has(lane.id) ? 'lane lane-' + lane.id : 'lane', 'aria-labelledby': headId },
        h('header', { class: 'lane-head' },
          h('h3', { class: 'lane-title', id: headId }, icon(lane.icon), lane.name,
            h('span', { class: 'n' }, String(members.length), h('span', { class: 'sr-only' }, members.length === 1 ? ' agent' : ' agents'))),
          desc && members.length > 1 ? h('p', { class: 'lane-desc' }, desc) : null),
        h('div', { class: 'lane-cards' }, members.length
          ? members.map((a) => (a.rule_id ? researchCard(a, rec(research.get(a.rule_id))) : agentCard(a, a.id === 'event_tagger' ? tagger : null)))
          : h('p', { class: 'lane-empty' }, 'No agent here yet.')));
    }));
  }

  function agentCard(a, tagger) {
    const planned = a.status === 'planned';
    const t = rec(tagger);
    const facts = [];
    if (t.stage) facts.push(['Stage', titleCase(t.stage) + (t.measured ? ' · ' + str(t.measured) : '')]);
    if (t.model) facts.push(['Model', str(t.model)]);
    return h('article', { class: planned ? 'agent is-planned' : 'agent' },
      h('div', { class: 'agent-top' }, h('h4', { class: 'agent-name' }, str(a.name) || str(a.id)), kindChip(a.kind)),
      h('div', { class: 'chips' }, statusChip(a.status)),
      facts.length ? h('dl', { class: 'agent-facts' }, facts.map(([k, v]) => h('div', null, h('dt', null, k), h('dd', null, v)))) : null,
      a.role ? h('p', { class: 'agent-role' }, str(a.role)) : null,
      a.summary ? h('p', { class: 'agent-summary' }, h('span', { class: 'sr-only' }, 'Last output: '), niceMinus(a.summary)) : null,
      a.id === 'event_tagger' || a.lane === 'context' ? h('a', { class: 'agent-more', href: '#agents/context' }, 'See its answers') : null);
  }

  function researchCard(a, r) {
    const gate = a.gate_status || rec(r.gate).status;
    const href = '#agents/' + encodeURIComponent(str(a.rule_id));
    const hold = rec(rec(r.windows).holdout);
    return h('article', { class: 'agent research' },
      h('div', { class: 'agent-top' }, h('h4', { class: 'agent-name' }, h('a', { class: 'agent-link', href }, str(a.name) || str(a.rule_id))), kindChip(a.kind)),
      r.description ? h('p', { class: 'agent-what' }, firstSentence(r.description)) : null,
      h('div', { class: 'chips' }, isSelfTest(r) ? selfTestChip(r.expected) : a.control ? controlChip() : null, gateChip(gate, r), stageChip(r.stage)),
      accuracyMeter(num(a.accuracy), gate, { trades: num(hold.trades), hidden: r.results_hidden === true }),
      a.summary ? h('p', { class: 'agent-summary' }, niceMinus(a.summary)) : null);
  }

  function selfTestPanel(s, tests) {
    if (!tests.length) return null;
    const research = researchMap(s);
    const ok = tests.filter((t) => t.ok === true).length;
    const wrong = tests.filter((t) => t.ok === false).length;
    const summary = wrong ? chip(VERDICT.false, `${wrong} wrong`) : chip(ok === tests.length ? VERDICT.true : VERDICT.null, `${ok} of ${tests.length} as expected`);
    return h('section', { class: 'card st-panel', 'aria-labelledby': 'st-h' },
      h('div', { class: 'st-head' },
        h('div', null,
          h('h2', { id: 'st-h' }, 'Self-tests'),
          h('p', null, 'Each one has a known right answer. If any comes out wrong, no result on this page can be trusted. These test the system; they are not trading ideas and are never traded.')),
        summary),
      h('ul', { class: 'st-list' }, tests.map((t) => selfTestRow(t, research.get(t.id)))));
  }

  function selfTestRow(t, r) {
    const v = verdictOf(t.ok);
    const expected = str(t.expected);
    // Rule self-test names end in ": <expected>", which is already shown on its own line.
    const rawName = str(t.name) || str(t.id);
    const name = expected && rawName.endsWith(': ' + expected) ? rawName.slice(0, -(expected.length + 2)) : rawName;
    return h('li', { class: 'st-row ' + v.cls },
      h('span', { class: 'st-mark', title: v.label }, icon(v.icon)),
      h('div', { class: 'st-body' },
        h('h3', null, h('span', { class: 'sr-only' }, v.label + ': '), name),
        h('dl', { class: 'st-vs' },
          h('div', null, h('dt', null, 'Expected'), h('dd', null, expected || DASH)),
          h('div', null, h('dt', null, 'Got'), h('dd', null, str(t.actual) || DASH))),
        t.detail ? h('p', { class: 'st-detail' }, niceMinus(t.detail)) : null,
        r ? h('a', { class: 'agent-more', href: '#agents/' + encodeURIComponent(str(t.id)) }, 'See the numbers') : null));
  }

  function accuracyMeter(value, gate, opts) {
    const bar = accuracyBar();
    const few = gate === 'insufficient';
    const untrusted = gate === 'blocked' || few;
    const label = 'Wins on never-seen months';
    const flag = opts.hidden ? 'hidden until the plan is locked' : gate === 'blocked' ? 'not trusted'
      : few ? `only ${plural(opts.trades ?? 0, 'trade')}: too few to judge` : null;
    const valueText = value == null ? (opts.hidden ? 'hidden until the plan is locked' : 'not measured') : fmtWin(value) + (flag ? ` (${flag})` : '');
    const box = h('div', { class: 'acc' + (untrusted ? ' untrusted' : '') + (opts.large ? ' lg' : '') });
    if (!opts.large) {
      box.append(h('p', { class: 'acc-line' }, h('strong', null, value == null ? (opts.hidden ? 'Hidden' : 'Not measured') : fmtWin(value)), ' wins on never-seen months',
        flag ? h('span', { class: 'acc-flag' }, ` — ${flag}`) : null));
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
      h('ul', { class: 'planned-list' }, agents.map((a) => h('li', null,
        h('span', { class: 'planned-name' }, icon('planned'), str(a.name) || str(a.id)), kindChip(a.kind),
        a.role ? h('p', null, str(a.role)) : null))));
  }

  // ---------------------------------------------------------------- agents

  function renderAgents(s) {
    const research = list(s.research).map(rec);
    const summaries = new Map(list(s.agents).map(rec).filter((a) => a.rule_id).map((a) => [a.rule_id, a.summary]));
    const bar = fmtPct(accuracyBar());
    const rules = research.filter((r) => !isSelfTest(r));
    const tests = research.filter(isSelfTest);
    ui.agentNodes = new Map();
    const group = (id, title, intro, rows) => h('section', { class: 'agent-group', id: 'sec-' + id, 'aria-labelledby': 'grp-' + id },
      groupHead('grp-' + id, title, intro, rows.length),
      h('div', { class: 'agent-list' }, rows.map((r) => researchRow(r, summaries.get(r.rule_id)))));
    const meta = rec(s.meta);
    const tries = num(meta.trial_count);
    const prior = num(meta.prior_trials);
    return [
      callout(),
      h('div', { class: 'panel-head' },
        h('h2', null, 'Agents'),
        h('p', null, `Every agent’s scorecard. The headline numbers come from months the rule never saw while it was built; ${bar} wins there is the bar.`),
        tries != null ? h('p', { class: 'small' }, `${fmtInt(tries)} tries counted on these never-seen months` + (prior ? ` (${fmtInt(prior)} from earlier studies)` : ' (no earlier studies counted)') +
          '. Every extra try makes the random-entry test stricter (Holm correction).') : null),
      glossary(bar),
      research.length ? null : emptyBox('No research agents have run yet.'),
      rules.length ? group('rules', 'Rule agents', 'Each tests one fixed textbook rule (not your EAs). Only these could ever move toward money.', rules) : null,
      tests.length ? group('self-tests', 'Self-tests', 'Rules with a known right answer, run through the same gate to prove it works. Never traded.', tests) : null,
      gateSection(s),
      contextSection(s),
    ];
  }

  function glossary(bar) {
    const terms = [
      ['Wins on never-seen months', `Share of trades that won at least +0.1R in the months kept hidden while the rule was built. Break-evens (between −0.1R and +0.1R) don’t count. The bar is ${bar}.`],
      ['Likely range', 'With few trades the true number is uncertain. The range shows where it probably is (95% interval).'],
      ['Hit full stop', 'Share of trades that lost the whole amount risked (−0.9R or worse). A high win rate with many full stops can still lose money.'],
      ['Profit per trade (R), or expectancy', 'Average result per trade after spread, commission and slippage. 1R = the amount risked on a trade. The gate checks call it expectancy.'],
      ['Better than random?', 'The same trades were re-run 1,000 times on random days at the same time of day, with the same direction, stop, target and costs. p is the share of random runs that did as well. Each extra rule tried on the same months makes the bar for p stricter (Holm correction).'],
      ['Last 3 months', 'A second check on the most recent months, so a rule that stopped working is caught.'],
      ['Stress tests', 'A real edge should survive 1.5× costs, work for longs and shorts, and stay positive in at least 2 of 3 volatility regimes.'],
      ['Self-test', 'A rule with a known right answer. If it comes out wrong, the gate is broken.'],
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
    const lead = niceMinus(summary || list(gate.reasons)[0] || '');
    const title = h('h3', { id: key + '-title', tabindex: '-1' }, str(r.name) || id);
    const toggle = h('button', { type: 'button', class: 'btn btn-ghost btn-sm expand', id: key + '-toggle', 'aria-expanded': 'false', 'aria-controls': key + '-details' },
      h('span', null, 'Show details'), icon('chevron'));
    const details = h('div', { class: 'ra-details', id: key + '-details', hidden: true });
    const selfTest = isSelfTest(r);
    const card = h('article', { class: 'card ra', 'aria-labelledby': key + '-title' },
      h('div', { class: 'ra-head' },
        h('div', { class: 'ra-title' }, title, h('div', { class: 'chips' },
          selfTest ? selfTestChip(r.expected) : r.control ? controlChip() : null,
          gateChip(gate.status), stageChip(r.stage),
          selfTest && r.self_test_ok != null ? chip(verdictOf(r.self_test_ok)) : null)),
        meta ? h('p', { class: 'ra-meta' }, meta) : null),
      r.description ? h('p', { class: 'ra-what' }, firstSentence(r.description)) : null,
      lead ? h('p', { class: 'ra-summary' }, str(lead)) : null,
      trustAlert(gate, r.results_hidden === true),
      statsGrid(rec(windows.holdout), rec(windows.recent), gate, r.results_hidden === true),
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

  function trustAlert(gate, hidden) {
    const status = gate.status;
    if (hidden) return h('p', { class: 'ra-alert blocked' }, icon('stop'), 'Its never-seen results stay hidden until the test plan is locked properly (needs your YES), so nobody can look first and lock afterwards.');
    if (status === 'blocked') {
      const leak = list(gate.reasons).some((t) => /future-data leak/i.test(str(t)));
      return h('p', { class: 'ra-alert blocked' }, icon('stop'), leak
        ? 'These numbers are not real: the rule used future prices. The supervisor blocked it.'
        : 'Blocked by the supervisor (see Why). Treat these numbers as diagnosis only.');
    }
    if (status === 'insufficient') return h('p', { class: 'ra-alert insufficient' }, icon('clock'), 'Too few trades to judge. Treat these numbers as noise for now.');
    return null;
  }

  function findCheck(gate, re) {
    return list(gate.checks).map(rec).find((c) => re.test(str(c.name))) || null;
  }

  function randomVerdict(gate, p, threshold) {
    const check = findCheck(gate, /^beats random after correcting/i) || findCheck(gate, /^beats random entries \(never-seen/i);
    if (check && typeof check.passed === 'boolean') return check.passed;
    return p == null ? null : p <= (threshold ?? 0.05);
  }

  function holmReason(thr, tries) {
    if (thr == null) return '';
    const base = ` · needs ≤ ${fmtThr(thr)}`;
    return tries > 1 ? `${base}, stricter because ${fmtInt(tries)} tries were counted on these months (Holm correction)` : base;
  }

  function statsGrid(hold, recent, gate, hidden) {
    if (hidden) {
      return h('dl', { class: 'stats' }, h('div', { class: 'stat stat-main' }, h('dt', null, 'Wins on never-seen months'),
        h('dd', null, h('div', { class: 'stat-line' }, h('span', null, 'Hidden')), accuracyMeter(null, gate.status, { large: true, hidden: true }))));
    }
    const [lo, hi] = ciOf(hold);
    const extra = rec(hold.extra);
    const [elo, ehi] = pairOf(extra.expectancy_ci);
    const p = num(rec(hold.random).p_value);
    const thr = num(extra.holm_threshold);
    const beats = randomVerdict(gate, p, thr);
    const lost = num(hold.losses);
    return h('dl', { class: 'stats' },
      h('div', { class: 'stat stat-main' },
        h('dt', null, 'Wins on never-seen months'),
        h('dd', null,
          h('div', { class: 'stat-line' }, h('span', null, fmtWin(hold.win_rate)),
            lo != null && hi != null ? h('small', { title: 'Wilson 95% interval' }, `likely ${fmtPct(lo)}–${fmtPct(hi)}`) : null),
          accuracyMeter(num(hold.win_rate), gate.status, { large: true, ci: [lo, hi], trades: num(hold.trades) }))),
      stat('Better than random?', beats == null ? DASH : beats ? 'Yes' : 'No', fmtP(p) + holmReason(thr, num(extra.trial_count) ?? 0), 'stat-wide'),
      stat('Wins, last 3 months', fmtWin(recent.win_rate), plural(num(recent.trades) ?? 0, 'trade')),
      stat('Hit full stop', fmtPct(hold.full_stop_rate), num(hold.breakeven_rate) != null ? `break-even ${fmtPct(hold.breakeven_rate)}` : 'never-seen months'),
      stat('Profit per trade (R)', fmtR(hold.expectancy_r), elo != null && ehi != null ? `likely ${fmtR(elo)} to ${fmtR(ehi)}` : 'after costs'),
      stat('Trades', fmtInt(hold.trades), lost != null && num(hold.wins) != null ? `${fmtInt(hold.wins)} won · ${fmtInt(lost)} lost` : 'never-seen months'));
  }

  function stat(label, value, sub, cls) {
    return h('div', { class: 'stat' + (cls ? ' ' + cls : '') }, h('dt', null, label), h('dd', null, value, sub ? h('small', null, sub) : null));
  }

  function agentDetails(r) {
    const id = str(r.rule_id);
    const windows = rec(r.windows);
    const hold = rec(windows.holdout);
    const recent = rec(windows.recent);
    const dev = rec(windows.development);
    const gate = rec(r.gate);
    return [
      detail('About this rule', [
        r.description ? h('p', null, str(r.description)) : null,
        r.demo_note ? h('p', null, h('strong', null, 'Why this demo exists: '), str(r.demo_note)) : null,
      ]),
      h('p', { class: 'windows-line' }, [['Never-seen months', hold], ['Last 3 months', recent], ['Built on', dev]]
        .map(([label, w]) => h('span', null, `${label}: ${fmtRange(w)}`))),
      h('div', { class: 'chart-pair' }, equityFigure(hold, recent), randomFigure(id, hold, recent)),
      stressTable(hold, recent, gate),
      h('div', { class: 'detail-grid' },
        detail('Gate checks', [
          gate.status === 'blocked' ? h('p', { class: 'ra-alert blocked small' }, icon('stop'), 'Blocked: the problem under “Why” overrides every check below.') : null,
          gateChecks(list(gate.checks)),
        ]),
        detail('Why', reasonsList(list(gate.reasons))),
        detail('Path to money', pathToMoney(r)),
        detail('Test plan', planBlock(r, dev)),
        detail('Risk at minimum lot', isSelfTest(r) || r.control
          ? h('p', { class: 'muted' }, 'Self-test: never traded, so no lot applies.')
          : minLotNote(rec(r.risk_at_min_lot), list(r.symbols).map(str)))),
    ];
  }

  function detail(title, body) {
    return h('section', { class: 'detail' }, h('h4', null, title), body);
  }

  function stressTable(hold, recent, gate) {
    const hx = rec(hold.extra);
    const rx = rec(recent.extra);
    if (!Object.keys(hx).length && !Object.keys(rx).length) return null;
    const rCell = (v, sub) => ({ main: fmtR(v), cls: signCls(v), sub });
    const split = (x) => {
      const o = rec(x);
      return num(o.trades) ? rCell(o.expectancy_r, `${fmtInt(o.trades)} trades · ${fmtPct(o.win_rate)} wins`) : { main: DASH, sub: 'no trades' };
    };
    const tercile = (x, name) => {
      const t = list(x.terciles).map(rec).find((row) => row.name === name);
      if (!t || !num(t.trades)) return { main: DASH, sub: 'no trades' };
      return rCell(t.expectancy_r, `${fmtInt(t.trades)} trades` + (t.trades < 5 ? ' (too few to count)' : ''));
    };
    const randomRow = (win, x, recentWindow) => {
      const p = num(rec(win.random).p_value);
      const thr = num(x.holm_threshold);
      if (thr != null) return { main: fmtP(p), sub: holmReason(thr, num(x.trial_count) ?? 0).replace(/^ · /, '') };
      const check = recentWindow ? findCheck(gate, /^beats random entries \(last 3/i) : null;
      return { main: fmtP(p), sub: check && check.required ? 'required: ' + str(check.required) : 'no correction here' };
    };
    const rows = [
      ['Profit per trade', rCell(hold.expectancy_r, 'after costs'), rCell(recent.expectancy_r, 'after costs')],
      ['Likely range (95%)', { main: fmtRange2(hx.expectancy_ci) }, { main: fmtRange2(rx.expectancy_ci) }],
      ['At 1.5× costs', rCell(hx.expectancy_1_5x_costs), rCell(rx.expectancy_1_5x_costs)],
      ['At 2× costs', rCell(hx.expectancy_2x_costs, 'for info, not a check'), rCell(rx.expectancy_2x_costs, 'for info, not a check')],
      ['Long trades', split(hx.long), split(rx.long)],
      ['Short trades', split(hx.short), split(rx.short)],
      ['Calm market (low volatility)', tercile(hx, 'low'), tercile(rx, 'low')],
      ['Normal market (mid volatility)', tercile(hx, 'mid'), tercile(rx, 'mid')],
      ['Busy market (high volatility)', tercile(hx, 'high'), tercile(rx, 'high')],
      ['Stop vs target distance', { main: fmtX(hx.stop_target_ratio), sub: 'limit 2×' }, { main: fmtX(rx.stop_target_ratio), sub: 'limit 2×' }],
      ['Random entry times did as well', randomRow(hold, hx, false), randomRow(recent, rx, true)],
    ];
    const cell = (c) => h('td', { class: 'num' + (c.cls ? ' ' + c.cls : '') }, h('span', { class: 'v' }, c.main), c.sub ? h('span', { class: 'sub' }, c.sub) : null);
    return h('section', { class: 'stress', 'aria-label': 'Stress tests and splits' },
      h('div', { class: 'fig-head' }, h('div', null,
        h('h4', null, 'Stress tests and splits'),
        h('p', null, 'A real edge should survive higher costs, work for longs and shorts, and stay positive in most market moods. Volatility thirds use cut points from the months the rule was built on.'))),
      h('div', { class: 'table-wrap' }, h('table', { class: 'tbl stress-tbl' },
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, h('span', { class: 'sr-only' }, 'Measure')),
          h('th', { scope: 'col', class: 'num' }, 'Never-seen months'), h('th', { scope: 'col', class: 'num' }, 'Last 3 months'))),
        h('tbody', null, rows.map(([label, a, b]) => h('tr', null, h('th', { scope: 'row' }, label), cell(a), cell(b)))))));
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
      const value = [c.value ? niceMinus(c.value) : null, c.required ? 'required: ' + lowerFirst(str(c.required)) : null].filter(Boolean).join(' · ');
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
        ? h('p', { class: 'small muted' }, `Development months (used to build the rule): ${fmtInt(dev.trades)} trades, ${fmtPct(dev.win_rate)} wins. They never count toward passing the gate; they only set the volatility cut points.`)
        : null,
    ];
  }

  function minLotNote(m, symbols) {
    if (!Object.keys(m).length || num(m.risk_pct) == null) return h('p', { class: 'muted' }, 'Not calculated yet: no trades to measure a typical stop.');
    const risk = rec(ui.state.risk);
    const limits = rec(risk.limits);
    const cap = num(limits.risk_per_trade_cap_pct) ?? num(limits.risk_per_trade_pct);
    const currency = str(rec(risk.account).currency) || 'USD';
    const fits = m.ok !== false;
    const overCap = cap != null && m.risk_pct > cap + 1e-9;
    const capText = cap != null ? ` ${fmtPts(cap)}` : '';
    const rows = list(risk.min_lot).map(rec).filter((row) => symbols.includes(str(row.symbol)));
    const problems = rows.filter((row) => row.ok === false && row.note);
    const verdict = fits ? `Fits the${capText} risk cap and the margin limit`
      : overCap ? `Too big for the${capText} per-trade cap` : `Does not fit for ${problems.map((row) => str(row.symbol)).join(', ') || 'every symbol it trades'}`;
    const worst = rows.filter((row) => num(row.risk_pct) != null).sort((a, b) => b.risk_pct - a.risk_pct)[0];
    const whose = str(rec(risk.account).source) === 'local' ? 'your account' : 'the placeholder account';
    return [
      h('p', null, `${symbols.length > 1 ? `Worst of its symbols (${worst ? str(worst.symbol) : DASH}): median` : 'Median'} stop ${fmtInt(m.median_stop_points)} points → risks ${fmtMoney(m.risk, currency)} (${fmtPts(m.risk_pct, 2)} of ${whose}) at the minimum lot.`),
      h('p', null, h('span', { class: 'fits ' + (fits ? 'yes' : 'no') }, icon(fits ? 'check' : 'cross'), verdict)),
      !fits && problems.length ? h('ul', { class: 'notes' }, problems.map((row) => h('li', null, h('span', { class: 'fits no' }, icon('cross')),
        h('span', null, `${str(row.symbol)}: ${str(row.note)}`)))) : null,
      h('p', { class: 'small muted' }, 'Other account sizes: see the Risk tab.'),
    ];
  }

  // ---------------------------------------------------------------- reading the gate

  function gateSection(s) {
    const power = powerRows(s.power);
    return h('section', { class: 'agent-group', id: 'sec-gate', 'aria-labelledby': 'grp-gate' },
      groupHead('grp-gate', 'Reading the gate', 'Two things that surprise most people: a high win rate can still lose money, and a small real edge usually fails a short test.'),
      h('div', { class: power.length ? 'gate-grid' : 'gate-grid one' }, calculatorCard(), power.length ? powerCard(power) : null));
  }

  function breakEven(c) {
    if (!(c.target > 0 && c.stop > 0 && c.cost >= 0)) return null;
    return (c.stop + c.cost) / (c.target + c.stop);
  }

  function calculatorCard() {
    const fields = [
      ['target', 'Target', 'Profit when the target is hit, in R.'],
      ['stop', 'Stop', 'Loss when the stop is hit. 1R = the amount risked.'],
      ['cost', 'Costs per trade', 'Spread, commission and slippage, in R.'],
    ];
    const out = h('div', { class: 'calc-out', 'aria-live': 'polite' });
    const inputs = {};
    const presets = CALC_PRESETS.map((p) => h('button', { type: 'button', 'data-preset': p.label },
      `${p.label} (${p.target}R : ${p.stop}R)`));
    const syncPresets = () => presets.forEach((btn, i) => {
      const p = CALC_PRESETS[i];
      btn.setAttribute('aria-pressed', String(p.target === ui.calc.target && p.stop === ui.calc.stop && p.cost === ui.calc.cost));
    });
    const update = () => {
      out.replaceChildren(...calcResult(ui.calc));
      syncPresets();
    };
    const form = h('div', { class: 'calc-fields' }, fields.map(([key, label, help]) => {
      const id = 'calc-' + key;
      const input = h('input', { id, type: 'number', inputmode: 'decimal', min: '0', step: key === 'cost' ? '0.005' : '0.05', value: String(ui.calc[key]), 'aria-describedby': id + '-help' });
      input.addEventListener('input', () => {
        const v = parseFloat(input.value);
        ui.calc = Object.assign({}, ui.calc, { [key]: Number.isFinite(v) ? v : NaN });
        update();
      });
      inputs[key] = input;
      return h('div', { class: 'calc-field' }, h('label', { for: id }, label, h('span', { class: 'unit' }, ' (R)')), input,
        h('p', { class: 'calc-help', id: id + '-help' }, help));
    }));
    presets.forEach((btn, i) => btn.addEventListener('click', () => {
      const p = CALC_PRESETS[i];
      ui.calc = { target: p.target, stop: p.stop, cost: p.cost };
      Object.keys(inputs).forEach((k) => { inputs[k].value = String(ui.calc[k]); });
      update();
    }));
    update();
    return h('section', { class: 'card calc', 'aria-labelledby': 'calc-h' },
      h('div', { class: 'fig-head' }, h('div', null,
        h('h3', { id: 'calc-h' }, icon('calc'), 'Why 80% wins can still lose money'),
        h('p', null, 'Put the target 4× closer than the stop and even random entries win about 80%. Break-even win rate = (stop + costs) ÷ (target + stop).'))),
      h('div', { class: 'seg presets', role: 'group', 'aria-label': 'Examples' }, presets),
      form,
      out);
  }

  function calcResult(c) {
    const be = breakEven(c);
    if (be == null) return [h('p', { class: 'calc-error', role: 'alert' }, 'Enter a target and a stop above 0, and costs of 0 or more.')];
    const bar = accuracyBar();
    const atBar = bar * c.target - (1 - bar) * c.stop - c.cost;
    const digits = Math.abs(atBar) < 0.1 ? 3 : 2;
    const beText = fmtPct(Math.min(be, 1), 1);
    const sentence = be >= 1
      ? 'Even winning every trade would not cover the costs.'
      : `You must win more than ${beText} of trades just to break even. At the ${fmtPct(bar)} bar you would ${atBar < 0 ? 'lose' : 'make'} ${fmtR(Math.abs(atBar), digits).replace(/^\+/, '')} per trade.`;
    const track = h('div', { class: 'calc-track', role: 'img', 'aria-label': `Break-even win rate ${beText}; the bar is ${fmtPct(bar)}.` });
    const loss = setWidth(h('span', { class: 'zone lose' }), Math.min(be, 1));
    const markBe = h('span', { class: 'mark be' });
    markBe.style.left = clamp(be, 0, 1) * 100 + '%';
    const markBar = h('span', { class: 'mark bar' });
    markBar.style.left = clamp(bar, 0, 1) * 100 + '%';
    track.append(loss, markBar, markBe);
    const label = (cls, text, at) => {
      const node = h('span', { class: 'calc-label ' + cls }, text);
      node.style.left = clamp(at, 0.06, 0.94) * 100 + '%';
      return node;
    };
    return [
      h('p', { class: 'calc-big' }, h('span', null, 'Break-even win rate'), h('strong', null, beText)),
      h('div', { class: 'calc-scale', 'aria-hidden': 'true' }, label('above', `${fmtPct(bar)} bar`, bar)),
      track,
      h('div', { class: 'calc-scale', 'aria-hidden': 'true' }, label('below', `break-even ${beText}`, Math.min(be, 1))),
      h('p', { class: 'calc-legend' }, h('span', { class: 'key lose' }), 'Loses money', h('span', { class: 'key win' }), 'Makes money'),
      h('p', { class: 'calc-note ' + (atBar < 0 ? 'neg' : 'pos') }, sentence),
    ];
  }

  function powerRows(power) {
    return list(power).map(rec).filter((p) => num(p.edge_r) != null && num(p.trades) != null && num(p.pass_rate) != null);
  }

  function powerCard(rows) {
    const edges = [...new Set(rows.map((p) => p.edge_r))].sort((a, b) => a - b);
    const trades = [...new Set(rows.map((p) => p.trades))].sort((a, b) => a - b);
    const value = (e, n) => {
      const row = rows.find((p) => p.edge_r === e && p.trades === n);
      return row ? clamp(row.pass_rate, 0, 1) : null;
    };
    const focus = edges.includes(0.1) ? 0.1 : edges[Math.floor(edges.length / 2)];
    const first = value(focus, trades[0]);
    const last = value(focus, trades[trades.length - 1]);
    const note = first != null && last != null
      ? `A rule with a real ${fmtTickR(focus)} edge per trade passes only ${fmtPct(first)} of the time with ${fmtInt(trades[0])} trades, and ${fmtPct(last)} with ${fmtInt(trades[trades.length - 1])}. A pass means “start a forward test”, not “proven”.`
      : null;
    const legend = h('ul', { class: 'legend', 'aria-label': 'Real edge per trade' }, edges.map((e, i) =>
      h('li', null, h('span', { class: 'key-line', style: `--c: ${powerColor(i, edges.length)}` }), fmtTickR(e))));
    return h('figure', { class: 'card fig power' },
      h('div', { class: 'fig-head' }, h('div', null,
        h('h3', null, 'How often the gate catches a real edge'),
        h('p', null, 'Simulated 1:1 rules with a true edge per trade, put through the expectancy and random-entry checks at different trade counts.'))),
      legend,
      chartBox((w) => drawPower(w, edges, trades, value)),
      note ? h('p', { class: 'fig-note' }, note) : null,
      tableView(['Real edge per trade'].concat(trades.map((n) => `${fmtInt(n)} trades`)),
        edges.map((e) => [fmtTickR(e)].concat(trades.map((n) => (value(e, n) == null ? DASH : fmtPct(value(e, n), 1)))))));
  }

  function powerColor(i, n) {
    if (n === 4) return `var(--pw-${i + 1})`;
    const t = n <= 1 ? 1 : i / (n - 1);
    return `color-mix(in oklab, var(--pw-4) ${Math.round(t * 100)}%, var(--pw-1))`;
  }

  // ---------------------------------------------------------------- context agents

  function contextSection(s) {
    const ctx = rec(s.context);
    const tagger = rec(ctx.event_tagger);
    const regime = list(ctx.regime).map(rec);
    if (!Object.keys(tagger).length && !regime.length) return null;
    return h('section', { class: 'agent-group', id: 'sec-context', 'aria-labelledby': 'grp-context' },
      groupHead('grp-context', 'Context agents', 'They read the calendar and the market mood. In v1 they run in shadow: scored and logged, affecting nothing.'),
      h('div', { class: 'ctx-grid' }, Object.keys(tagger).length ? taggerCard(tagger) : null, regime.length ? regimeCard(regime) : null));
  }

  function taggerCard(t) {
    const rows = list(t.last).map(rec);
    const split = rows.filter((r) => new Set(list(r.verdicts).map(str)).size > 1).length;
    const outcome = (r) => {
      const verdicts = list(r.verdicts).map(str);
      if (new Set(verdicts).size > 1) return { text: 'No opinion (split)', cls: 'idle', icon: 'idle' };
      if (r.pause === true) return { text: 'Would pause (shadow, not sent)', cls: 'warn', icon: 'pause' };
      return { text: 'No pause', cls: 'ok', icon: 'check' };
    };
    const vchip = (v) => {
      const pause = /^pause$/i.test(v);
      return h('span', { class: 'vchip' + (pause ? ' pause' : ''), title: pause ? 'pause' : 'no pause' },
        icon(pause ? 'pause' : 'check'), h('span', { class: 'sr-only' }, pause ? 'pause' : 'no pause'));
    };
    const cell = (label, content, cls) => h('td', { 'data-label': label, class: cls }, content);
    return h('section', { class: 'card block tagger', 'aria-labelledby': 'tagger-h' },
      h('div', { class: 'tagger-head' },
        h('h3', { id: 'tagger-h' }, 'Event-risk tagger'),
        h('div', { class: 'chips' }, kindChip('llm'), t.stage ? h('span', { class: 'chip outline chip-wrap' }, 'Stage: ' + titleCase(t.stage)) : null,
          t.measured ? h('span', { class: 'chip warn chip-wrap', title: 'Fewer than 30 scored calls: no accuracy can be claimed.' }, icon('clock'), str(t.measured)) : null,
          h('span', { class: 'chip info' }, icon('info'), 'Self-test, not accuracy'))),
      h('dl', { class: 'kv' },
        h('dt', null, 'Question'), h('dd', null, 'A high-impact event for this symbol within 2 hours?'),
        h('dt', null, 'Model'), h('dd', null, str(t.model) || DASH),
        h('dt', null, 'Samples'), h('dd', null, `${fmtInt(t.samples)} per question. A pause only when all ${fmtInt(t.samples)} agree; a split means no opinion.`)),
      t.note ? h('p', { class: 'small muted' }, str(t.note)) : null,
      rows.length
        ? h('div', { class: 'table-wrap' }, h('table', { class: 'tbl cards tagger-tbl' },
          h('caption', { class: 'sr-only' }, 'Latest answers from the event-risk tagger'),
          h('thead', null, h('tr', null, ['Symbol', 'Event', 'Answers', 'Result'].map((x) => h('th', { scope: 'col' }, x)))),
          h('tbody', null, rows.map((r) => {
            const o = outcome(r);
            return h('tr', null,
              cell('Symbol', str(r.symbol), 'lead'),
              cell('Event', h('span', { class: 'ev' }, str(r.event), h('span', { class: 'sub' }, fmtDateTime(r.time)))),
              cell('Answers', h('span', { class: 'vchips' }, list(r.verdicts).map(str).map(vchip))),
              cell('Result', h('span', { class: 'res' }, chip({ label: o.text, icon: o.icon, cls: o.cls }),
                r.agreement ? h('span', { class: 'sub' }, `${str(r.agreement)} agree`) : null)));
          }))))
        : h('p', { class: 'muted' }, 'No answers yet.'),
      rows.length ? h('p', { class: 'calc-legend' }, h('span', { class: 'vchip pause' }, icon('pause')), 'pause', h('span', { class: 'vchip' }, icon('check')), 'no pause') : null,
      rows.length ? h('p', { class: 'small muted' }, `${split} of ${rows.length} questions got split answers this run. Under 30 scored calls the tagger stays UNMEASURED, whatever it says.`) : null);
  }

  function regimeCard(rows) {
    const VOL = { 1: 'Calm', 2: 'Normal', 3: 'Busy' };
    const TREND = { up: { icon: 'up', label: 'Up' }, down: { icon: 'down', label: 'Down' }, flat: { icon: 'flat', label: 'Flat' } };
    const cell = (label, content, cls) => h('td', { 'data-label': label, class: cls }, content);
    return h('section', { class: 'card block regime', 'aria-labelledby': 'regime-h' },
      h('div', { class: 'tagger-head' }, h('h3', { id: 'regime-h' }, 'Regime agent'), h('div', { class: 'chips' }, kindChip('code'))),
      h('p', { class: 'small muted' }, 'Volatility third from the H1 ATR (1 = calm, 3 = busy) and trend from EMA 20 vs 50. Code only, no AI.'),
      h('div', { class: 'table-wrap' }, h('table', { class: 'tbl cards regime-tbl' },
        h('caption', { class: 'sr-only' }, 'Volatility and trend per symbol'),
        h('thead', null, h('tr', null, ['Symbol', 'Volatility', 'Trend'].map((x) => h('th', { scope: 'col' }, x)))),
        h('tbody', null, rows.map((r) => {
          const n = clamp(Math.round(num(r.vol_tercile) ?? 0), 0, 3);
          const steps = h('span', { class: 'terc', 'aria-hidden': 'true' }, [1, 2, 3].map((k) => h('span', { class: k <= n ? 'on' : null })));
          const trend = TREND[str(r.trend)] || { icon: 'idle', label: titleCase(r.trend) || DASH };
          return h('tr', null,
            cell('Symbol', str(r.symbol), 'lead'),
            cell('Volatility', h('span', { class: 'terc-cell' }, steps, n ? `${VOL[n]} (${n} of 3)` : DASH)),
            cell('Trend', h('span', { class: 'trend' }, icon(trend.icon), trend.label)));
        })))));
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
    const stageNames = new Map(CHECK_STAGES.map((st) => [st.id, st.name]));
    list(s.pipeline).map(rec).forEach((p) => { if (p.id && p.name) stageNames.set(str(p.id), str(p.name)); });
    const order = CHECK_STAGES.map((st) => st.id);
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
            h('div', { class: 'check-meta' }, checkMeta(str(c.subject), names.get(c.agent_id) || str(c.agent_id))),
            c.detail ? h('p', { class: 'check-detail' }, niceMinus(c.detail)) : null)))));
    });
  }

  function checkMeta(subject, agent) {
    const same = (a, b) => a.toLowerCase().includes(b.toLowerCase());
    // Subjects already name the rule ("Planted pattern"); repeating the agent ("Self-test: planted pattern") adds nothing.
    if (subject && agent && (same(subject, agent) || same(agent, subject))) return subject;
    return [subject, agent].filter(Boolean).join(' · ');
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
    const connected = rec(s.meta).account_feed === true;
    const local = str(account.source) === 'local';
    const daily = num(limits.daily_stop_pct) ?? num(limits.max_daily_loss_pct);
    const cap = num(limits.risk_per_trade_cap_pct);
    const maxPos = num(limits.max_open_positions);
    return [
      head,
      connected ? null : h('p', { class: 'feed-note', role: 'note' }, icon('plug'), h('span', null, h('strong', null, 'No live account feed. '),
        'Open risk, margin and losses read 0% because v1 cannot see your account. Nothing watches or stops your live account until the Guardian EA is built (Phase 1).')),
      h('div', { class: 'gauges' },
        gauge('Open risk', usage.open_risk_pct, limits.max_open_risk_pct, 'What you could lose if every open trade hit its stop.', connected),
        gauge('Margin in use', usage.margin_use_pct, limits.max_margin_use_pct, 'Share of the account held as margin by open trades.', connected),
        gauge('Loss today', usage.daily_loss_pct, daily, 'Once connected, everything stops for the day at this limit.', connected)),
      h('dl', { class: 'card facts' },
        fact('Risk per trade', fmtPts(limits.risk_per_trade_pct) + (cap != null ? ` (cap ${fmtPts(cap)})` : '')),
        fact('Open positions', connected ? fmtInt(usage.open_positions) + (maxPos != null ? ` of ${fmtInt(maxPos)}` : '') : `not connected (limit ${fmtInt(maxPos)})`),
        fact(local ? 'Your account size (settings.local.json)' : 'Account size (placeholder, not yours)', fmtMoney(account.balance, currency, true)),
        fact('Leverage', num(account.leverage) != null ? '1:' + fmtInt(account.leverage) : DASH)),
      rulesBlock(limits, connected),
      groupsBlock(list(risk.groups).map(rec), limits),
      h('div', { class: 'risk-split' }, minLotTable(list(risk.min_lot).map(rec), currency, limits, account), correlationBlock(rec(risk.correlation))),
      balancesBlock(list(risk.min_lot_balances).map(rec), currency, limits),
      bridgeBlock(rec(s.bridge)),
    ];
  }

  function rulesBlock(limits, connected) {
    const p = (v) => fmtPts(num(v), Number.isInteger(num(v)) ? 0 : 1);
    const has = (...keys) => keys.every((k) => num(limits[k]) != null);
    const bo = rec(limits.blackouts);
    const items = [];
    if (has('risk_per_trade_pct')) {
      items.push(['target', 'Per trade', `Risk ${p(limits.risk_per_trade_pct)} of equity` + (has('risk_per_trade_cap_pct')
        ? `, never more than ${p(limits.risk_per_trade_cap_pct)}. If even the minimum lot would risk more, the trade is skipped, never rounded up.` : '.')]);
    }
    if (has('max_open_risk_pct')) {
      items.push(['scale', 'Open risk', `At most ${p(limits.max_open_risk_pct)} at risk across all open trades` + (has('max_cluster_risk_pct')
        ? `, and at most ${p(limits.max_cluster_risk_pct)} per cluster of symbols that move together, with no credit for hedges.` : '.')]);
    }
    if (has('max_margin_use_pct')) items.push(['gauge', 'Margin', `At most ${p(limits.max_margin_use_pct)} of the account held as margin after a new trade.`]);
    if (has('daily_stop_pct')) {
      const parts = [`Stop for the day at −${p(limits.daily_stop_pct)}`];
      if (has('weekly_stop_pct')) parts.push(`for the week at −${p(limits.weekly_stop_pct)}`);
      let text = parts.join(', ');
      if (has('overall_kill_pct')) text += `. At −${p(limits.overall_kill_pct)} from the equity peak everything stops until your YES`;
      items.push(['stop', 'Loss stops', text + '.']);
    }
    if (has('max_open_positions')) {
      const bits = [`At most ${fmtInt(limits.max_open_positions)} open positions (hand trades included)`];
      if (has('max_entries_per_day')) bits.push(`${fmtInt(limits.max_entries_per_day)} new entries a day`);
      if (has('min_minutes_between_entries_per_symbol')) bits.push(`one entry per symbol every ${fmtMinutes(limits.min_minutes_between_entries_per_symbol)}`);
      items.push(['list', 'Activity', bits.join(', ') + '.']);
    }
    if (has('spread_skip_multiple') || has('pause_after_full_stops')) {
      const bits = [];
      if (has('spread_skip_multiple')) bits.push(`Skip a trade when the spread is over ${fmtX(limits.spread_skip_multiple)} the usual for that hour.`);
      if (has('pause_after_full_stops')) bits.push(`Pause a rule after ${fmtInt(limits.pause_after_full_stops)} full stops in a row.`);
      items.push(['warn', 'Spread and losing streaks', bits.join(' ')]);
    }
    if (Object.keys(bo).length) {
      const bits = [];
      if (num(bo.news_minutes) != null) bits.push(`${fmtInt(bo.news_minutes)} minutes around news` + (num(bo.major_news_minutes) != null ? ` (${fmtInt(bo.major_news_minutes)} around FOMC, NFP and CPI)` : ''));
      if (bo.rollover) bits.push(`during the rollover, ${fmtRollover(bo.rollover)}`);
      if (bo.friday_cutoff_utc) bits.push(`on Fridays after ${str(bo.friday_cutoff_utc)} UTC`);
      if (num(bo.calendar_max_age_hours) != null) bits.push(`when the news calendar is more than ${fmtInt(bo.calendar_max_age_hours)} hours old`);
      if (bits.length) items.push(['clock', 'No-trade times', 'No new entries ' + joinWords(bits) + '.']);
    }
    if (!items.length) return null;
    return h('section', { class: 'card block', 'aria-labelledby': 'rules-h' },
      blockHead('Risk rules in plain words', 'All in % of equity, for every agent and hand trade together. Changing any of them needs your YES on the Approvals tab.' +
        (connected ? '' : ' Written down and tested, but enforced on no account until the Guardian EA is built.'), 'rules-h'),
      h('ul', { class: 'rules' }, items.map(([ic, title, text]) => h('li', { class: 'rule' }, h('span', { class: 'rule-icon' }, icon(ic)),
        h('div', null, h('h4', null, title), h('p', null, text))))));
  }

  function fmtMinutes(v) {
    const m = num(v);
    if (m == null) return DASH;
    return m % 60 === 0 ? (m === 60 ? 'hour' : `${m / 60} hours`) : `${fmtInt(m)} minutes`;
  }

  function fmtRollover(text) {
    const m = /^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s+(.+)$/.exec(str(text).trim());
    if (!m) return str(text);
    const zone = m[3].includes('/') ? m[3].split('/').pop().replace(/_/g, ' ') + ' time' : m[3];
    return `${m[1]}–${m[2]} ${zone}`;
  }

  function joinWords(parts) {
    if (parts.length < 2) return parts.join('');
    return parts.slice(0, -1).join(', ') + ' or ' + parts[parts.length - 1];
  }

  function gauge(label, used, limit, help, connected = true) {
    const l = num(limit);
    if (!connected) {
      return h('div', { class: 'card gauge na' },
        h('div', { class: 'gauge-top' }, h('span', { class: 'gauge-label' }, label), h('span', { class: 'gauge-val' }, h('small', null, 'limit ' + fmtPts(l)))),
        h('div', { class: 'meter na', role: 'img', 'aria-label': `${label}: not connected. Limit ${fmtPts(l)}.` }),
        h('p', { class: 'gauge-status na' }, icon('plug'), 'Not connected: v1 cannot see your account'),
        h('p', { class: 'small muted' }, help));
    }
    const u = num(used);
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
    const cluster = num(limits.max_cluster_risk_pct);
    const max = num(limits.max_positions_per_group);
    const intro = 'Symbols in a cluster move together, so they count as one bet, as if fully correlated, with no credit for hedges' +
      (cluster != null ? `: together at most ${fmtPts(cluster, Number.isInteger(cluster) ? 0 : 1)} risk.` : max != null ? `: at most ${fmtInt(max)} open position${max === 1 ? '' : 's'} per cluster.` : '.');
    return h('section', { class: 'card block', 'aria-labelledby': 'groups-h' },
      blockHead('Exposure by cluster', intro, 'groups-h'),
      groups.length ? h('div', { class: 'groups' }, groups.map(groupCard)) : h('p', { class: 'muted' }, 'No clusters configured.'));
  }

  const CLUSTER_WORDS = {
    USD: ['Rises when the dollar rises', 'Falls when the dollar rises'],
    RISK_ON: ['Rise together when markets are upbeat', 'Fall when markets are upbeat'],
  };

  function groupCard(g) {
    const [withWords, againstWords] = CLUSTER_WORDS[str(g.id).toUpperCase()] || ['Move together', 'Move the opposite way'];
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
        withGroup.length ? [h('dt', null, withWords), h('dd', null, symList(withGroup))] : null,
        against.length ? [h('dt', null, againstWords), h('dd', null, symList(against))] : null),
      h('p', { class: 'small muted' }, 'All count as one bet.'),
      h('div', { class: 'risk-row' }, h('span', null, `Risk ${fmtPts(used)} of ${fmtPts(limit)} cluster limit`), meter));
  }

  function fitsMark(ok, text) {
    if (ok == null) return h('span', { class: 'fits unknown' }, icon('idle'), text || 'Not measured');
    return h('span', { class: 'fits ' + (ok ? 'yes' : 'no') }, icon(ok ? 'check' : 'cross'), text || (ok ? 'Fits' : 'Doesn’t fit'));
  }

  function minLotTable(rows, currency, limits, account) {
    const cap = num(limits.risk_per_trade_cap_pct) ?? num(limits.risk_per_trade_pct);
    const size = num(rec(account).balance);
    const whose = str(rec(account).source) === 'local' ? 'your balance from settings.local.json' : 'placeholder, not your account';
    const intro = `With the typical stop, one minimum lot must not risk more than ${fmtPts(cap)} of the account` +
      (size != null ? ` (here ${fmtMoney(size, currency, true)}: ${whose}).` : '.');
    const headers = ['Symbol', 'Min lot', 'Typical stop', 'Risk at min lot', 'Margin at min lot', 'Fits?'];
    const cell = (label, content, cls) => h('td', { 'data-label': label, class: cls }, h('span', null, content));
    const body = rows.map((r) => {
      const measured = num(r.risk_pct) != null;
      return h('tr', null,
        cell('Symbol', str(r.symbol), 'lead'),
        cell('Min lot', fmtLot(r.min_lot), 'num'),
        cell('Typical stop', measured ? fmtInt(r.median_stop_points) + ' pts' : DASH, 'num'),
        cell('Risk at min lot', measured ? `${fmtMoney(r.risk_at_min_lot, currency)} (${fmtPts(r.risk_pct, 2)})` : DASH, 'num'),
        cell('Margin at min lot', fmtMoney(r.margin_at_min_lot, currency), 'num'),
        cell('Fits?', [fitsMark(r.ok), r.note ? h('span', { class: 'note' }, str(r.note)) : null]));
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
    // The synthetic self-test symbol is never traded, so it has no place in a picture of real exposure.
    const keep = list(c.symbols).map(str).map((sym, i) => [sym, i]).filter(([sym]) => !/^CTRL-SYN$/i.test(sym));
    const syms = keep.map(([sym]) => sym);
    const matrix = keep.map(([, i]) => list(list(c.matrix)[i])).map((row) => keep.map(([, j]) => row[j]));
    const ok = syms.length > 1 && matrix.length === syms.length && matrix.every((row) => Array.isArray(row) && row.length === syms.length);
    const intro = 'From −1 (move opposite) to +1 (move together). Strongly linked symbols are one bet, not two.' + (c.window ? ' Window: ' + str(c.window) + '.' : '');
    return h('section', { class: 'card block', 'aria-labelledby': 'corr-h' },
      blockHead('How symbols move together', intro, 'corr-h'),
      ok ? chartBox((w) => drawHeatmap(w, syms, matrix)) : chartEmpty('No correlation data yet.'),
      ok ? h('div', { class: 'hm-legend', 'aria-hidden': 'true' }, h('div', { class: 'hm-ramp' }),
        h('div', { class: 'hm-ends' }, h('span', null, '−1 opposite'), h('span', null, '0 unrelated'), h('span', null, '+1 together'))) : null);
  }

  function balancesBlock(groups, currency, limits) {
    const sizes = groups.filter((g) => num(g.balance) != null);
    if (!sizes.length) return null;
    const cap = num(limits.risk_per_trade_cap_pct) ?? num(limits.risk_per_trade_pct);
    const symbols = [];
    sizes.forEach((g) => list(g.rows).map(rec).forEach((r) => { if (r.symbol && !symbols.includes(str(r.symbol))) symbols.push(str(r.symbol)); }));
    const find = (g, sym) => list(g.rows).map(rec).find((r) => str(r.symbol) === sym) || null;
    const label = (g) => fmtMoney(g.balance, currency, true);
    const notes = [];
    const body = symbols.map((sym) => h('tr', null,
      h('td', { 'data-label': 'Symbol', class: 'lead' }, h('span', null, sym)),
      sizes.map((g) => {
        const r = find(g, sym);
        if (!r || num(r.risk_pct) == null) return h('td', { 'data-label': label(g), class: 'num' }, h('span', { title: 'No typical stop measured yet' }, DASH));
        const fits = r.ok !== false;
        if (r.note) notes.push({ fits, text: `${sym} at ${label(g)}: ${str(r.note)}` });
        const share = r.risk_pct > 0 && r.risk_pct < 0.01 ? '<0.01%' : fmtPts(r.risk_pct, 2);
        return h('td', { 'data-label': label(g), class: 'num' }, h('span', { class: 'fits ' + (fits ? 'yes' : 'no') },
          icon(fits ? 'check' : 'cross'), share, h('span', { class: 'sr-only' }, fits ? ', fits' : ', does not fit')));
      })));
    return h('section', { class: 'card block', 'aria-labelledby': 'bal-h' },
      blockHead('Does the minimum lot fit other account sizes?', `Risk of one minimum lot with the typical stop, as a share of four example balances (placeholders, not your account). Over the ${fmtPts(cap)} cap, trades are skipped.`, 'bal-h'),
      h('div', { class: 'table-wrap' }, h('table', { class: 'tbl cards balances' },
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Symbol'), sizes.map((g) => h('th', { scope: 'col', class: 'num' }, label(g))))),
        h('tbody', null, body))),
      notes.length ? h('ul', { class: 'notes' }, notes.map((n) => h('li', null, h('span', { class: 'fits ' + (n.fits ? 'yes' : 'no') }, icon(n.fits ? 'info' : 'cross')), h('span', null, n.text)))) : null);
  }

  function bridgeBlock(b) {
    const advisories = list(b.advisories).map(rec);
    const kill = b.kill_flag === true;
    return h('section', { class: 'card block', 'aria-labelledby': 'bridge-h' },
      blockHead('Bridge to MT5', 'The only thing that leaves this system: a small advisories file a fixed-rule EA on your PC can read. An advisory can only pause a symbol for up to 4 hours. It never carries a lot size, a direction or an entry, and nothing here places orders.', 'bridge-h'),
      h('dl', { class: 'kv' },
        h('dt', null, 'File'), h('dd', null, h('code', null, str(b.file) || DASH)),
        h('dt', null, 'Heartbeat'), h('dd', null, b.heartbeat ? h('time', { datetime: str(b.heartbeat) }, fmtDateTime(b.heartbeat)) : DASH, h('span', { class: 'small muted' }, ' · shows the file is fresh')),
        h('dt', null, 'Kill flag'), h('dd', null, h('span', { class: 'fits ' + (kill ? 'no' : 'yes') }, icon(kill ? 'stop' : 'check'),
          kill ? 'Present: kill.flag tells the EA to stop all entries' : 'Absent (kill switch off)')),
        h('dt', null, 'Advisories'), h('dd', null, advisories.length ? `${fmtInt(advisories.length)} pause${advisories.length === 1 ? '' : 's'}` : 'None')),
      b.note ? h('p', null, str(b.note)) : null,
      advisories.length ? h('ul', { class: 'bridge-list' }, advisories.map(advisoryLine)) : null);
  }

  function advisoryLine(a) {
    return h('li', null, h('span', { class: 'chip warn chip-wrap' }, icon('pause'), 'Pause ' + (str(a.symbol) || DASH)),
      h('span', null, `${str(a.reason) || 'No reason given'} · until ${fmtDateTime(a.expires_at)}`), h('span', { class: 'small muted' }, str(a.id)));
  }

  // ---------------------------------------------------------------- approvals

  function renderApprovals(s) {
    const approvals = rec(s.approvals);
    const pending = list(approvals.pending).map(rec);
    const history = list(approvals.history).map(rec);
    return [
      panelHead('Waiting for your YES', 'No lot, rule or settings change takes effect until you approve it here by typing YES.'),
      pending.length ? h('div', { class: 'agent-list' }, pending.map((item) => approvalCard(item, s))) : emptyBox('Nothing is waiting for your YES.'),
      h('h3', { class: 'section-title' }, 'History'),
      history.length ? h('ul', { class: 'history' }, history.map(historyRow)) : emptyBox('No decisions yet.'),
    ];
  }

  function approvalCard(item, s) {
    const baseline = str(item.kind).toLowerCase() === 'baseline';
    const names = new Map(list(rec(s).research).map(rec).map((r) => [str(r.rule_id), str(r.name)]));
    const id = str(item.id);
    const actions = ui.snapshot
      ? h('p', { class: 'snapshot-howto' }, icon('info'), h('span', null, 'Buttons are off in this file. To decide, on your PC run ',
        h('code', null, `python -m llm_trader approve ${id} --yes`), ' (or ', h('code', null, `reject ${id}`), '), or run ',
        h('code', null, 'python -m llm_trader serve'), ' and open http://127.0.0.1:8765.'))
      : h('div', { class: 'approval-actions' },
        lockAction(h('button', { type: 'button', class: 'btn btn-primary', id: 'approve-' + slug(id), onclick: () => approveChange(item, names) }, icon('check'), 'Approve…')),
        lockAction(h('button', { type: 'button', class: 'btn', id: 'reject-' + slug(id), onclick: () => rejectChange(item) }, icon('cross'), 'Reject…')));
    return h('article', { class: 'card approval' },
      h('div', { class: 'approval-head' }, h('h3', null, str(item.summary) || id), h('span', { class: 'chip outline chip-wrap' }, titleCase(item.kind) || 'Change')),
      h('p', { class: 'small muted' }, `${id} · requested ${fmtDateTime(item.created_at)}`),
      baseline ? h('p', null, 'This is the starting point: approving it records today’s settings and locked test plans as yours. After that, every change shows up here line by line. Until you decide, safe mode keeps the bridge closed.') : null,
      baseline ? adoptingBlock(s) : null,
      baseline
        ? h('details', { class: 'fingerprints' }, h('summary', null, 'Fingerprints (SHA-256) of what you approve'), diffList(list(item.diff), names))
        : diffList(list(item.diff), names),
      actions);
  }

  function adoptingBlock(s) {
    const limits = rec(rec(rec(s).risk).limits);
    const p = (v) => fmtPts(num(v));
    const bar = fmtPct(accuracyBar());
    const rules = list(rec(s).research).map(rec);
    const items = [
      `Risk ${p(limits.risk_per_trade_pct)} per trade (never more than ${p(limits.risk_per_trade_cap_pct)}), at most ${p(limits.max_open_risk_pct)} open risk in total and ${p(limits.max_cluster_risk_pct)} per cluster, margin at most ${p(limits.max_margin_use_pct)}.`,
      `Loss stops: −${p(limits.daily_stop_pct)} a day, −${p(limits.weekly_stop_pct)} a week, −${p(limits.overall_kill_pct)} from the equity peak.`,
      `At most ${fmtInt(limits.max_open_positions)} open positions and ${fmtInt(limits.max_entries_per_day)} entries a day.`,
    ];
    return h('section', { class: 'adopting', 'aria-label': 'What you are adopting' },
      h('h4', null, 'What you are adopting'),
      h('ul', null,
        items.map((text) => h('li', null, text)),
        h('li', null, `The ${bar} gate, with these locked test plans: `, rules.map((r, i) => [i ? ', ' : null,
          h('a', { href: '#agents/' + encodeURIComponent(str(r.rule_id)) }, str(r.name) || str(r.rule_id))]), '.')),
      rec(rec(s).meta).account_feed === true ? null : h('p', { class: 'small muted' }, 'These limits are written down and tested; they are enforced on no account until the Guardian EA is built.'));
  }

  function diffList(lines, names) {
    if (!lines.length) return null;
    const label = (key) => {
      const m = /^plan (.+)$/.exec(key);
      if (m && names && names.get(m[1])) return names.get(m[1]) + ' plan';
      return key === 'settings' ? 'Settings' : key;
    };
    return h('ul', { class: 'diff', 'aria-label': 'What changes' }, lines.map((line) => {
      const m = /^(.*?):\s*(.*?)\s*(?:→|->)\s*(.*)$/.exec(str(line));
      if (!m) return h('li', null, h('code', null, str(line)));
      const added = m[2] === '(none)';
      return h('li', null, h('code', null, label(m[1])),
        added ? h('span', { class: 'added' }, 'new') : h('span', { class: 'old' }, h('span', { class: 'sr-only' }, 'from '), m[2]),
        h('span', { 'aria-hidden': 'true' }, '→'),
        h('span', { class: 'new' }, h('span', { class: 'sr-only' }, 'to '), m[3]));
    }));
  }

  function historyRow(item) {
    const decision = str(item.decision).toLowerCase();
    const approved = decision === 'approved' || decision === 'approve';
    const def = approved ? { label: 'Approved', icon: 'check', cls: 'approved' } : { label: titleCase(decision) || 'Rejected', icon: 'cross', cls: 'rejected' };
    return h('li', null, chip(def, null, 'chip-wrap'), h('span', { class: 'what' }, str(item.summary) || str(item.id)),
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
        // data-label lets narrow screens show each row as a small card of "label: value" lines.
        out.push(h('div', { class: 'table-wrap' }, h('table', { class: 'md-table' },
          h('thead', null, h('tr', null, header.map((c) => h('th', { scope: 'col' }, mdInline(c))))),
          h('tbody', null, rows.map((row) => h('tr', null, header.map((c, k) => h('td', { 'data-label': c.replace(/[*`_]/g, '') }, mdInline(row[k] || '')))))))));
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
      if (m.index > last) out.push(niceMinus(text.slice(last, m.index)));
      if (m[1] != null) out.push(h('code', null, m[1]));
      else if (m[2] != null || m[3] != null) out.push(h('strong', null, mdInline(m[2] ?? m[3])));
      else if (m[4] != null || m[5] != null) out.push(h('em', null, mdInline(m[4] ?? m[5])));
      else if (/^https?:\/\//i.test(m[7])) out.push(h('a', { href: m[7], rel: 'noopener noreferrer', target: '_blank' }, mdInline(m[6])));
      else out.push(...mdInline(m[6]));
      last = re.lastIndex;
    }
    if (last < text.length) out.push(niceMinus(text.slice(last)));
    return out;
  }

  // ---------------------------------------------------------------- log

  function renderLog(s) {
    const time = (iso) => toDate(iso)?.getTime() ?? 0;
    const rows = list(s.log).map(rec).map((l, i) => Object.assign({}, l, { i, lvl: normLevel(l.level) }))
      .sort((a, b) => time(b.time) - time(a.time) || b.i - a.i);
    const days = new Set(rows.map((r) => fmtDate(r.time)));
    const names = agentNames(s);
    const counts = { all: rows.length, alert: 0, error: 0, warn: 0, info: 0, debug: 0 };
    rows.forEach((r) => { counts[r.lvl] += 1; });
    const options = [['all', 'All', null], ['alert', 'Phone alerts', LOG_LEVEL.alert], ['error', 'Errors', LOG_LEVEL.error], ['warn', 'Warnings', LOG_LEVEL.warn], ['info', 'Info', LOG_LEVEL.info]];
    if (counts.debug) options.push(['debug', 'Debug', LOG_LEVEL.debug]);
    const box = h('div');
    const draw = () => {
      const shown = rows.filter((r) => ui.logFilter === 'all' || r.lvl === ui.logFilter);
      box.replaceChildren(shown.length ? h('ol', { class: 'log' }, shown.map((r) => h('li', { class: 'log-row' + (r.lvl === 'alert' ? ' is-alert' : '') },
        h('time', { datetime: str(r.time), title: fmtDateTime(r.time) }, (days.size > 1 ? fmtDate(r.time, false) + ' ' : '') + fmtClock(r.time)),
        chip(LOG_LEVEL[r.lvl]),
        h('span', { class: 'log-agent' }, names.get(r.agent_id) || str(r.agent_id)),
        h('span', { class: 'log-msg' }, alertText(r))))) : emptyBox(rows.length ? 'No log lines at this level.' : 'No log lines yet.'));
    };
    draw();
    return [
      panelHead('Log', 'What every agent did in the last run, newest first. Supervisor decisions are logged here, and so are would-be phone alerts: in v1 nothing is sent to your phone.'),
      filterBar('Filter log by level', options, counts, () => ui.logFilter, (v) => { ui.logFilter = v; draw(); }),
      box,
    ];
  }

  function alertText(r) {
    const msg = niceMinus(r.msg);
    if (r.lvl !== 'alert') return msg;
    const body = msg.replace(/^would-be phone alert:\s*/i, '');
    return [h('strong', { class: 'alert-tag' }, 'Would-be phone alert'), h('span', { class: 'sr-only' }, ': '), h('span', null, body)];
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

  function drawPower(w, edges, trades, value) {
    const H = w < 480 ? 220 : 240;
    const m = { t: 14, r: 62, b: 42, l: 44 };
    const pw = Math.max(80, w - m.l - m.r);
    const ph = H - m.t - m.b;
    const n = trades.length;
    const x = (i) => m.l + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
    const y = (v) => m.t + (1 - v) * ph;
    const svg = s('svg', {
      width: w, height: H, viewBox: `0 0 ${w} ${H}`, role: 'img', tabindex: '0',
      'aria-label': 'How often the gate passes a rule with a real edge, by number of trades in the test. Use the arrow keys to read each trade count.',
    });
    [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
      svg.append(s('line', { class: t === 0 ? 'c-zero' : 'c-grid', x1: m.l, x2: m.l + pw, y1: r1(y(t)), y2: r1(y(t)) }));
      svg.append(s('text', { class: 'c-tick', x: m.l - 8, y: r1(y(t) + 4), 'text-anchor': 'end' }, Math.round(t * 100) + '%'));
    });
    trades.forEach((tr, i) => svg.append(s('text', { class: 'c-tick', x: r1(x(i)), y: m.t + ph + 18, 'text-anchor': 'middle' }, fmtInt(tr))));
    svg.append(s('text', { class: 'c-label', x: r1(m.l + pw / 2), y: H - 4, 'text-anchor': 'middle' }, 'trades in the test'));
    const color = (k) => powerColor(k, edges.length);
    edges.forEach((e, k) => {
      const pts = trades.map((tr, i) => [x(i), value(e, tr)]).filter(([, v]) => v != null).map(([px, v]) => [px, y(v)]);
      if (!pts.length) return;
      const path = s('path', { class: 'c-pline', d: pts.map(([px, py], j) => `${j ? 'L' : 'M'}${r1(px)} ${r1(py)}`).join('') });
      path.style.stroke = color(k);
      svg.append(path);
      pts.forEach(([px, py]) => {
        const dot = s('circle', { class: 'c-pdot', cx: r1(px), cy: r1(py), r: 4 });
        dot.style.fill = color(k);
        svg.append(dot);
      });
    });
    const ends = edges.map((e, k) => ({ e, k, v: value(e, trades[n - 1]) })).filter((o) => o.v != null)
      .map((o) => Object.assign(o, { py: y(o.v) })).sort((a, b) => a.py - b.py);
    let lastY = -Infinity;
    for (const o of ends) {
      if (o.py - lastY < 13) continue;
      svg.append(s('text', { class: 'c-end-label', x: r1(x(n - 1) + 10), y: r1(o.py + 4) }, fmtTickR(o.e)));
      lastY = o.py;
    }
    const cross = s('line', { class: 'c-cross', y1: m.t, y2: m.t + ph, visibility: 'hidden' });
    const hit = s('rect', { class: 'c-hit', x: m.l - 16, y: 0, width: pw + 32, height: H });
    svg.append(cross, hit);
    const tip = tooltip();
    let current = -1;
    const show = (i) => {
      current = clamp(i, 0, n - 1);
      const px = r1(x(current));
      cross.setAttribute('x1', px);
      cross.setAttribute('x2', px);
      cross.setAttribute('visibility', 'visible');
      const rows = edges.map((e, k) => ({ e, k, v: value(e, trades[current]) })).filter((o) => o.v != null).sort((a, b) => b.e - a.e)
        .map((o) => h('div', { class: 'tip-row' }, h('span', { class: 'key-line', style: `--c: ${color(o.k)}` }),
          h('strong', null, fmtPct(o.v, 1)), h('span', { class: 'tip-lab' }, `${fmtTickR(o.e)} edge`)));
      tip.show([h('div', { class: 'tip-lab' }, `Pass rate with ${fmtInt(trades[current])} trades`)].concat(rows), px, m.t, w);
    };
    const hide = () => {
      current = -1;
      cross.setAttribute('visibility', 'hidden');
      tip.hide();
    };
    const fromPointer = (e) => {
      const box = svg.getBoundingClientRect();
      const rel = n === 1 ? 0 : ((e.clientX - box.left - m.l) / pw) * (n - 1);
      show(Math.round(rel));
    };
    hit.addEventListener('pointermove', fromPointer);
    hit.addEventListener('pointerdown', fromPointer);
    hit.addEventListener('pointerleave', hide);
    svg.addEventListener('keydown', (e) => chartKeys(e, current, n - 1, show, hide));
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

  function toast(kind, message, sticky = false) {
    let host = document.querySelector('.toasts');
    if (!host) {
      host = h('div', { class: 'toasts', 'aria-live': 'polite' });
      document.body.append(host);
    }
    while (host.children.length >= TOAST_LIMIT) host.firstElementChild.remove();
    const close = h('button', { type: 'button', class: 'toast-x', 'aria-label': 'Dismiss' }, icon('cross'));
    const node = h('div', { class: 'toast ' + kind, role: kind === 'error' || kind === 'warn' ? 'alert' : 'status' },
      icon(kind === 'error' || kind === 'warn' ? 'warn' : kind === 'ok' ? 'check' : 'info'), h('p', null, message), close);
    close.addEventListener('click', () => node.remove());
    host.append(node);
    if (kind !== 'error' && kind !== 'warn' && !sticky) setTimeout(() => node.remove(), 6000);
    return node;
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
