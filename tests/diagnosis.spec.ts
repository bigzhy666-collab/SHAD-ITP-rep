import {expect,test} from '@playwright/test'

test('同页单选诊断、过程回看、自动报告及历史新版本',async({page},info)=>{
 test.setTimeout(45000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/diagnosis');await page.getByRole('button',{name:'新建诊断',exact:true}).click()
 await expect(page.getByRole('heading',{name:'原因诊断与解决建议',exact:true})).toHaveCount(0)
 const events=page.locator('.event-choice input');await expect(events).toHaveCount(2)
 await page.getByRole('button',{name:'取消全选',exact:true}).click();await expect(page.getByRole('button',{name:'开始诊断（0 项事件）'})).toBeDisabled()
 await events.first().check();await page.getByRole('button',{name:'开始诊断（1 项事件）'}).click()
 await expect(page).toHaveURL(/diagnosis\/AI-/);const taskUrl=page.url()
 await expect(page.locator('.process-rail [data-state=running]')).toHaveCount(1,{timeout:5000})
 await page.screenshot({path:info.outputPath('diagnosis-running.png'),fullPage:true});await page.reload();await expect(page.locator('.event-choice input:checked')).toHaveCount(1)
 await expect(page.getByRole('heading',{name:'原因诊断与解决建议',exact:true})).toBeVisible({timeout:15000})
 await page.getByRole('button',{name:/检查参数关联/}).click();await expect(page.getByRole('button',{name:'双轴时序对齐'})).toBeVisible()
 await page.getByRole('button',{name:'双轴时序对齐'}).click();await expect(page.locator('.process-chart canvas')).toBeVisible()
 await page.screenshot({path:info.outputPath('diagnosis-single-event.png'),fullPage:true});const report=page.getByRole('region',{name:'诊断报告与归档'});await expect(report).toBeVisible();await expect(report.getByRole('cell',{name:'回水压力',exact:true})).toHaveCount(0)
 await report.getByRole('textbox',{name:/归档备注/}).fill('单选事件诊断备注');await report.getByRole('button',{name:'保存备注',exact:true}).click()
 await report.getByRole('button',{name:'确认归档',exact:true}).click();await page.getByRole('button',{name:'确认归档当前版本'}).click()
 await report.getByRole('button',{name:'重新生成新版本'}).click();await expect(page).toHaveURL(/diagnosis\/REP-/);await expect(page.getByRole('textbox',{name:/归档备注/})).toHaveValue('')
 await page.goto(taskUrl);await expect(page.getByRole('button',{name:'当前版本已归档'})).toHaveCount(0)
 await page.getByRole('button',{name:'历史记录',exact:true}).click();await page.getByRole('button',{name:'报告与归档',exact:true}).click();await page.getByLabel('归档状态').selectOption('yes');await expect(page.getByRole('button',{name:'查看报告',exact:true})).toHaveCount(1)
 await page.screenshot({path:info.outputPath('diagnosis-history.png'),fullPage:true});await page.getByRole('button',{name:'查看报告',exact:true}).click();await expect(page.getByRole('textbox',{name:/归档备注/})).toHaveValue('单选事件诊断备注');await expect(page.getByRole('textbox',{name:/归档备注/})).toHaveAttribute('readonly','')
 expect(errors).toEqual([])
})

test('旧链接兼容，切换当前管段不改写历史来源',async({page})=>{
 await page.goto('/analysis/AI-20261103-042');await expect(page).toHaveURL(/diagnosis\/AI-20261103-042/)
 await page.goto('/networks');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-2');await page.getByRole('button',{name:'确认选择',exact:true}).click()
 await page.goto('/reports/REP-20261103-018');await expect(page).toHaveURL(/diagnosis\/REP-20261103-018/);await expect(page.locator('.object-path')).toContainText('2号一次供热管段');await expect(page.locator('.diagnosis-task-meta+ p')).toContainText('1号二次供热管段')
 await page.goto('/reports');await expect(page.getByRole('button',{name:'报告与归档',exact:true})).toBeVisible()
 await page.goto('/diagnosis/missing');await expect(page.getByRole('alert')).toContainText('记录不存在')
})

test('没有检测或异常时给出引导且不生成诊断',async({page})=>{
 await page.goto('/networks');await page.getByRole('button',{name:'确认选择',exact:true}).click();await page.goto('/diagnosis?create=1');await page.evaluate(()=>{const key='shad-workspace-v3',s=JSON.parse(localStorage.getItem(key)!);s.detections[0].anomalies=[];localStorage.setItem(key,JSON.stringify(s))});await page.reload();await expect(page.getByText('该检测未检出异常事件，无需发起原因诊断。',{exact:false})).toBeVisible();await expect(page.getByRole('button',{name:'开始诊断（0 项事件）'})).toBeDisabled()
 await page.goto('/networks');await page.getByLabel('管段选择',{exact:true}).selectOption('seg-2');await page.getByRole('button',{name:'确认选择',exact:true}).click();await page.goto('/diagnosis?create=1');await expect(page.getByText('请先完成异常检测。',{exact:false})).toBeVisible()
})
