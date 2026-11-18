// Adapted from PR #467. Run only against isolated local builds without account configuration.
import { chromium } from '../../../web/node_modules/playwright/index.mjs';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const fixture = fileURLToPath(new URL('../../../tests/fixtures/issue_43_golden.kml', import.meta.url));
const origins = [process.env.BENCHMARK_BASE_ORIGIN, process.env.BENCHMARK_CANDIDATE_ORIGIN];
if (origins.some(origin => !origin || !['127.0.0.1', 'localhost'].includes(new URL(origin).hostname))) {
  throw new Error('Specify two isolated loopback origins with BENCHMARK_BASE_ORIGIN / BENCHMARK_CANDIDATE_ORIGIN');
}
const builds = [process.env.BENCHMARK_BASE_ID, process.env.BENCHMARK_CANDIDATE_ID];
if (builds.some(id => !id)) throw new Error('Specify exact source/build identifiers with BENCHMARK_BASE_ID / BENCHMARK_CANDIDATE_ID');
const repetitions = Number(process.env.BENCHMARK_REPETITIONS ?? 5);
if (!Number.isInteger(repetitions) || repetitions < 1) throw new Error('Invalid repetition count');
const counts = (process.env.BENCHMARK_PROJECT_COUNTS ?? '0,10').split(',').map(Number);
if (counts.some(count => !Number.isInteger(count) || count < 0)) throw new Error('Invalid Project count');
const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--no-sandbox'] });
const samples = [];
async function measure(variant, count, repetition) {
  const origin = origins[variant];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  try {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      const observer = new MutationObserver(() => {
        if (!window.startupReady && document.querySelector('.leaflet-control-zoom-in')
          && document.querySelector('input[type=file]:not(:disabled)') && !document.querySelector('.loading-screen')) {
          requestAnimationFrame(() => { window.startupReady ??= performance.now(); });
        }
      });
      observer.observe(document, { childList: true, subtree: true, attributes: true });
    });
    const cdp = await context.newCDPSession(page);
    await cdp.send('Network.enable');
if (count) {
 await page.goto(origin);
 await page.locator('.map-frame').waitFor({timeout:120000});
 await page.locator('input[type="file"]').setInputFiles(fixture);
 await page.getByRole('button',{name:'経路を確定',exact:true}).click();
 await page.getByLabel('DATE',{exact:true}).waitFor();
 await page.getByLabel('気象モード').selectOption('FTD');
 await page.getByLabel('DATE',{exact:true}).fill('2026-09-11');
 await page.getByLabel('ETD JST',{exact:true}).fill('09:00');
 for(const [name,altitude] of [['RJFM','6500'],['米ノ津','7500'],['玉名','6500']]){
  const input=page.getByLabel(`${name}出発Legの計画高度`,{exact:true});await input.fill(altitude);await input.blur();
 }
 await page.getByRole('button',{name:/NAV LOGを(?:作る|再計算)$/}).click();
 await page.locator('.nav-log-table').waitFor({timeout:120000});
 await page.getByRole('button',{name:'プロジェクトメニュー',exact:true}).click();
 await page.getByLabel('プロジェクト',{exact:true}).fill('Benchmark');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('status').filter({hasText:'プロジェクトを保存しました'}).waitFor();
 await page.evaluate(count=>new Promise((resolve,reject)=>{
  const open=indexedDB.open('autonavlog.projects');
  open.onsuccess=()=>{const db=open.result;const tx=db.transaction('projects','readwrite');const store=tx.objectStore('projects');const read=store.getAll();
   read.onsuccess=()=>{const template=read.result.find(x=>x.checkpoint && x.lastCalculation);if(!template){reject(new Error("Missing calculated Project template"));tx.abort();return;}store.clear();for(let i=0;i<count;i++){const row=structuredClone(template);row.id=crypto.randomUUID();row.token=crypto.randomUUID();row.draft.id=row.id;row.checkpoint.id=row.id;row.checkpoint.name='Benchmark '+i;row.draft.name=row.checkpoint.name;if(row.lastCalculation){row.lastCalculation.project.id=row.id;row.lastCalculation.outcome.project_id=row.id;}store.put(row)}};
   tx.oncomplete=()=>{db.close();sessionStorage.clear();resolve()};tx.onabort=()=>reject(tx.error)
  }
 }),count);
}

    for (const cache of ['cold', 'warm']) {
      if (cache === 'cold') await cdp.send('Network.clearBrowserCache');
      await page.goto(origin);
      await page.waitForFunction(() => window.startupReady, null, { timeout: 120_000 });
      if (errors.length) throw new Error(errors.join('\n'));
      const timing = await page.evaluate(() => ({
        fcp_ms: performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null,
        operable_ms: window.startupReady,
      }));
      const sample = { variant: variant ? 'candidate' : 'base', projects: count, repetition, cache, ...timing };
      samples.push(sample);
      console.log(JSON.stringify(sample));
    }
  } finally { await context.close(); }
}
try {
  for (const count of counts) {
    for (let repetition = 1; repetition <= repetitions; repetition++) {
      for (const variant of repetition % 2 ? [0, 1] : [1, 0]) await measure(variant, count, repetition);
    }
  }
  writeFileSync(process.argv[2] ?? '/tmp/startup-comparison.json', JSON.stringify({
    builds, browser: browser.version(), viewport: { width: 1280, height: 900 },
    method: 'Alternating variants; new context per variant/repetition; cold then warm; saved Projects include Last Calculation',
    samples,
  }, null, 2) + '\n');
} finally { await browser.close(); }
