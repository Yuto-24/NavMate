import { openProjectMenu } from "./helpers/header";
import { test, expect } from '@playwright/test';
for (const width of [390, 1100, 1440]) {
  test(`ordinary App error does not move viewport or workflow at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 600});
    await page.goto('/e2e/notification-harness/index.html');
    const trigger = page.getByRole('button', {name:'Test: invalid route'});
    await expect(trigger).toBeEnabled({timeout:120000});
    // Establish focus before measuring: native focus navigation is not a Toast effect.
    await trigger.evaluate(element => element.focus({preventScroll:true}));
    await page.evaluate(() => scrollTo({top:150, behavior:'instant'}));
    const geometry = () => page.evaluate(() => ({y:scrollY, height:document.documentElement.scrollHeight,
      workspace:document.querySelector('.app-workspace')!.getBoundingClientRect().toJSON()}));
    const before = await geometry();
    for (let i=0;i<2;i++) {
      await trigger.click();
      const notification = page.locator('.app-notification');
      await expect(notification).toBeVisible();
      await expect(notification).toHaveAttribute('role','alert');
      expect(await geometry()).toEqual(before);
      const r=await notification.boundingBox();
      expect(r!.x).toBeGreaterThanOrEqual(0);
      expect(r!.x+r!.width).toBeLessThanOrEqual(width);
      expect(r!.y).toBeGreaterThanOrEqual(56);
      await notification.getByRole('button',{name:'メッセージを閉じる'}).click();
      await expect(notification).toHaveCount(0);
      expect(await geometry()).toEqual(before);
    }
    await trigger.click();
    const notification = page.locator('.app-notification');
    await expect(notification).toBeVisible();
      await page.getByRole('button', {name:'アカウント（未ログイン）'}).click();
      await expect(page.getByRole('dialog', {name:'アカウント', exact:true})).toBeVisible();
      expect(await notification.evaluate(el => { const r=el.getBoundingClientRect(); return !!document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('.modal-backdrop'); })).toBe(true);
      await page.getByRole('button', {name:'アカウントを閉じる'}).click();
  });
}

test('auth toast expires at five seconds, keeps retry in account dialog, and restarts for a new notice', async ({page}) => {
 await page.clock.install();
 await page.goto('/e2e/notification-harness/account.html');
 await page.getByRole('button',{name:'Test: notify',exact:true}).click();
 const toast=page.locator('.account-notification');
 await expect(toast).toBeVisible();
 await page.clock.fastForward(4000);
 await expect(toast).toBeVisible();
 await page.getByRole('button',{name:'Test: newer notice'}).click();
 await page.clock.fastForward(4000);
 await expect(toast).toContainText('Test: newer failure');
 await page.clock.fastForward(1100);
 await expect(toast).toHaveCount(0);
 await page.getByRole('button',{name:'アカウント（未ログイン）'}).click();
 const dialog=page.getByRole('dialog',{name:'アカウント',exact:true});
 await expect(dialog).toContainText('Test: newer failure');
 await expect(dialog.getByRole('button',{name:'ログアウトを再試行'})).toBeEnabled();
 await dialog.getByRole('button',{name:'ログアウトを再試行'}).click();
 await expect(dialog.getByRole('button',{name:'Googleでログイン'})).toBeVisible();
 await page.getByRole('button',{name:'アカウントを閉じる'}).click();
 await page.getByRole('button',{name:'Test: notify',exact:true}).click();
 await expect(toast).toBeVisible();
 await toast.getByRole('button',{name:'メッセージを閉じる'}).click();
 await expect(toast).toHaveCount(0);
 await page.getByRole('button',{name:'アカウント（未ログイン）'}).click();
 await expect(dialog).toContainText('Test: sign-out failed');
 await expect(dialog.getByRole('button',{name:'ログアウトを再試行'})).toBeEnabled();
});

test('App toast expires without losing failure details and repeated failures restart it', async ({page}) => {
 await page.clock.install();
 await page.goto('/e2e/notification-harness/index.html');
 const trigger=page.getByRole('button',{name:'Test: invalid route'});
 await expect(trigger).toBeEnabled({timeout:120000});
 await trigger.click();
 const toast=page.locator('.app-notification');
 await expect(toast).toBeVisible();
 const message=await toast.locator('span').innerText();
 await page.clock.fastForward(4000);
 await expect(toast).toBeVisible();
 await page.clock.fastForward(1100);
 await expect(toast).toHaveCount(0);
 await page.getByRole('button',{name:/^その他/}).click();
 await expect(page.locator('#operation-messages')).toContainText(message);
 await page.getByRole('button',{name:/^その他/}).click();
 await trigger.click();
 await expect(toast).toContainText(message);
 await page.clock.fastForward(5100);
 await expect(toast).toHaveCount(0);
});

test('unrelated operation failures survive, successful import clears only import failure', async ({page}) => {
 await page.clock.install();
 await page.goto('/e2e/notification-harness/index.html?fail-new=1');
 const invalid=page.getByRole('button',{name:'Test: invalid route'});
 await expect(invalid).toBeEnabled({timeout:120000});
 await invalid.click();
 const importError=await page.locator('.app-notification span').innerText();
 await page.getByRole('button',{name:'新規',exact:true}).click();
 await expect(page.locator('.app-notification')).toContainText('Test: new work failed');
 await page.clock.fastForward(5100);
 await page.getByRole('button',{name:/^その他/}).click();
 await expect(page.locator('#operation-messages')).toContainText(importError);
 await expect(page.locator('#operation-messages')).toContainText('Test: new work failed');
 await page.getByRole('button',{name:/^その他/}).click();
 await page.getByRole('button',{name:'Test: valid route'}).click();
 await expect(page.locator('.app-notification')).toContainText('経路候補を読み込みました');
 await page.clock.fastForward(5100);
 await page.getByRole('button',{name:/^その他/}).click();
 await expect(page.locator('#operation-messages')).not.toContainText(importError);
 await expect(page.locator('#operation-messages')).toContainText('Test: new work failed');
});

test('sync notices and independent undo failures remain inspectable after five seconds; Undo lasts ten', async ({page}) => {
 await page.clock.install();
 await page.goto('/e2e/notification-harness/sync.html');
 await page.getByRole('button',{name:'Test: notify',exact:true}).click();
 const undo=page.locator('.sync-undo');
 await undo.getByRole('button',{name:'元に戻す'}).nth(0).click();
 await undo.getByRole('button',{name:'元に戻す'}).nth(1).click();
 await expect(page.locator('.app-notification').last()).toContainText('Test: undo B failed');
 await page.clock.fastForward(5100);
 await expect(page.locator('.app-notification')).toHaveCount(0);
 await expect(undo.getByRole('button',{name:'元に戻す'})).toHaveCount(2);
 await page.getByRole('button',{name:'アカウント（未ログイン）'}).click();
 const dialog=page.getByRole('dialog',{name:'アカウント',exact:true});
 for(const text of ['Test: sync offline','Test: undo A failed','Test: undo B failed']) await expect(dialog).toContainText(text);
 await page.getByRole('button',{name:'アカウントを閉じる'}).click();
 await page.getByRole('button',{name:'Test: allow retry'}).click();
 await undo.getByRole('button',{name:'元に戻す'}).nth(0).click();
 await page.getByRole('button',{name:'アカウント（未ログイン）'}).click();
 await expect(dialog).not.toContainText('Test: undo A failed');
 await expect(dialog).toContainText('Test: undo B failed');
 await expect(dialog).toContainText('Test: sync offline');
 await page.getByRole('button',{name:'アカウントを閉じる'}).click();
 await page.getByRole('button',{name:'Test: sync recovered'}).click();
 await page.clock.fastForward(5000);
 await expect(undo).toHaveCount(0);
 await page.getByRole('button',{name:'アカウント（未ログイン）'}).click();
 await expect(dialog).not.toContainText('Test: sync offline');
 await expect(dialog).toContainText('Test: undo B failed');
});

test('cancelled load retains its earlier failure until a successful load', async ({page}) => {
 await page.goto('/e2e/notification-harness/index.html?fail-load=1');
 await page.getByRole('button',{name:'Test: valid route'}).click();
 await page.getByRole('button',{name:'経路を確定',exact:true}).click();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await openProjectMenu(page);
 const saved=page.getByLabel('保存済み',{exact:true});
 await expect(saved.locator('option')).not.toHaveCount(1);
 const id=await saved.locator('option').last().getAttribute('value');
 await saved.selectOption(id!);
 await openProjectMenu(page);
 await page.getByRole('button',{name:'保存済みプロジェクトを開く',exact:true}).click();
 await expect(page.locator('.app-notification')).toContainText('Test: load failed');
 await openProjectMenu(page);
 await page.getByRole('button',{name:'保存済みプロジェクトを開く',exact:true}).click();
 await page.getByRole('button',{name:/^その他/}).click();
 await expect(page.locator('#operation-messages')).toContainText('Test: load failed');
 await page.getByRole('button',{name:/^その他/}).click();
 await openProjectMenu(page);
 page.once('dialog',dialog=>dialog.accept());
 await openProjectMenu(page);
 await page.getByRole('button',{name:'保存済みプロジェクトを開く',exact:true}).click();
 await page.getByRole('button',{name:/^その他/}).click();
 await expect(page.locator('#operation-messages')).not.toContainText('Test: load failed');
});


test('successful Header source-link retry clears only the resolved failure', async ({page}) => {
 await page.goto('/e2e/notification-harness/index.html?fail-link=1&fail-new=1');
 await page.getByRole('button',{name:'Test: invalid route'}).waitFor();
 await page.getByRole('button',{name:'新規',exact:true}).click();
 await expect(page.locator('.app-notification')).toContainText('Test: new work failed');
 await page.getByRole('button',{name:/^その他/}).click();
 await page.locator('.map-source-details summary').click();
 const link=page.locator('.map-source-details').getByRole('link',{name:'OpenStreetMap contributors',exact:true});
 await link.click();
 await expect(page.locator('#operation-messages')).toContainText('Test: source link failed');
 await link.click();
 await expect(page.locator('#operation-messages')).not.toContainText('Test: source link failed');
 await expect(page.locator('#operation-messages')).toContainText('Test: new work failed');
});


for(const mode of ['denied','empty','kmz']) test(`unfinished ${mode} import preserves the previous failure`, async ({page}) => {
 await page.goto('/e2e/notification-harness/index.html?pending-import='+mode);
 await page.getByRole('button',{name:'Test: invalid route'}).click();
 await expect(page.locator('.app-notification')).toBeVisible();
 const error=await page.locator('.app-notification span').first().innerText();
 if(mode==='kmz') await page.locator('input[type=file]').setInputFiles({name:'pending.kmz',mimeType:'application/vnd.google-earth.kmz',buffer:Buffer.from('synthetic')});
 else await page.getByRole('button',{name:'Google Earth からペースト',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:mode==='kmz'?'KMZ内のKMLを選択':'KML/XMLを貼り付け',exact:true});
 await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'キャンセル',exact:true}).click();
 await page.getByRole('button',{name:/^その他/}).click();
 await expect(page.locator('#operation-messages')).toContainText(error);
});

test('opening account history does not duplicate live provider announcements', async ({page}) => {
 await page.clock.install();
 await page.goto('/e2e/notification-harness/account.html');
 await page.getByRole('button',{name:'Test: notify',exact:true}).click();
 await page.getByRole('button',{name:'アカウント（未ログイン）'}).click();
 await expect(page.getByRole('alert')).toHaveCount(1);
 await expect(page.getByRole('dialog',{name:'アカウント',exact:true}).getByText('Test: sign-out failed',{exact:true})).toBeVisible();
 await page.clock.fastForward(5100);
 await expect(page.getByRole('alert')).toHaveCount(0);
 await expect(page.getByRole('dialog',{name:'アカウント',exact:true})).toContainText('Test: sign-out failed');
});

test('committed route failure focuses planning once; unrelated failure does not steal focus or scroll', async ({page}) => {
 await page.goto('/e2e/notification-harness/index.html?committed-focus');
 await page.getByRole('button',{name:'Test: valid route',exact:true}).click();
 await page.getByRole('button',{name:'経路を確定',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('Test: committed route failure');
 await expect(page.locator('.input-rail input').first()).toBeFocused();
 const save=page.getByRole('button',{name:'保存',exact:true});
 await page.locator('.route-map').focus();
 const before=await page.evaluate(()=>scrollY);
 await save.evaluate((button:HTMLButtonElement)=>button.click());
 await expect(page.getByRole('alert')).toContainText('Test: unrelated save failure');
 await expect(page.locator('.route-map')).toBeFocused();
 expect(await page.evaluate(()=>scrollY)).toBe(before);
});
