import { clickMapCoordinate } from "./helpers/mapCoordinate";
import { test, expect } from "@playwright/test";
import { confirmImportedDraft } from "./helpers/importWorkflow";

const route = `<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>RJFM-RJFO</name><LineString><coordinates>131.4486111111,31.8772222222,0 131.5,32.4,0 131.65,33.1,0 131.7,33.4,0 131.7372222222,33.4794444444,0</coordinates></LineString></Placemark></Document></kml>`;
for (const width of [390, 820, 1100, 1240, 1241, 1440]) {
  test(`route planning keeps map, actions and inputs usable at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/");
    await expect(page.getByText("地図をクリックし、経路を作成してください", {exact:true})).toBeVisible({timeout:90_000});
    const map = page.locator(".map-frame"), pane = page.locator(".planning-pane");
    const boxes = async () => ({ map: (await map.boundingBox())!, pane: (await pane.boundingBox())! });
    let b = await boxes();
    if (width > 700) { expect(Math.abs(b.map.y - b.pane.y)).toBeLessThan(2); expect(b.map.x + b.map.width).toBeLessThanOrEqual(b.pane.x + 1); }
    else expect(b.map.y + b.map.height).toBeLessThanOrEqual(b.pane.y + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const drop = page.locator(".draft-import-controls .drop-zone");
    await expect(drop.locator(".file-picker-drop-description")).toHaveText("KML/KMZ をドロップ");
    await expect(drop.locator(".file-picker-drop-description")).toBeVisible();
    await expect(drop.locator("strong")).toBeHidden();
    await expect(drop.locator(".file-picker-label")).toHaveCSS("font-size", "11px");
    // Exercise the same component's non-compact presentation without changing
    // application state; restore Draft before file actions.
    await page.locator(".draft-import-controls").evaluate(el => el.classList.remove("draft-import-controls"));
    const normalDrop = page.locator(".drop-zone");
    await expect(normalDrop.locator("strong")).toHaveText("KML/KMZ をドロップ");
    await expect(normalDrop.locator("strong")).toBeVisible();
    await expect(normalDrop.locator(".file-picker-drop-description")).toBeHidden();
    await normalDrop.evaluate(el => el.parentElement!.classList.add("draft-import-controls"));
    const imports = await page.locator(".draft-import-controls > *").evaluateAll(elements => elements.map(e => ({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,y:e.getBoundingClientRect().y})));
    expect(Math.abs(imports[0]!.height - imports[1]!.height)).toBeLessThan(2);
    expect(Math.abs(imports[0]!.width - imports[1]!.width)).toBeLessThan(2);
    expect(Math.abs(imports[0]!.y - imports[1]!.y)).toBeLessThan(2);
    expect(imports[0]!.height).toBe(48);
    if(width>=1000) expect(b.pane.width).toBe(320);
    await page.locator('input[type="file"]').setInputFiles({name:"416.kml",mimeType:"application/vnd.google-earth.kml+xml",buffer:Buffer.from(route)});
    await expect(page.getByRole("list",{name:"経路リスト"}).locator("li")).toHaveCount(5);
    const draft = await page.getByRole("list",{name:"経路リスト"}).innerText();
    const view = () => page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!));
    const before = await view();
    await page.getByRole("button",{name:"地図を全画面表示",exact:true}).click();
    await expect(page.getByRole("dialog",{name:"全画面の経路地図"})).toBeVisible();
    await expect(map).toHaveCSS("position","fixed");
    await page.getByRole("button",{name:"地図の全画面表示を終了",exact:true}).press("Escape");
    await expect(page.getByRole("dialog",{name:"全画面の経路地図"})).toHaveCount(0);
    expect(await page.getByRole("list",{name:"経路リスト"}).innerText()).toBe(draft);
    const after = await view();
    expect(after.zoom).toBe(before.zoom);
    // Leaflet rounds the resized pixel origin. No intentional pan/zoom; allow one pixel.
    const degreesPerPixel = 360 / (256 * 2 ** before.zoom);
    expect(Math.abs(after.longitude - before.longitude)).toBeLessThan(degreesPerPixel);
    expect(Math.abs(after.latitude - before.latitude)).toBeLessThan(degreesPerPixel);
    await page.screenshot({path:info.outputPath(`draft-${width}.png`),fullPage:true});
    await confirmImportedDraft(page);
    await expect(page.locator(".timeline-stop")).toHaveCount(5);
    await expect(page.locator(".timeline-leg")).toHaveCount(4);
    await expect(page.locator(".point-index").first()).toHaveText("");
    await expect(page.locator(".point-index").first()).toHaveCSS("width","8px");
    await expect(page.locator(".route-name-edit").first()).toHaveCSS("border-width","0px");
    await expect(page.getByText("再計算後に表示",{exact:true})).toHaveCount(0);
    await expect(page.getByLabel("FROM",{exact:true})).toHaveValue(/RJFM/);
    await expect(page.getByLabel("TO",{exact:true})).toHaveValue(/RJFO/);
    await page.getByLabel("気象モード").selectOption("FTD");
    await page.getByLabel("DATE",{exact:true}).fill("2026-11-17");
    await page.getByLabel("ETD JST",{exact:true}).fill("09:00");
    await expect(page.getByLabel("ETD JST",{exact:true})).toHaveAttribute("type","text");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    b = await boxes();
    if (width > 700) expect(Math.abs(b.map.y - b.pane.y)).toBeLessThan(2);
    await page.screenshot({path:info.outputPath(`planning-${width}.png`),fullPage:true});
    await page.getByRole("button", {name:"経路を編集",exact:true}).click();
    await expect(page.getByRole("list",{name:"経路リスト"}).locator("li")).toHaveCount(5);
    await page.getByRole("button",{name:"地図を全画面表示",exact:true}).click();
    page.once("dialog", dialog => dialog.accept());
    // Simulate completion/cancellation delivered while the fullscreen map owns input.
    await page.getByRole("button",{name:"キャンセル",exact:true}).evaluate((button:HTMLButtonElement) => button.click());
    await expect(page.getByRole("dialog",{name:"全画面の経路地図"})).toHaveCount(0);
    await expect(page.locator("body")).not.toHaveCSS("overflow","hidden");
    await expect(page.getByLabel("DATE",{exact:true})).toHaveValue("2026-11-17");
    await page.screenshot({path:info.outputPath(`planning-${width}.png`),fullPage:true});
  });
}

test("per-Leg CPs retain distance order, reject a different Leg and preserve map on rename", async ({ page }, info) => {
  await page.setViewportSize({width:1440,height:950});
  await page.goto("/");
  await expect(page.getByText("地図をクリックし、経路を作成してください",{exact:true})).toBeVisible({timeout:90_000});
  await page.locator('input[type="file"]').setInputFiles({name:"416-cp.kml",mimeType:"application/vnd.google-earth.kml+xml",buffer:Buffer.from(route)});
  await confirmImportedDraft(page);
  const view = () => page.evaluate(() => JSON.parse(localStorage.getItem("autonavlog.map-viewport.v1.anonymous.last")!));
  const pick = async (lat:number, lon:number) => {
    const v = await view(), box = (await page.locator(".route-map").boundingBox())!;
    const project = (latitude:number, longitude:number) => { const scale=256*2**v.zoom, sine=Math.sin(latitude*Math.PI/180); return [scale*(longitude+180)/360,scale*(0.5-Math.log((1+sine)/(1-sine))/(4*Math.PI))]; };
    const p=project(lat,lon), c=project(v.latitude,v.longitude);
    await page.mouse.click(box.x+box.width/2+p[0]!-c[0]!,box.y+box.height/2+p[1]!-c[1]!);
  };
  const leg=page.locator(".timeline-leg").nth(1);
  for (const [label,lat,lon] of [["Far CP",32.9,131.61],["Near CP",32.6,131.54]] as const) {
    await leg.getByRole("button",{name:"2番目のLegへ地図からチェックポイントを追加"}).click();
    await pick(lat,lon);
    await expect(leg.getByRole("textbox",{name:/^名称/})).toBeFocused();
    await expect(page.getByRole("button",{name:/地図上の地点をクリック|地図から座標を選択/})).toHaveCount(0);
    await leg.getByRole("textbox",{name:/^名称/}).fill(label);
    await leg.getByRole("textbox",{name:/^名称/}).press("Enter");
    await expect(leg.getByText(label,{exact:true})).toBeVisible();
  }
  await expect(leg.locator(".checkpoint-item strong")).toHaveText(["Near CP","Far CP"]);
  const before=await view();
  await leg.getByRole("button",{name:"Near CPを編集",exact:true}).click();
  await leg.getByRole("textbox",{name:/^名称/}).fill("Near renamed");
  await leg.getByRole("textbox",{name:/^名称/}).press("Enter");
  await expect(leg.locator(".checkpoint-item strong")).toHaveText(["Near renamed","Far CP"]);
  expect(await view()).toEqual(before);
  await page.locator(".timeline-leg").first().getByRole("button",{name:"1番目のLegへ地図からチェックポイントを追加"}).click();
  await pick(33.25,131.68);
  await expect(page.getByText("選択したLegの範囲外です。地図で選び直すか、関連Legを選択してください。",{exact:true})).toBeVisible();
  await expect(page.locator(".checkpoint-form").getByRole("button",{name:"追加",exact:true})).toBeDisabled();
  const relatedLeg = page.locator(".checkpoint-form select");
  const option = await relatedLeg.locator('option').last().getAttribute('value');
  await relatedLeg.selectOption(option!);
  await expect(page.locator(".checkpoint-form").getByRole("textbox",{name:/^名称/})).toBeFocused();
  await page.getByRole("button",{name:"編集を閉じる",exact:true}).click();
  await page.screenshot({path:info.outputPath("planning-cps-1440.png"),fullPage:true});
});

test("#416 UI copy preview covers Draft, sources and CP controls", async ({page}, info) => {
  await page.setViewportSize({width:1440,height:950});
  await page.goto("/");
  await expect(page.getByText("地図をクリックし、経路を作成してください",{exact:true})).toBeVisible({timeout:90_000});
  await page.screenshot({path:info.outputPath("01-draft-empty-desktop.png"),fullPage:true});
  await page.locator('input[type="file"]').setInputFiles({name:"review-route.kml",mimeType:"application/vnd.google-earth.kml+xml",buffer:Buffer.from(route)});
  await expect(page.getByRole("list",{name:"経路リスト"}).locator("li")).toHaveCount(5);
  await page.screenshot({path:info.outputPath("02-draft-route-desktop.png"),fullPage:true});
  await page.setViewportSize({width:390,height:950});
  await page.screenshot({path:info.outputPath("03-draft-route-mobile.png"),fullPage:true});
  await page.setViewportSize({width:1440,height:950});
  await page.getByRole("button",{name:/^その他/}).click();
  await page.getByText("地図の出典",{exact:true}).click();
  await expect(page.getByText("必要な出典表示は地図上にも常時表示します。空域の出典は地図上の空域表示に付記します。",{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath("04-map-sources-menu.png"),fullPage:true});
  await page.keyboard.press("Escape");
  await confirmImportedDraft(page);
  await page.getByLabel("DATE",{exact:true}).fill("2026-11-17");
  await page.getByLabel("ETD JST",{exact:true}).fill("09:00");
    await expect(page.getByLabel("ETD JST",{exact:true})).toHaveAttribute("type","text");
  await page.getByLabel("気象モード").selectOption("FTD");
  await page.screenshot({path:info.outputPath("05-planning-inputs-desktop.png"),fullPage:true});
  await page.locator(".timeline-leg").nth(1).getByRole("button",{name:"2番目のLegへ地図からチェックポイントを追加"}).click();
  await expect(page.locator(".checkpoint-form")).toBeVisible();
  await page.screenshot({path:info.outputPath("06-checkpoint-add-desktop.png"),fullPage:true});
  await page.getByRole("button",{name:"編集を閉じる",exact:true}).click();
  await page.setViewportSize({width:390,height:950});
  await page.screenshot({path:info.outputPath("07-planning-mobile.png"),fullPage:true});
});


test("pending KMZ import cannot enter fullscreen and hide document selection", async ({ page }) => {
  const { execFileSync } = await import("node:child_process");
  const bytes = execFileSync("python3", ["-c", "import io,zipfile,sys; b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); s=sys.stdin.read(); z.writestr('a.kml',s); z.writestr('b.kml',s); z.close(); sys.stdout.buffer.write(b.getvalue())"], {input: route});
  await page.goto("/");
  const full = page.getByRole("button", {name:"地図を全画面表示",exact:true});
  await expect(full).toBeEnabled({timeout:90_000});
  await page.evaluate(() => {
    const original = File.prototype.arrayBuffer;
    File.prototype.arrayBuffer = async function () {
      File.prototype.arrayBuffer = original;
      await new Promise<void>(resolve => Object.assign(window, { releaseImportRead: resolve }));
      return original.call(this);
    };
  });
  await page.locator('input[type="file"]').setInputFiles({name:"delayed.kmz",mimeType:"application/vnd.google-earth.kmz",buffer:bytes});
  await expect(full).toBeDisabled();
  await page.evaluate(() => (window as unknown as {releaseImportRead:()=>void}).releaseImportRead());
  const selection = page.getByLabel("KML文書");
  await expect(selection).toBeVisible();
  await expect(page.getByRole("dialog", {name:"全画面の経路地図"})).toHaveCount(0);
  await selection.selectOption("b.kml");
  await page.getByRole("button",{name:"選択したKMLを読み込む"}).click();
  await expect(page.getByRole("list",{name:"経路リスト"}).locator("li")).toHaveCount(5);
  await expect(full).toBeEnabled();
});


test("resumed unsaved CP accepts a direct new map pick without an activation button", async ({page}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", {name:"経路作成",exact:true})).toBeVisible({timeout:90_000});
  await page.locator('input[type="file"]').setInputFiles({name:"resume.kml",mimeType:"application/vnd.google-earth.kml+xml",buffer:Buffer.from(route)});
  await confirmImportedDraft(page);
  await page.getByRole("button",{name:"2番目のLegへ地図からチェックポイントを追加",exact:true}).click();
  await clickMapCoordinate(page,32.6,131.54);
  await page.locator(".checkpoint-form").getByRole("textbox",{name:/^名称/}).fill("Resume CP");
  const draft=()=>page.evaluate(()=>JSON.parse(sessionStorage.getItem("autonavlog.working-session.v1")!).checkPointDraft);
  await expect.poll(async()=>(await draft()).name).toBe("Resume CP");
  const before=await draft();
  await page.reload();
  await page.getByRole("button",{name:"チェックポイントの編集を続ける",exact:true}).click({timeout:90_000});
  expect(await draft()).toEqual(before);
  await expect(page.getByRole("button",{name:/地図から座標を選択|地図上の地点をクリック/})).toHaveCount(0);
  await clickMapCoordinate(page,32.9,131.61);
  await expect(page.locator(".checkpoint-form").getByRole("textbox",{name:/^名称/})).toBeFocused();
  await expect.poll(async()=>Number((await draft()).latitude)).toBeCloseTo(32.9,2);
  expect((await draft()).linkedSectionId).toBe(before.linkedSectionId);
  await page.locator(".checkpoint-form").getByRole("button",{name:"追加",exact:true}).click();
  await expect(page.getByText("Resume CP",{exact:true})).toBeVisible();
});

for (const width of [390, 1440]) test(`24h ETD dial confirms, cancels and preserves direct input at ${width}px`, async ({page}) => {
  await page.setViewportSize({width,height:950});
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'経路作成',exact:true})).toBeVisible({timeout:120000});
  await page.locator('input[type=file]').setInputFiles({name:'dial.kml',mimeType:'application/vnd.google-earth.kml+xml',buffer:Buffer.from(route)});
  await confirmImportedDraft(page);
  const input=page.getByLabel('ETD JST',{exact:true});
  const trigger=page.getByRole('button',{name:'ETD を時計で選択',exact:true});
  await input.fill('09:17');await trigger.click();
  const dialog=page.getByRole('dialog',{name:'ETD JST の時刻選択',exact:true});
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button',{name:'23時',exact:true}).click();
  await dialog.getByRole('button',{name:'55分',exact:true}).click();
  await dialog.getByLabel('ETD の分',{exact:true}).fill('58');
  await dialog.getByRole('button',{name:'キャンセル',exact:true}).click();
  await expect(input).toHaveValue('09:17');await expect(trigger).toBeFocused();
  await trigger.click();await dialog.getByRole('button',{name:'00時',exact:true}).click();
  await dialog.getByLabel('ETD の分',{exact:true}).fill('03');
  await dialog.getByRole('button',{name:'確定',exact:true}).click();
  await expect(input).toHaveValue('00:03');await expect(trigger).toBeFocused();
  await trigger.click();await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
  await expect(input).toHaveValue('00:03');await expect(trigger).toBeFocused();
  await input.fill('12:00');await trigger.click();
  await dialog.getByRole('button',{name:'12時',exact:true}).focus();
  await page.keyboard.press('ArrowRight');await page.keyboard.press('Enter');
  await expect(dialog.getByLabel('ETD の時',{exact:true})).toHaveValue('13');
  await expect(dialog.getByRole('button',{name:'00分',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowRight');await page.keyboard.press('Space');
  await expect(dialog.getByLabel('ETD の分',{exact:true})).toHaveValue('0');
  for (let i=0;i<8 && !await dialog.getByRole('button',{name:'確定',exact:true}).evaluate(e=>e===document.activeElement);i++) await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button',{name:'確定',exact:true})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(input).toHaveValue('13:00');
  for (const key of ['Enter', 'Space']) {
    await input.fill('09:17'); await trigger.click();
    await dialog.getByRole('button', {name:'09時',exact:true}).focus();
    await page.keyboard.press(key);
    await expect(dialog.getByRole('button', {name:'15分',exact:true})).toBeFocused();
    await expect(dialog.getByLabel('ETD の分',{exact:true})).toHaveValue('17');
    await page.keyboard.press(key);
    await expect(dialog.getByLabel('ETD の分',{exact:true})).toHaveValue('15');
    await dialog.getByRole('button',{name:'確定',exact:true}).click();
    await expect(input).toHaveValue('09:15');
  }
  await input.fill('23:59');await expect(input).toHaveValue('23:59');
  await expect(page.getByRole('heading',{name:'確定済み経路',exact:true})).toHaveCount(0);
  await expect(page.getByRole('region',{name:'確定済み経路',exact:true})).toBeVisible();
});
