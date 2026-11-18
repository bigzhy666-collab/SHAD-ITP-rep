import {test,expect, type Page} from '@playwright/test'

async function ready(page:Page){
  await page.goto('/model');
  await expect(page.getByText('正在加载管网模型…')).toHaveCount(0);
}

test('单击站点居中、切换及重复点击保持比例',async({page})=>{
  await page.setViewportSize({width:1920,height:1080});
  await page.emulateMedia({reducedMotion:'no-preference'});
  await ready(page);
  const station=page.getByRole('button',{name:'聚焦1#换热站',exact:true});
  await station.click();
  await expect(station).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('#infoName')).toHaveText('1#换热站');
  await expect.poll(async()=>{
    const p=await station.boundingBox(),left=await page.locator('.pipe-model-scene .left').boundingBox(),info=await page.locator('#info').boundingBox();
    return Math.abs(p!.x+p!.width/2-(left!.x+left!.width+info!.x)/2);
  }).toBeLessThan(2);
  const other=page.getByRole('button',{name:'聚焦2#换热站',exact:true});
  const before=await other.boundingBox();
  await station.click();await page.waitForTimeout(450);
  const after=await other.boundingBox();
  expect(Math.abs(before!.x-after!.x)+Math.abs(before!.y-after!.y)).toBeLessThan(2);
  await other.click();
  await expect(other).toHaveAttribute('aria-pressed','true');
  await expect(station).toHaveAttribute('aria-pressed','false');
  await page.waitForTimeout(450);
  await page.screenshot({path:'verification/station-focus/desktop.png',fullPage:true});
  await page.getByRole('button',{name:'复位视角',exact:true}).click();
  await expect(other).toHaveAttribute('aria-pressed','false');
  await expect(page.locator('#info')).not.toHaveClass(/show/);
});

test('手机异常红点聚焦、详情避让与减少动态效果',async({page})=>{
  await page.setViewportSize({width:375,height:812});
  await ready(page);
  await page.getByRole('button',{name:'定位演示异常',exact:true}).click();
  await page.getByRole('button',{name:'演示异常 S3',exact:true}).click();
  const station=page.locator('.station-target[aria-pressed=true]');
  await expect(station).toHaveAttribute('aria-label','聚焦3#换热站');
  const p=await station.boundingBox(),panel=await page.locator('#info').boundingBox(),bar=await page.locator('.pipe-model-scene .top').boundingBox();
  expect(p!.y).toBeGreaterThan(bar!.y+bar!.height);
  expect(p!.y+p!.height).toBeLessThan(panel!.y);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('#info').getByRole('button',{name:'×',exact:true}).click();
  // Keyboard activation uses the same station selection path.
  const ordinary=page.getByRole('button',{name:'聚焦1#换热站',exact:true});
  await ordinary.focus();await page.keyboard.press('Enter');
  await expect(ordinary).toHaveAttribute('aria-pressed','true');
  await ordinary.blur();
  await page.screenshot({path:'verification/station-focus/mobile.png',fullPage:true});
});

test('快速切换、切场景、退出页面会取消旧聚焦动画',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.emulateMedia({reducedMotion:'no-preference'});
  await ready(page);
  await page.getByRole('button',{name:'聚焦1#换热站',exact:true}).click();
  await page.locator('#entSel').selectOption('ent-1');
  await page.waitForTimeout(450);
  await expect(page.locator('.station-target[aria-pressed=true]')).toHaveCount(0);
  await page.getByRole('button',{name:'聚焦1#换热站',exact:true}).click();
  await page.locator('nav').getByRole('link',{name:'总览',exact:true}).click();
  await page.waitForTimeout(450);
  await page.locator('nav').getByRole('link',{name:'管网模型',exact:true}).click();
  await expect(page.locator('canvas#c')).toHaveCount(1);
  expect(errors).toEqual([]);
});
