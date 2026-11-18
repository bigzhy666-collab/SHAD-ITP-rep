import {expect,test} from '@playwright/test'

test('本机组织维护：三级新增、改名冲突、停用恢复、模式隔离和刷新保留',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/networks?service=local')
 await expect(page.getByRole('heading',{name:'组织维护'})).toBeVisible()
 async function create(kind:string,name:string,parent?:string){
  await page.getByLabel('组织管理层级').selectOption(kind)
  await page.getByRole('button',{name:'新增'+({enterprises:'企业',networks:'供热管网',segments:'管段'}[kind])}).click()
  await page.getByLabel('组织名称',{exact:true}).fill(name)
  await page.getByLabel('组织编码',{exact:true}).fill('BROWSER-ORG')
  if(parent)await page.getByLabel('组织上级').selectOption(parent)
  await page.getByRole('button',{name:'创建组织',exact:true}).click()
  await expect(page.getByRole('button',{name:'编辑组织 '+name,exact:true})).toBeVisible()
  return (await (await request.get('/api/organizations')).json()).data[kind].find((r:{name:string})=>r.name===name).id as string
 }
 const ent=await create('enterprises','组织验收企业'),net=await create('networks','组织验收管网',ent),seg=await create('segments','组织验收管段',net)
 await page.getByLabel('本机企业选择').selectOption(ent);await page.getByLabel('本机供热管网选择').selectOption(net);await page.getByLabel('本机管段选择').selectOption(seg);await page.getByRole('button',{name:'确认选择',exact:true}).click()
 await expect(page.locator('.sidebar-object')).toContainText('组织验收管段')
 await page.getByRole('button',{name:'编辑组织 组织验收管段',exact:true}).click()
 const row=(await(await request.get('/api/organizations')).json()).data.segments.find((r:{id:string})=>r.id===seg)
 await request.patch('/api/organizations/segments/'+seg,{data:{name:'另一窗口改名',code:row.code,active:true,expectedRevision:row.revision}})
 await page.getByLabel('组织名称',{exact:true}).fill('保留当前输入');await page.getByRole('button',{name:'保存组织修改'}).click()
 await expect(page.getByRole('alert')).toContainText('其他窗口修改');await expect(page.getByLabel('组织名称',{exact:true})).toHaveValue('保留当前输入')
 await page.getByRole('button',{name:'刷新组织',exact:true}).click();await page.getByRole('button',{name:'编辑组织 另一窗口改名',exact:true}).click()
 await page.getByLabel('组织名称',{exact:true}).fill('最终管段名称');await page.getByRole('button',{name:'保存组织修改'}).click();await expect(page.locator('.sidebar-object')).toContainText('最终管段名称')
 await page.reload();await expect(page.locator('.sidebar-object')).toContainText('最终管段名称')
 for(const width of [1366,390]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.evaluate(()=>{(document.activeElement as HTMLElement)?.blur()});await page.screenshot({path:`verification/organization-management/organizations-${width}.png`,fullPage:true})}
 await page.getByLabel('组织管理层级').selectOption('enterprises');await page.getByRole('button',{name:'编辑组织 组织验收企业',exact:true}).click();await page.getByLabel('组织状态').selectOption('false');await page.getByRole('button',{name:'保存组织修改'}).click();await expect(page.locator('.sidebar-object')).toContainText('未选择管段')
 await page.getByRole('button',{name:'编辑组织 组织验收企业',exact:true}).click();await page.getByLabel('组织状态').selectOption('true');await page.getByRole('button',{name:'保存组织修改'}).click();await expect(page.locator('.sidebar-object')).toContainText('最终管段名称')
 await page.getByLabel('运行模式').selectOption('demo');await expect(page.locator('.sidebar-object')).not.toContainText('最终管段名称');await page.getByLabel('运行模式').selectOption('local');await expect(page.locator('.sidebar-object')).toContainText('最终管段名称')
 expect(errors).toEqual([])
})
