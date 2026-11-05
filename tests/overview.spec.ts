import { expect, test } from '@playwright/test'

const routes=['overview','networks','detections','diagnosis']
test('四模块可导航，已移除工控工具，切换入口紧接对象路径',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/overview')
 const nav=page.getByRole('navigation');await expect(nav.getByRole('link')).toHaveCount(4)
 for(const [i,name] of ['总览','管网管理','异常检测','AI诊断'].entries()){await nav.getByRole('link',{name,exact:true}).click();await expect(page).toHaveURL(new RegExp('/'+routes[i]));await expect(page.locator('main')).toBeVisible()}
 await expect(page.getByText('工控支撑工具',{exact:true})).toHaveCount(0);await expect(page.getByText('残差阈值标定',{exact:true})).toHaveCount(0)
 await page.getByRole('link',{name:'切换管段对象'}).click();await expect(page).toHaveURL(/networks\?pick=1/);expect(errors).toEqual([])
})
test('完整检测、AI、报告及归档流程，刷新后保留',async({page})=>{
 await page.goto('/detections?create=1');const dialog=page.getByRole('dialog');await dialog.getByLabel('任务名称').fill('全流程检测')
 await dialog.getByRole('button',{name:'创建并执行检测'}).click();await expect(page).toHaveURL(/detections\/DET-/);await expect(page.getByText('检测状态：已完成',{exact:false})).toBeVisible({timeout:15000})
 await page.getByRole('button',{name:/将选中异常/}).click();await expect(page).toHaveURL(/diagnosis\/AI-/);await expect(page.getByRole('heading',{name:'原因诊断与解决建议',exact:true})).toBeVisible({timeout:15000})
 await expect(page.getByRole('button',{name:'导出 PDF',exact:true})).toBeVisible()
 await page.getByRole('textbox',{name:/归档备注/}).fill('人工核查前的演示归档备注');await page.getByRole('button',{name:'保存备注',exact:true}).click();await page.getByRole('button',{name:'确认归档',exact:true}).click();await page.getByRole('button',{name:'确认归档当前版本'}).click()
 await expect(page.getByRole('button',{name:'当前版本已归档'})).toBeDisabled();await page.reload();await expect(page.getByRole('textbox',{name:/归档备注/})).toHaveValue('人工核查前的演示归档备注')
})
test('导出 Word 和 PDF 为有效文件',async({page},info)=>{
 test.setTimeout(120000);await page.goto('/reports');await expect(page.locator('canvas').first()).toBeVisible();await page.evaluate(()=>document.fonts.ready)
 for(const kind of ['Word','PDF']){const downloading=page.waitForEvent('download',{timeout:90000});await page.getByRole('button',{name:kind==='Word'?'导出 Word (.docx)':'导出 PDF',exact:true}).click();const file=await downloading;await file.saveAs(info.outputPath('sample-report.'+(kind==='Word'?'docx':'pdf')));expect(file.suggestedFilename()).toMatch(kind==='Word'?/\.docx$/:/\.pdf$/);const stream=await file.createReadStream();const parts:Buffer[]=[];for await(const part of stream!)parts.push(part);const bytes=Buffer.concat(parts);expect(bytes.length).toBeGreaterThan(10000);expect(bytes.subarray(0,kind==='Word'?2:4).toString()).toBe(kind==='Word'?'PK':'%PDF')}
})
test('层级联动、空参数、无数据及选择持久化',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/networks');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-3');await expect(page.getByText('当前管段未配置监测参数，暂不能发起检测。')).toBeVisible();await page.getByRole('button',{name:'确认选择',exact:true}).click();await page.reload();await expect(page.getByLabel('管段选择',{exact:true})).toHaveValue('seg-3')
 await page.getByLabel('企业选择',{exact:true}).selectOption('ent-2');await expect(page.getByLabel('供热管网选择',{exact:true})).toHaveValue('');await expect(page.getByLabel('管段选择',{exact:true})).toHaveValue('');await page.getByLabel('供热管网选择',{exact:true}).selectOption('net-3');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-5');await page.getByRole('button',{name:'确认选择',exact:true}).click();await expect(page.locator('.object-path')).toContainText('高新供热管段');expect(errors).toEqual([])
})
test('检测校验、无异常和失败重试',async({page})=>{
 await page.goto('/detections?create=1');let dialog=page.getByRole('dialog');await dialog.getByLabel('开始时间').fill('2026-11-03T09:00');await dialog.getByRole('button',{name:'创建并执行检测'}).click();await expect(dialog.getByRole('alert')).toContainText('起始时间必须早于结束时间')
 await dialog.getByLabel('开始时间').fill('2026-11-03T00:00');await dialog.getByLabel('演示场景').selectOption('normal');await dialog.getByRole('button',{name:'创建并执行检测'}).click();await expect(page.getByText('检测完成，未检出异常',{exact:true})).toBeVisible({timeout:15000})
 await page.getByRole('button',{name:'新建检测',exact:true}).click();dialog=page.getByRole('dialog');await dialog.getByLabel('演示场景').selectOption('failure');await dialog.getByRole('button',{name:'创建并执行检测'}).click();await expect(page.getByRole('button',{name:'重试检测',exact:true})).toBeVisible({timeout:15000});await page.getByRole('button',{name:'重试检测',exact:true}).click();await expect(page.getByText('检测状态：已完成',{exact:false})).toBeVisible({timeout:15000})
})
test('刷新快捷键保留筛选和路由',async({page})=>{
 await page.goto('/networks');await page.getByLabel('搜索管段').fill('ST-P01');await page.keyboard.press('Control+r');await expect(page.getByRole('status')).toContainText('演示数据已刷新');await expect(page.getByLabel('搜索管段')).toHaveValue('ST-P01');await expect(page).toHaveURL(/networks/)
})
for(const width of [2560,1920,1440,1366,768,390,375])test(`${width}px 四模块适配与视觉记录`,async({page},info)=>{
 test.setTimeout(120000);await page.setViewportSize({width,height:width>1000?1000:844});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 for(const route of routes){await page.goto('/'+route);await page.evaluate(()=>document.fonts.ready);await expect(page.locator('canvas').first()).toBeVisible();const sizes=await page.evaluate(()=>({page:document.documentElement.scrollWidth,view:document.documentElement.clientWidth}));expect(sizes.page,route).toBeLessThanOrEqual(sizes.view+1);await page.screenshot({path:info.outputPath(`${route}-${width}.png`),fullPage:true})}
 expect(errors).toEqual([])
})
test('存储失败明确提示',async({page})=>{await page.addInitScript(()=>{Storage.prototype.setItem=()=>{throw new Error('quota')}});await page.goto('/networks');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-2');await page.getByRole('button',{name:'确认选择',exact:true}).click();await expect(page.getByRole('alert')).toContainText('本地保存失败')})


test('AI 失败可重试并返回检测保留异常选择',async({page})=>{
 await page.goto('/detections');await page.getByRole('checkbox',{name:/回水压力微幅脉冲/}).uncheck();await page.getByLabel('演示分析失败场景').check();await page.getByRole('button',{name:/将选中异常/}).click();await expect(page.getByRole('button',{name:'重试诊断'})).toBeVisible({timeout:15000});await page.getByRole('button',{name:'重试诊断'}).click();await expect(page.getByRole('heading',{name:'原因诊断与解决建议',exact:true})).toBeVisible({timeout:15000});await page.getByRole('link',{name:'返回检测结果'}).click();await expect(page.getByRole('checkbox',{name:/回水温度骤降异常/})).toBeChecked();await expect(page.getByRole('checkbox',{name:/回水压力微幅脉冲/})).not.toBeChecked()
})
test('运行中任务刷新恢复，缺少关联参数时降级展示',async({page})=>{
 await page.goto('/detections?create=1');const dialog=page.getByRole('dialog');for(const name of ['供水温度','回水温度','循环流量'])await dialog.getByRole('checkbox',{name:new RegExp(name)}).uncheck();await dialog.getByRole('button',{name:'创建并执行检测'}).click();await page.reload();await expect(page.getByText('检测状态：已完成',{exact:false})).toBeVisible({timeout:15000});await page.getByRole('button',{name:/将选中异常/}).click();await expect(page.getByRole('heading',{name:'原因诊断与解决建议',exact:true})).toBeVisible({timeout:15000});await page.getByRole('button',{name:/检查参数关联/}).click();await expect(page.getByRole('button',{name:'关联散点流'})).toBeDisabled();await expect(page.getByText('测点变化或局部水力扰动',{exact:false}).first()).toBeVisible()
})
test('PDF 导出失败保留页面并可重试',async({page})=>{
 test.setTimeout(120000);await page.goto('/reports');await page.route('**/fonts/NotoSansSC.ttf',route=>route.abort());await page.getByRole('button',{name:'导出 PDF',exact:true}).click();await expect(page.getByRole('alert')).toContainText('导出失败');await expect(page.getByRole('textbox',{name:/归档备注/})).toBeVisible();await page.unroute('**/fonts/NotoSansSC.ttf');const downloading=page.waitForEvent('download',{timeout:90000});await page.getByRole('button',{name:'导出 PDF',exact:true}).click();expect((await downloading).suggestedFilename()).toMatch(/pdf$/)
})
test('移动导航和图表参数可操作',async({page})=>{
 await page.setViewportSize({width:375,height:812});await page.goto('/overview');await page.getByRole('button',{name:'打开导航菜单'}).click();await page.getByRole('link',{name:'管网管理',exact:true}).click();await expect(page).toHaveURL(/networks/);await page.getByLabel('图表监测参数').selectOption('pressure');await expect(page.getByLabel('图表监测参数')).toHaveValue('pressure');await page.getByLabel('开始时间',{exact:true}).fill('2026-11-03T09:00');await expect(page.getByText('当前管段或时间范围暂无数据，请调整选择。')).toBeVisible();await page.getByLabel('开始时间',{exact:true}).fill('2026-11-03T00:00');await expect(page.locator('canvas').first()).toBeVisible();await page.goto('/diagnosis');await page.getByRole('button',{name:/检查参数关联/}).click();await page.getByRole('button',{name:'双轴时序对齐'}).click();await expect(page.getByLabel('图表监测参数').first()).toHaveValue('return')
})
