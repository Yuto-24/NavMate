import { chromium } from '../../../web/node_modules/playwright/index.mjs';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const fixture=fileURLToPath(new URL('../../../tests/fixtures/issue_43_golden.kml',import.meta.url));
const browser = await chromium.launch({headless:true, channel:'chrome', args:['--no-sandbox']});
const origin=process.env.BENCHMARK_ORIGIN??'http://127.0.0.1:4178/';
const context = await browser.newContext({viewport:{width:1440,height:1000}});
const page = await context.newPage();
page.on('pageerror', e=>console.error(e.message));
await page.addInitScript(() => {
 window.startupRequests=[];
 const Original=window.Worker;
 window.Worker=class extends Original {
  constructor(...args){super(...args);const starts=new Map();
   const post=this.postMessage.bind(this);
   this.postMessage=(message,...rest)=>{if(message.type==='APPLY')starts.set(message.id,{operation:message.argumentList?.[0]?.value,start:performance.now()});return post(message,...rest)};
   this.addEventListener('message',event=>{const start=starts.get(event.data.id);if(start){window.startupRequests.push({...start,end:performance.now()});starts.delete(event.data.id)}});
  }
 };
 const observer=new MutationObserver(()=>{if(!window.startupReady&&document.querySelector('.leaflet-control-zoom-in') && document.querySelector('input[type=file]:not(:disabled)')&& !document.querySelector('.loading-screen'))window.startupReady=performance.now()});
 observer.observe(document,{childList:true,subtree:true});
});
const cdp=await context.newCDPSession(page);
await cdp.send('Network.enable');
const samples=[];
const count=Number(process.argv[3]??0);
if(count){
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
   read.onsuccess=()=>{const template=read.result.find(x=>x.checkpoint);store.clear();for(let i=0;i<count;i++){const row=structuredClone(template);row.id=crypto.randomUUID();row.token=crypto.randomUUID();row.draft.id=row.id;row.checkpoint.id=row.id;row.checkpoint.name='Benchmark '+i;row.draft.name=row.checkpoint.name;if(row.lastCalculation){row.lastCalculation.project.id=row.id;row.lastCalculation.outcome.project_id=row.id;}store.put(row)}};
   tx.oncomplete=()=>{db.close();sessionStorage.clear();resolve()};tx.onabort=()=>reject(tx.error)
  }
 }),count);
}
for(let i=0;i<6;i++){
 const cold=i%2===0;
 if(cold) await cdp.send('Network.clearBrowserCache');
 await page.goto(origin);
 await page.waitForFunction(()=>window.startupReady,{timeout:120000});
 const stats=await page.evaluate(()=>({ready:window.startupReady,marks:performance.getEntriesByType('mark').map(x=>({name:x.name,start:x.startTime})),paint:performance.getEntriesByType('paint').map(x=>({name:x.name,start:x.startTime})),requests:window.startupRequests,resources:performance.getEntriesByType('resource').filter(x=>!x.name.includes('tile')).map(x=>({name:x.name,duration:x.duration,bytes:x.transferSize}))}));
 const workers=await Promise.all(page.workers().map(w=>w.evaluate(()=>performance.getEntriesByType('mark').map(x=>({name:x.name,start:x.startTime})))));
 samples.push({cold,...stats,workers});
 console.log(JSON.stringify({i,cold,ready:stats.ready,paint:stats.paint,requests:stats.requests,workers}));
}
writeFileSync(process.argv[2]??'/tmp/startup-benchmark.json',JSON.stringify({browser:browser.version(),count,samples},null,2));
await browser.close();
