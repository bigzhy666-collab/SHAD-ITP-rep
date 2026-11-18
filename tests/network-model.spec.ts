import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
const heat=JSON.parse(readFileSync(new URL('../src/model/heat.json',import.meta.url),'utf8'))

test('运行指标与图例在矮窗口中不重叠，指标可以滚动查看',async({page})=>{
 await page.goto('/model');await expect(page.getByText('正在加载管网模型…')).toHaveCount(0);
 for(const size of [{width:1920,height:1080},{width:1366,height:768},{width:1024,height:700},{width:768,height:700}]){
  await page.setViewportSize(size);
  const metrics=page.locator('.model-panels .left'),legend=page.locator('#legend');
  await expect(metrics).toBeVisible();await expect(legend).toBeVisible();
  const a=await metrics.boundingBox(),b=await legend.boundingBox();
  expect(a!.y+a!.height+8).toBeLessThanOrEqual(b!.y);
  await metrics.evaluate(e=>e.scrollTop=e.scrollHeight);
  const last=await metrics.locator('.kpi').last().boundingBox();
  expect(last!.y+last!.height).toBeLessThanOrEqual(a!.y+a!.height+1);
  await metrics.evaluate(e=>e.scrollTop=0);
 }
 await page.screenshot({path:'verification/network-model/panels-no-overlap.png'});
 await page.setViewportSize({width:375,height:812});
 await expect(page.locator('.model-panels .left')).toBeHidden();await expect(page.locator('#legend')).toBeVisible();
});
test('模型首页、时序告警、对象详情与页面恢复',async({page})=>{const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:1920,height:1080});await page.goto('/');await expect(page).toHaveURL(/\/model$/);await expect(page.locator('.nav-item').first()).toHaveText('管网模型');await expect(page.locator('.pipe-model-scene canvas')).toBeVisible();await expect(page.getByText('正在加载管网模型…')).toHaveCount(0);await page.getByRole('button',{name:'定位演示异常'}).click();const alarm=page.locator('.model-alarm');await expect(alarm.first()).toBeVisible();await alarm.first().click();await expect(page.locator('#info')).toHaveClass(/show/);await expect(page.locator('#infoDl')).toContainText('80');await page.getByRole('button',{name:'地下',exact:true}).click();await page.getByRole('button',{name:'透明地面',exact:true}).click();await page.getByRole('button',{name:'剖切',exact:true}).click();await page.getByRole('button',{name:'图层',exact:true}).click();await expect(page.locator('#layerPop')).toBeVisible();await page.locator('#layerPop input').first().uncheck();await page.locator('#btnLayers').click();await page.screenshot({path:'verification/network-model/model-1920.png',fullPage:true});const good=heat.v.s_hc1_supply_temperature.findIndex((v:number)=>v<=80);await page.getByLabel('演示时间',{exact:true}).fill(String(good));await expect(alarm).toHaveCount(0);await page.getByRole('button',{name:'播放',exact:true}).click();await expect(page.getByRole('button',{name:'暂停',exact:true})).toBeVisible();await page.getByRole('button',{name:'暂停',exact:true}).click();for(let i=0;i<3;i++){await page.locator('nav').getByRole('link',{name:'总览',exact:true}).click();await page.locator('nav').getByRole('link',{name:'管网模型',exact:true}).click();await expect(page.locator('canvas#c')).toHaveCount(1)}expect(errors).toEqual([])})
test('离线、手机布局和减少动态效果',async({page,context})=>{await page.goto('/model');await expect(page.getByText('正在加载管网模型…')).toHaveCount(0);await context.setOffline(true);await page.setViewportSize({width:375,height:812});await page.getByRole('button',{name:'定位演示异常'}).click();await expect(page.locator('.model-alarm').first()).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.locator('#entSel').selectOption('ent-1');await page.locator('#segSel').selectOption('seg-2');await page.getByRole('button',{name:'复位视角'}).click();await page.evaluate(()=>{(document.activeElement as HTMLElement)?.blur()});await page.screenshot({path:'verification/network-model/model-375.png',fullPage:true});expect(await page.locator('.model-alarm').first().evaluate(e=>getComputedStyle(e).animationName)).toBe('none')})


test('模型加载失败可恢复',async({page})=>{await page.route(new RegExp('(/assets/scene-.*\\.js|/src/model/scene\\.ts)(\\?.*)?$'),r=>r.abort());await page.goto('/model');await expect(page.getByRole('alert')).toContainText('模型加载失败');await expect(page.getByRole('button',{name:'重新加载'})).toBeVisible();await page.unroute(new RegExp('(/assets/scene-.*\\.js|/src/model/scene\\.ts)(\\?.*)?$'));await page.getByRole('button',{name:'重新加载'}).click();await expect(page.getByText('正在加载管网模型…')).toHaveCount(0);await expect(page.getByRole('alert')).toHaveCount(0);await expect(page.locator('canvas#c')).toBeVisible()})
