import {expect,test} from '@playwright/test'
import {fields,optionalFields} from '../../src/services/local/fields'
import fs from 'node:fs/promises'

const columns=[...fields,...optionalFields]
const csv=Buffer.from(['时间,'+columns.map(f=>f.field).join(','),...Array.from({length:60},(_,i)=>[
 new Date(Date.parse('2026-11-08T00:00:00+08:00')+i*30*60000).toISOString(),
 10+i/10,90,50,100,2500,35,55,55,35,60,55,60,40,60,
].join(','))].join('\n'))

test('真实检测与报告闭环：来源快照、备注冲突、归档、新版本及实际导出',async({page,request})=>{
 test.setTimeout(90000)
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'))
 await page.goto('/networks')
 await page.getByLabel('本机管段选择').selectOption('seg-2')
 await page.getByRole('button',{name:'确认选择',exact:true}).click()
 await expect(page.getByLabel('关联换热站')).toHaveValue('station-browser-fixture')
 await page.locator('input[type=file]').setInputFiles({name:'仅测试-合成异常样例.csv',mimeType:'text/csv',buffer:csv})
 await page.getByRole('button',{name:'导入并校验本站数据'}).click()
 await expect(page.getByText('数据已保存，可用于检测。')).toBeVisible()
 const datasets=(await(await request.get('/api/datasets?stationId=station-browser-fixture')).json()).data.items
 const dataset=datasets.find((d:{name:string})=>d.name==='仅测试-合成异常样例')
 await page.goto(`/detections?stationId=station-browser-fixture&datasetId=${dataset.id}`)
 await expect(page.getByLabel('检测数据集')).toHaveValue(dataset.id)
 await expect(page.getByRole('button',{name:'创建本站检测',exact:true})).toBeEnabled()
 const created=page.waitForResponse(r=>r.url().endsWith('/api/detections')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'创建本站检测',exact:true}).click()
 const response=await created;expect(response.status()).toBe(202)
 const task=(await response.json()).data
 await expect(page).toHaveURL(new RegExp(`/detections/${task.id}$`))
 await expect(page.getByText('确认告警 1 段',{exact:true})).toBeVisible({timeout:15000})
 await expect(page.getByText('正在执行示例模型；结果用于接口验证，不构成本站模型适用性或诊断准确性证明。',{exact:true})).toBeVisible()
 const result=(await(await request.get(`/api/detections/${task.id}/result`)).json()).data
 expect(result.summary.pointCount).toBe(60)
 const events=(await(await request.get(`/api/detections/${task.id}/events`)).json()).data.items
 expect(events[0].cause).toBeNull();expect(events[0].solution).toBeNull()
 await page.getByRole('button',{name:'定位区间',exact:true}).click()
 await expect(page.locator('.local-chart').last()).toHaveAttribute('data-focused-event',/2026-11/)
 await page.getByLabel('全选确认告警').check()
 await page.reload();await expect(page.getByLabel('全选确认告警')).toBeChecked()
 for(const width of [1366,390]){
  await page.setViewportSize({width,height:900})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
  await page.screenshot({path:`verification/organization-management/detection-${width}.png`,fullPage:true})
 }
 await page.getByRole('button',{name:'查看 1 项事件与报告'}).click()
 await expect(page.getByRole('button',{name:/分析所选/})).toHaveCount(0)
 await expect(page.getByRole('button',{name:'保存并归档'})).toBeEnabled()
 await page.getByLabel('本机报告备注').fill('真实接口验收：示例模型及合成数据，不作现场结论。')
 await page.getByRole('button',{name:'保存并归档'}).click()
 await expect(page.getByText('V1 · 已归档',{exact:true})).toBeVisible()
 await expect(page).toHaveURL(/reportId=/)
 await expect(page.getByLabel('本机报告备注')).toBeDisabled()
 const firstId=new URL(page.url()).searchParams.get('reportId')!
 const first=(await(await request.get('/api/reports/'+firstId)).json()).data
 expect(first.snapshot.task.id).toBe(task.id);expect(first.snapshot.points.length).toBe(60)
 expect(first.snapshot.events.map((e:{id:string})=>e.id)).toEqual(events.map((e:{id:string})=>e.id))
 expect(first.snapshot.diagnosis).toBeNull();expect(first.archivedAt).toBeTruthy()
 await page.getByRole('button',{name:'创建新版本'}).click()
 await expect(page.getByText('V2 · 已保存',{exact:true})).toBeVisible()
 const secondId=new URL(page.url()).searchParams.get('reportId')!
 const second=(await(await request.get('/api/reports/'+secondId)).json()).data
 expect(second.seriesId).toBe(first.id);expect(second.snapshot).toEqual(first.snapshot)
 // A second window writes a competing note. The first window must retain its input.
 const other=await request.patch(`/api/reports/${secondId}/note`,{data:{note:'其他窗口已保存备注',expectedRevision:second.revision}})
 expect(other.status()).toBe(200)
 await page.getByLabel('本机报告备注').fill('复核后备注：合成数据和示例模型，仍需现场核查。')
 await page.getByRole('button',{name:'保存报告与备注'}).click()
 await expect(page.getByRole('alert')).toContainText('其他窗口更新')
 await expect(page.getByLabel('本机报告备注')).toHaveValue('复核后备注：合成数据和示例模型，仍需现场核查。')
 await page.getByRole('button',{name:'读取最新版本，保留当前备注'}).click()
 await expect(page.getByText('最新已保存备注：其他窗口已保存备注。请核对下方当前输入后再保存。',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'保存并归档'}).click()
 await expect(page.getByText('V2 · 已归档',{exact:true})).toBeVisible()
 await page.reload()
 await expect(page.getByLabel('本机报告备注')).toHaveValue('复核后备注：合成数据和示例模型，仍需现场核查。')
 await expect(page.getByLabel('本机报告备注')).toBeDisabled()
 expect((await(await request.get('/api/reports/'+firstId)).json()).data).toEqual(first)
 const archived=(await(await request.get('/api/reports/'+secondId)).json()).data
 await fs.writeFile('verification/organization-management/report-snapshots.json',JSON.stringify({archivedV1:first,archivedV2:archived},null,2))
 // A real resource failure must leave the archived record untouched, then allow retry.
 await page.route('**/fonts/NotoSansSC.ttf',route=>route.fulfill({status:404,body:''}))
 await page.getByRole('button',{name:'导出 PDF',exact:true}).click()
 await expect(page.getByRole('alert')).toContainText('本地中文字体读取失败')
 expect((await(await request.get('/api/reports/'+secondId)).json()).data).toEqual(archived)
 await page.unroute('**/fonts/NotoSansSC.ttf')
 for(const format of ['Word','PDF']){
  const download=page.waitForEvent('download')
  await page.getByRole('button',{name:`导出 ${format}`,exact:true}).click()
  const file=await download
  const path=`verification/organization-management/exports/synthetic-model-detection-V2.${format==='PDF'?'pdf':'docx'}`
  await file.saveAs(path)
  const bytes=await fs.readFile(path)
  expect(bytes.length).toBeGreaterThan(1000)
  expect(bytes.subarray(0,format==='PDF'?4:2).toString()).toBe(format==='PDF'?'%PDF':'PK')
 }
 for(const width of [1920,1366,768,390,375]){
  await page.setViewportSize({width,height:900})
  await page.evaluate(()=>window.scrollTo(0,0))
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
  await page.screenshot({path:`verification/organization-management/diagnosis-archived-${width}.png`,fullPage:true})
 }
 const history=(await(await request.get(`/api/reports?detectionId=${task.id}&archived=true`)).json()).data
 expect(history.total).toBe(2);expect(history.items.every((r:object)=>!('snapshot' in r))).toBe(true)
 await page.getByRole('link',{name:'返回数据监测',exact:true}).click()
 await expect(page.getByLabel('全选确认告警')).toBeChecked()
 expect(errors).toEqual([])
})

test('未保存报告导出时先持久化备注和证据，刷新恢复同一版本',async({page,request})=>{
 const tasks=(await(await request.get('/api/detections?segmentId=seg-2&status=success')).json()).data.items
 const task=tasks[0];expect(task).toBeTruthy()
 const events=(await(await request.get(`/api/detections/${task.id}/events`)).json()).data.items
 await page.addInitScript(()=>localStorage.setItem('shad-service-mode','local'))
 await page.goto(`/diagnosis?detectionId=${task.id}&eventIds=${encodeURIComponent(JSON.stringify([events[0].id]))}`)
 await expect(page.getByText('临时报告 · 未存档',{exact:true})).toBeVisible()
 await page.getByLabel('本机报告备注').fill('导出前自动保存的备注：保留完整来源。')
 const download=page.waitForEvent('download')
 await page.getByRole('button',{name:'导出 Word',exact:true}).click()
 await(await download).saveAs('verification/organization-management/exports/autosaved-V1.docx')
 await expect(page).toHaveURL(/reportId=/)
 await expect(page.getByText('V1 · 已保存',{exact:true})).toBeVisible()
 const id=new URL(page.url()).searchParams.get('reportId')!
 const report=(await(await request.get('/api/reports/'+id)).json()).data
 expect(report.note).toBe('导出前自动保存的备注：保留完整来源。')
 expect(report.archivedAt).toBeNull();expect(report.snapshot.points.length).toBe(60)
 await fs.writeFile('verification/organization-management/autosaved-snapshot.json',JSON.stringify(report,null,2))
 await page.reload()
 await expect(page.getByLabel('本机报告备注')).toHaveValue(report.note)
 await expect(page.getByText('V1 · 已保存',{exact:true})).toBeVisible()
})
