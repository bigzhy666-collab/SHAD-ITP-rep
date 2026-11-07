import {expect,test} from '@playwright/test'

test('三栏联动、分类折叠、参数对比、异常定位和采样明细',async({page},info)=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/detections')
 await expect(page.getByRole('heading',{name:'数据监测',exact:true})).toBeVisible()
 const readings=page.locator('.monitor-readings');await expect(readings).toContainText('回水温度')
 await page.getByRole('button',{name:'监测供水温度',exact:true}).click();await expect(readings).toContainText('供水温度');await expect(readings).not.toContainText('回水温度')
 await page.getByRole('button',{name:'多参数对比',exact:true}).click();await page.getByRole('button',{name:'监测回水压力',exact:true}).click();await expect(page.locator('.monitor-reading')).toHaveCount(2)
 await page.getByRole('button',{name:'温度',exact:true}).click();await expect(page.getByRole('button',{name:'监测供水温度',exact:true})).toHaveCount(0);await page.getByRole('button',{name:'温度',exact:true}).click()
 await page.getByLabel('异常事件范围').selectOption('all');await page.getByRole('button',{name:'定位回水温度骤降异常',exact:true}).click();await expect(page.locator('.monitor-event-detail')).toContainText('33.2');await expect(page.locator('[data-testid=telemetry-chart]')).toHaveAttribute('data-focused-event','AN-01');await expect(page.locator('.monitor-reading')).toHaveCount(3)
 await page.getByLabel('仅异常 / 质量问题').check();const table=page.locator('.monitor-center table');await expect(table).toContainText('运行参数异常');await expect(table).not.toContainText('有效采样');await expect(page.locator('.monitor-quality')).toContainText('数据质量问题 0 条')
 const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出监测 CSV'}).click();expect((await downloading).suggestedFilename()).toMatch(/监测数据.csv$/)
 await page.screenshot({path:info.outputPath('monitoring-compare-focused.png'),fullPage:true});expect(errors).toEqual([])
})

test('监测时间筛选只改变视图，检测输入独立并可一键带入',async({page})=>{
 await page.goto('/detections');const form=page.getByRole('region',{name:'异常检测配置'});await expect(form.getByLabel('结束时间 *',{exact:true})).toHaveValue('2026-11-03T08:00')
 await page.getByLabel('监测开始时间').fill('2026-11-03T01:00');await page.getByLabel('监测结束时间').fill('2026-11-03T02:00');await page.getByRole('button',{name:'应用范围',exact:true}).click();await expect(page.locator('.monitor-event-count')).toContainText('0');await expect(form.getByLabel('结束时间 *',{exact:true})).toHaveValue('2026-11-03T08:00')
 await page.getByRole('button',{name:'使用当前监测范围与参数'}).click();await expect(form.getByLabel('结束时间 *',{exact:true})).toHaveValue('2026-11-03T02:00');await expect(form.getByRole('checkbox',{name:/回水温度/})).toBeChecked();await expect(form.getByRole('checkbox',{name:/循环流量/})).not.toBeChecked()
 await page.getByLabel('监测开始时间').fill('2026-11-03T05:00');await page.getByRole('button',{name:'应用范围',exact:true}).click();await expect(page.getByRole('alert')).toContainText('监测开始时间必须早于结束时间');await expect(form.getByLabel('结束时间 *',{exact:true})).toHaveValue('2026-11-03T02:00')
})

test('无参数、无采样和历史对象均有明确边界',async({page})=>{
 await page.goto('/networks');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-3');await page.getByRole('button',{name:'确认选择',exact:true}).click();await page.goto('/detections');await expect(page.locator('.monitor-parameters')).toContainText('当前管段未配置监测参数');await expect(page.getByRole('button',{name:'创建并执行检测'})).toBeDisabled()
 await page.goto('/networks');await page.getByLabel('供热管网选择',{exact:true}).selectOption('net-2');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-4');await page.getByRole('button',{name:'确认选择',exact:true}).click();await page.goto('/detections');await expect(page.getByRole('button',{name:'监测回水压力',exact:true})).toHaveCount(0);await expect(page.locator('.monitor-reading')).toContainText('无有效数据');await expect(page.getByRole('button',{name:'创建并执行检测'})).toBeDisabled()
 await page.goto('/detections/DET-20261103-089');await expect(page.locator('.monitor-context')).toContainText('1号二次供热管段');await expect(page.locator('.object-path')).toContainText('西区供热支线')
})

test('移动端定位后仍可切换图表参数，历史筛选不改变当前任务',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/detections');await page.getByLabel('异常事件范围').selectOption('all');await page.getByRole('button',{name:'定位回水压力微幅脉冲',exact:true}).click();await expect(page.locator('.monitor-readings')).toContainText('回水压力')
 await page.getByRole('button',{name:'多参数对比',exact:true}).click();await page.getByRole('button',{name:'监测供水温度',exact:true}).click();await page.getByLabel('图表监测参数').selectOption('supply');await expect(page.getByLabel('图表监测参数')).toHaveValue('supply')
 await page.getByRole('button',{name:'任务记录',exact:true}).click();await page.getByLabel('搜索检测任务').fill('不存在');await expect(page.locator('#detection-history')).toContainText('当前范围没有匹配任务');await expect(page.locator('.monitor-context')).toContainText('1号二次供热管段');await expect(page.getByText('DET-20261103-089',{exact:true})).toBeVisible()
})

test('监测超出已检测区间时不会延长持续异常',async({page})=>{
 await page.goto('/detections');await page.getByLabel('异常事件范围').selectOption('all')
 await page.getByLabel('监测开始时间').fill('2026-11-03T09:00');await page.getByLabel('监测结束时间').fill('2026-11-03T10:00');await page.getByRole('button',{name:'应用范围',exact:true}).click()
 await expect(page.locator('.monitor-event-count')).toContainText('0');await expect(page.getByText('部分监测时段尚未检测，异常统计仅来自已有检测覆盖区间。')).toBeVisible();await expect(page.getByRole('button',{name:'监测回水压力',exact:true})).toContainText('部分未检测')
})
