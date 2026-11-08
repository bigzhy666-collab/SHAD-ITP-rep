import {expect,test} from '@playwright/test'
import {mockLocal,makeTask} from './helpers/localApi'
import {fields} from '../src/services/local/fields'

test('服务不可用不回退演示，恢复连接与模式切换保留边界',async({page})=>{
 const state=await mockLocal(page);state.offline=true;await page.goto('/detections/DET-20261103-089');await page.getByLabel('运行模式').selectOption('local')
 await expect(page).toHaveURL(/\/detections$/);await expect(page.getByRole('heading',{name:'本机服务尚未连接'})).toBeVisible();await expect(page.getByRole('button',{name:'创建并执行检测'})).toHaveCount(0)
 state.offline=false;await page.getByRole('button',{name:'重新连接本机服务'}).click();await expect(page.getByLabel('检测换热站')).toHaveValue('station-1');await page.getByLabel('本机检测开始时间').fill('2026-11-08T01:00');await page.getByRole('button',{name:'刷新数据',exact:true}).click();await expect(page.getByLabel('本机检测开始时间')).toHaveValue('2026-11-08T01:00')
 await page.reload();await expect(page.getByLabel('运行模式')).toHaveValue('local');await page.getByLabel('运行模式').selectOption('demo');await expect(page.locator('.monitoring-page')).toBeVisible()
})

test('本机检测、全量分页、事件定位、真实来源、临时报告和 Word/PDF',async({page},info)=>{
 test.setTimeout(60000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));const state=await mockLocal(page);await page.goto('/detections');await page.getByLabel('运行模式').selectOption('local')
 await expect(page.getByLabel('检测数据集')).toHaveValue('dataset-1');await page.getByRole('button',{name:'读取监测数据',exact:true}).click();await expect(page.getByRole('cell',{name:'186500'})).toHaveCount(0)
 await page.getByLabel('本机图表参数').selectOption('p_net_meter_flow');await expect(page.getByRole('cell',{name:'186500 L/h',exact:true})).toHaveCount(17)
 await page.getByRole('button',{name:'创建本站检测',exact:true}).click();await expect(page).toHaveURL(/detections\/det-1$/);await expect(page.getByText('确认告警 1 段',{exact:true})).toBeVisible({timeout:10000})
 const submission=state.requests.find(r=>r.method()==='POST'&&new URL(r.url()).pathname==='/api/detections')!;expect(submission.headers()['idempotency-key']).toBeTruthy();expect(submission.postDataJSON()).not.toHaveProperty('scenario')
 await page.getByRole('button',{name:'定位区间'}).click();await expect(page.locator('.local-chart').last()).toHaveAttribute('data-focused-event',/2026-11-08/)
 const csv=page.waitForEvent('download');await page.getByRole('button',{name:'导出逐点 CSV'}).click();expect((await csv).suggestedFilename()).toContain('det-1')
 await page.getByLabel('全选确认告警').check();await page.getByRole('button',{name:'查看 1 项事件与报告'}).click();await expect(page.getByText('原因诊断尚未接入。',{exact:false})).toBeVisible();await expect(page.getByRole('button',{name:'保存并归档'})).toBeDisabled();await page.getByLabel('本机报告备注').fill('本机接口临时导出备注')
 for(const name of ['导出 Word','导出 PDF']){const download=page.waitForEvent('download');await page.getByRole('button',{name,exact:true}).click();const file=await download;await file.saveAs(info.outputPath(file.suggestedFilename()))}
 await page.screenshot({path:info.outputPath('local-diagnosis-1366.png'),fullPage:true});await page.reload();await expect(page.locator('.local-source')).toContainText('接口联调换热站');expect(errors).toEqual([])
})

test('CSV 映射与单位确认通过 multipart 提交到本站',async({page})=>{
 const state=await mockLocal(page);await page.goto('/networks');await page.getByLabel('运行模式').selectOption('local');await expect(page.getByLabel('关联换热站')).toHaveValue('station-1')
 await page.locator('input[type=file]').setInputFiles({name:'本站.csv',mimeType:'text/csv',buffer:Buffer.from(['时间,'+fields.map(f=>f.field).join(','),'2026-11-08T00:00:00+08:00,'+fields.map(()=>10).join(',')].join('\n'))})
 await page.getByLabel('一次侧瞬时流量原始单位').selectOption('m3/h');await page.getByRole('button',{name:'导入并校验本站数据'}).click();await expect(page.getByText('数据已保存，可用于检测。')).toBeVisible()
 const body=state.requests.find(r=>new URL(r.url()).pathname==='/api/datasets/import')!.postData()!;expect(body).toContain('"p_net_meter_flow":"m3/h"');expect(body).toContain('"stationId":"station-1"')
})

test('无异常属于成功，失败可重试且来源不变',async({page})=>{
 const state=await mockLocal(page,{normal:true});await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'));await page.goto('/detections/det-seed');await expect(page.getByText('检测成功，本次未形成确认告警事件。')).toBeVisible();await expect(page.getByRole('button',{name:'查看 0 项事件与报告'})).toBeDisabled()
 const failed={...makeTask('det-failed'),status:'failed' as const,error:{code:'TASK_INTERRUPTED',message:'上次软件关闭中断任务',retryable:true}};state.tasks.push(failed);await page.goto('/detections/det-failed');await page.getByRole('button',{name:'创建重试任务'}).click();await expect(page).toHaveURL(/detections\/det-1$/);expect(state.tasks.find(t=>t.id==='det-1')?.retryOf).toBe('det-failed')
})

test('诊断能力、报告备注、冲突恢复、归档与版本走真实契约',async({page})=>{
 const state=await mockLocal(page,{diagnosis:true,reports:true});await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'));await page.goto('/diagnosis?detectionId=det-seed&eventIds=event-det-seed')
 await expect(page.getByRole('button',{name:'分析所选 1 项异常'})).toBeEnabled();await page.getByRole('button',{name:'分析所选 1 项异常'}).click();await expect(page.getByRole('heading',{name:'核对实际证据 · 已完成'})).toBeVisible()
 await page.getByLabel('本机报告备注').fill('需要人工复核');await page.getByRole('button',{name:'保存报告与备注'}).click();await expect(page.getByText('V1 · 已保存',{exact:true})).toBeVisible();expect(state.reports[0]?.note).toBe('需要人工复核')
 state.conflict=true;await page.getByLabel('本机报告备注').fill('冲突时保留的备注');await page.getByRole('button',{name:'保存报告与备注'}).click();await expect(page.getByRole('alert')).toContainText('报告已被修改');await expect(page.getByLabel('本机报告备注')).toHaveValue('冲突时保留的备注')
 state.conflict=false;await page.getByRole('button',{name:'保存并归档'}).click();await expect(page.getByLabel('本机报告备注')).toBeDisabled();await page.getByRole('button',{name:'创建新版本'}).click();await expect(page.getByText('V2 · 已保存',{exact:true})).toBeVisible();await page.reload();await expect(page.getByLabel('本机报告备注')).toHaveValue('冲突时保留的备注');expect(state.reports[0]?.archivedAt).toBeTruthy()
})

test('本机界面在 1920、768 和 375 宽度可操作且无整页横向溢出',async({page},info)=>{
 await mockLocal(page);await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'))
 for(const width of [1920,768,375]){await page.setViewportSize({width,height:900});for(const path of ['/overview','/networks','/detections/det-seed','/diagnosis?detectionId=det-seed&eventIds=event-det-seed']){await page.goto(path);await expect(page.getByLabel('运行模式')).toBeVisible();await expect(page.locator('.local-service-state')).toHaveCount(0);if(path.includes('det-seed'))await expect(page.locator('.local-chart')).not.toHaveCount(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath(`${path.split('?')[0].split('/')[1]}-${width}.png`),fullPage:true})}
 }
})

test('事件选择刷新与返回后保留，时间校验不创建任务',async({page})=>{
 const state=await mockLocal(page);await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'));await page.goto('/detections/det-seed');await expect(page.getByLabel('全选确认告警')).toBeEnabled();await page.getByLabel('全选确认告警').check();await page.reload();await expect(page.getByLabel('全选确认告警')).toBeChecked()
 await page.getByLabel('本机检测开始时间').fill('2026-11-09T00:00');await expect(page.getByRole('alert')).toContainText('开始时间必须早于结束时间');await expect(page.getByRole('button',{name:'创建本站检测'})).toBeDisabled();expect(state.requests.filter(r=>r.method()==='POST')).toHaveLength(0)
 await page.getByRole('button',{name:'查看 1 项事件与报告'}).click();await page.getByRole('link',{name:'返回数据监测',exact:true}).click();await expect(page.getByLabel('全选确认告警')).toBeChecked()
})

test('错误来源的结果不展示，服务端失败不伪装健康',async({page})=>{
 await mockLocal(page);await page.route('**/api/detections/det-seed/events*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({data:{items:[{id:'wrong',detectionId:'other-task',stationId:'other-station'}],page:1,pageSize:500,total:1}})}));await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'));await page.goto('/detections/det-seed');await expect(page.getByRole('alert')).toContainText('检测结果来源不一致');await expect(page.getByText('确认告警 1 段',{exact:true})).toHaveCount(0)
})

test('本机 PDF 字体失败可恢复，刷新不丢失未保存备注',async({page})=>{
 test.setTimeout(45000);await mockLocal(page);await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'));await page.goto('/diagnosis?detectionId=det-seed&eventIds=event-det-seed');await expect(page.getByLabel('本机报告备注')).toBeVisible();await page.getByLabel('本机报告备注').fill('失败恢复备注');await page.getByRole('button',{name:'刷新数据',exact:true}).click();await expect(page.getByLabel('本机报告备注')).toHaveValue('失败恢复备注')
 await page.route('**/fonts/NotoSansSC.ttf',route=>route.fulfill({status:404,body:'missing'}));await page.getByRole('button',{name:'导出 PDF',exact:true}).click();await expect(page.getByRole('alert')).toContainText('本地中文字体读取失败');await expect(page.getByLabel('本机报告备注')).toHaveValue('失败恢复备注')
 await page.unroute('**/fonts/NotoSansSC.ttf');const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出 PDF',exact:true}).click();expect((await download).suggestedFilename()).toMatch(/\.pdf$/)
})
