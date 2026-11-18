import {expect,test} from '@playwright/test'
import {fields,optionalFields} from '../../src/services/local/fields'

const measures=[...fields,...optionalFields]
function csv(minutes=30){
 const rows=Array.from({length:6},(_,i)=>[
  new Date(Date.parse('2026-11-08T00:00:00+08:00')+i*minutes*60000).toISOString(),
  10+i,90,50,250000,12,40,60,60,40,55,50,60,40,60,
 ].join(','))
 return Buffer.from(['时间,'+measures.map(f=>f.field).join(','),...rows].join('\n'))
}

test('真实本机后端：登记、导入、质量阻断、刷新恢复及监测浏览',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/networks');await page.getByLabel('运行模式').selectOption('local')
 await expect(page.getByText('当前管段未绑定换热站，请先登记本站对象。')).toBeVisible()
 await page.getByText('登记换热站',{exact:true}).click()
 await page.getByLabel('站点名称',{exact:true}).fill('本机验收换热站')
 await page.getByLabel('站点编码',{exact:true}).fill('M1-BROWSER')
 await page.getByRole('button',{name:'绑定到当前管段'}).click()
 await expect(page.getByLabel('关联换热站')).not.toHaveValue('')
 const stationId=await page.getByLabel('关联换热站').inputValue()
 await page.locator('input[type=file]').setInputFiles({name:'验收-半小时.csv',mimeType:'text/csv',buffer:csv()})
 await page.getByLabel('瞬时热功率原始单位').selectOption('W')
 await page.getByLabel('一次侧瞬时流量原始单位').selectOption('m3/h')
 await page.getByText('可选测点（6 项，有数据时建议一并导入）').click()
 await expect(page.getByLabel('生活热水供水温度对应列',{exact:true})).toHaveValue('s_dhw_supply_temperature')
 // A duplicated optional mapping must prevent submission before a request is sent.
 await page.getByLabel('生活热水供水温度对应列',{exact:true}).selectOption('outdoor_temperature')
 await expect(page.getByRole('button',{name:'导入并校验本站数据'})).toBeDisabled()
 await page.getByLabel('生活热水供水温度对应列',{exact:true}).selectOption('s_dhw_supply_temperature')
 await page.getByRole('button',{name:'导入并校验本站数据'}).click()
 await expect(page.getByText('数据已保存，可用于检测。')).toBeVisible()
 const list=(await (await request.get(`/api/datasets?stationId=${stationId}`)).json()).data
 expect(list.total).toBe(1);const dataset=list.items[0]
 expect(dataset.status).toBe('ready');expect(dataset.columns).toHaveLength(14)
 const samples=(await(await request.get(`/api/datasets/${dataset.id}/samples?pageSize=2`)).json()).data
 expect(samples.total).toBe(6);expect(samples.items).toHaveLength(2)
 expect(samples.items[0].values.p_net_meter_heat_power).toBe(250)
 expect(samples.items[0].values.p_net_meter_flow).toBe(12000)
 expect(samples.items[0].values.s_dhw_supply_temperature).toBe(55)
 for(const width of [1920,390]){
  await page.setViewportSize({width,height:900})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),
   {message:'响应式布局稳定后不可出现整页横向溢出',timeout:3000}).toBe(true)
  await page.screenshot({path:`verification/organization-management/networks-${width}.png`,fullPage:true})
 }
 await page.setViewportSize({width:1366,height:900});await page.reload()
 await expect(page.getByLabel('关联换热站')).toHaveValue(stationId)
 await expect(page.getByRole('cell',{name:'验收-半小时 / 1',exact:true})).toBeVisible()
 await page.locator('input[type=file]').setInputFiles({name:'验收-小时稀疏.csv',mimeType:'text/csv',buffer:csv(60)})
 await page.getByRole('button',{name:'导入并校验本站数据'}).click()
 await expect(page.getByText('数据已保存，但存在阻断问题，暂不能检测。')).toBeVisible()
 const invalid=(await(await request.get(`/api/datasets?stationId=${stationId}`)).json()).data.items.find((d:{name:string})=>d.name==='验收-小时稀疏')
 expect(invalid.status).toBe('invalid');expect(invalid.issues.some((i:{code:string;blocking:boolean})=>i.code==='SAMPLING_INTERVAL_UNSUPPORTED'&&i.blocking)).toBe(true)
 await page.goto(`/detections?stationId=${stationId}&datasetId=${dataset.id}`)
 await expect(page.getByLabel('检测数据集')).toHaveValue(dataset.id)
 await page.getByRole('button',{name:'读取监测数据',exact:true}).click()
 await expect(page.getByText('6 条 · 1 / 1',{exact:true})).toBeVisible()
 await page.getByLabel('本机图表参数').selectOption('p_net_meter_flow')
 await expect(page.getByRole('cell',{name:'12000 L/h',exact:true})).toHaveCount(6)
 await expect(page.getByRole('button',{name:'创建本站检测'})).toBeDisabled()
 await page.screenshot({path:'verification/organization-management/monitoring-data-1366.png',fullPage:true})
 expect(errors).toEqual([])
})
