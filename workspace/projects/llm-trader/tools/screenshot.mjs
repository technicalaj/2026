#!/usr/bin/env node
// Usage: node tools/screenshot.mjs [--state tests/fixtures/sample_state.json] [--out out/screens] [--agent rule_id]
import { createRequire } from 'node:module';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = path.join(ROOT, 'llm_trader', 'ui', 'index.html');
const TABS = ['team', 'agents', 'checks', 'risk', 'approvals', 'report', 'log'];
const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
];
const THEMES = ['light', 'dark'];

function parseArgs(argv) {
  const args = { state: 'tests/fixtures/sample_state.json', out: 'out/screens', agent: null };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i].replace(/^--/, '');
    if (!(key in args) || i + 1 >= argv.length) throw new Error(`Unknown or incomplete option: ${argv[i]}`);
    args[key] = argv[++i];
  }
  return args;
}

function loadPlaywright() {
  try {
    return require('playwright');
  } catch {
    console.error('Playwright is not installed. Run: npm install -g playwright && npx playwright install chromium');
    process.exit(2);
  }
}

function pickAgent(state) {
  const research = Array.isArray(state.research) ? state.research : [];
  const bar = state.meta?.accuracy_bar ?? 0.8;
  const trap = research.find((r) => r.gate?.status === 'failed' && (r.windows?.holdout?.win_rate ?? 0) >= bar);
  return (trap || research[0] || {}).rule_id || null;
}

const slug = (id) => String(id).replace(/[^a-zA-Z0-9_-]/g, '-');

const settle = (page) => page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));

async function checkPage(page, label, problems) {
  const found = await page.evaluate(() => {
    const doc = document.documentElement;
    const over = doc.scrollWidth - doc.clientWidth;
    const clipped = (el) => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        if (getComputedStyle(p).overflowX !== 'visible') return true;
      }
      return false;
    };
    const wide = [];
    if (over > 0) {
      for (const el of document.querySelectorAll('body *')) {
        const box = el.getBoundingClientRect();
        if (box.width && box.right > doc.clientWidth + 1 && !clipped(el)) wide.push(`${el.tagName.toLowerCase()}.${String(el.className.baseVal ?? el.className).trim().replace(/\s+/g, '.')}`);
        if (wide.length >= 6) break;
      }
    }
    const enabled = [...document.querySelectorAll('.action')].filter((b) => !b.disabled).length;
    const emptyCharts = [...document.querySelectorAll('.chart')].filter((c) => c.offsetParent && !c.querySelector('svg')).length;
    return { over, wide, enabled, emptyCharts };
  });
  if (found.over > 0) problems.push(`${label}: page scrolls sideways by ${found.over}px (${found.wide.join(', ')})`);
  if (found.enabled) problems.push(`${label}: ${found.enabled} action button(s) enabled in snapshot mode`);
  if (found.emptyCharts) problems.push(`${label}: ${found.emptyCharts} visible chart(s) did not draw`);
}

async function shootAgent(page, agent, label, outDir, problems) {
  const toggle = page.locator(`button[aria-controls="ra-${slug(agent)}-details"]`);
  if (!(await toggle.count())) {
    problems.push(`${label}: no expandable agent "${agent}"`);
    return null;
  }
  await page.evaluate(() => { location.hash = 'agents'; });
  await toggle.click();
  const details = page.locator(`#ra-${slug(agent)}-details`);
  await details.waitFor({ state: 'visible' });
  const equity = details.locator('.chart svg').first();
  await equity.waitFor();
  // A sticky bar would be stitched into a tall capture, so pin it in place for this shot only.
  await page.addStyleTag({ content: '.tabs-bar { position: static !important; }' });
  await equity.scrollIntoViewIfNeeded();
  await settle(page);
  const box = await equity.boundingBox();
  if (box) await page.mouse.move(box.x + box.width * 0.62, box.y + box.height * 0.5);
  await settle(page);
  await checkPage(page, `agent ${label}`, problems);
  const card = page.locator('article.ra', { has: details });
  const clip = await card.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
  });
  const file = path.join(outDir, `agent-${slug(agent)}-${label}.png`);
  await page.screenshot({ path: file, fullPage: true, clip });
  return file;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const state = JSON.parse(await readFile(path.resolve(ROOT, args.state), 'utf8'));
  const agent = args.agent || pickAgent(state);
  const outDir = path.resolve(ROOT, args.out);
  await mkdir(outDir, { recursive: true });
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const problems = [];
  const files = [];
  try {
    for (const theme of THEMES) {
      for (const vp of VIEWPORTS) {
        const label = `${vp.name}-${theme}`;
        const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, colorScheme: theme });
        await context.addInitScript((data) => { window.__STATE__ = data; }, state);
        const page = await context.newPage();
        page.on('console', (msg) => {
          if (msg.type() === 'error' || msg.type() === 'warning') problems.push(`${label}: console ${msg.type()}: ${msg.text()}`);
        });
        page.on('pageerror', (err) => problems.push(`${label}: page error: ${err.message}`));
        await page.goto(pathToFileURL(PAGE).href);
        await page.waitForSelector('html[data-ready="true"]', { timeout: 10000 });
        for (const tab of TABS) {
          await page.evaluate((t) => { location.hash = t; }, tab);
          await page.waitForSelector(`#panel-${tab}:not([hidden])`);
          await settle(page);
          await checkPage(page, `${tab} ${label}`, problems);
          const file = path.join(outDir, `${tab}-${label}.png`);
          await page.screenshot({ path: file, fullPage: true });
          files.push(file);
        }
        if (agent) {
          const file = await shootAgent(page, agent, label, outDir, problems);
          if (file) files.push(file);
        }
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  for (const file of files) console.log(path.relative(ROOT, file));
  if (problems.length) {
    console.error(`\n${problems.length} problem(s):\n- ${problems.join('\n- ')}`);
    process.exit(1);
  }
  console.log(`\n${files.length} screenshots, no problems found.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
