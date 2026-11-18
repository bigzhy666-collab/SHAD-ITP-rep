import {test,expect,_electron,type ElectronApplication} from '@playwright/test'
import {execFile,spawn} from 'node:child_process'
import {promisify} from 'node:util'
import {mkdir,readFile} from 'node:fs/promises'
import path from 'node:path'
import net from 'node:net'
const command=promisify(execFile)
const exe=process.env.SHAD_DESKTOP_EXE
if(!exe)throw new Error('请设置 SHAD_DESKTOP_EXE 为本轮桌面程序路径。')
const backend=path.join(path.dirname(exe),'resources/backend/SHAD.exe')
const cleanEnv=Object.fromEntries(Object.entries(process.env).filter(([k,v])=>k!=='ELECTRON_RUN_AS_NODE'&&v!==undefined)) as Record<string,string>
async function freePort(){const server=net.createServer();await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));const port=(server.address() as net.AddressInfo).port;await new Promise<void>(r=>server.close(()=>r()));return port}
async function launch(name:string,port:number){
 const root=path.resolve('build/desktop-checks',name+'-'+Date.now());await mkdir(root,{recursive:true});
 const data=path.join(root,'数据 空格'),profile=path.join(root,'窗口配置');
 const args=['--data-dir',data,'--profile-dir',profile,'--port',String(port)];
 const application=await _electron.launch({executablePath:exe!,args,env:cleanEnv,timeout:60000});
 return {application,data,root,args};
}
async function cleanup(application:ElectronApplication,data:string){
 await application.evaluate(({app})=>app.exit(0)).catch(()=>{});
 await command(backend,['stop','--json','--data-dir',data],{windowsHide:true,timeout:45000});
 const status=JSON.parse((await command(backend,['status','--json','--data-dir',data],{windowsHide:true})).stdout);
 expect(status.running).toBe(false);
}

test('实际 Windows 窗口的小图标和任务栏大图标没有多余留白',async()=>{
 const {application,data}=await launch('窗口图标',await freePort());
 try{
  const page=await application.firstWindow();await page.waitForURL(/\/model\?service=local/,{timeout:60000});
  const handle=await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.getNativeWindowHandle().readBigUInt64LE().toString());
  const python=process.env.SHAD_ICON_PYTHON || 'python';
  await command(python,['packaging/windows/test-icons.py','--exe',exe!,'--window-handle',handle],{windowsHide:true});
 }finally{await cleanup(application,data)}
});

test('独立窗口、单实例、备注提示、原生保存与安全退出',async()=>{
 const port=await freePort(),{application,data,root,args}=await launch('窗口生命周期',port);
 try{
  const page=await application.firstWindow();await page.waitForURL(/\/model\?service=local/,{timeout:60000});
  await expect(page.locator('canvas#c')).toBeVisible();await expect(page.getByText('正在加载管网模型…')).toHaveCount(0);
  expect(await page.evaluate(()=>typeof (window as unknown as {require?:unknown}).require)).toBe('undefined');
  expect(await page.evaluate(()=>typeof window.shadDesktop?.setDirty)).toBe('function');
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const second=spawn(exe!,args,{windowsHide:true,env:cleanEnv,stdio:'ignore'});
  await new Promise<void>(r=>second.once('exit',()=>r()));
  expect(await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().length)).toBe(1);
  const output=path.join(root,'导出.csv');
  await application.evaluate(({dialog},file)=>{dialog.showSaveDialogSync=()=>file},output);
  await page.evaluate(()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['测点,值\n温度,65'],{type:'text/csv'}));a.download='导出.csv';a.click()});
  await expect.poll(async()=>readFile(output,'utf8').catch(()=>'' )).toContain('温度,65');
  await page.getByLabel('运行模式').selectOption('demo');
  await page.goto(`http://127.0.0.1:${port}/diagnosis/REP-20261103-018`);
  const note=page.locator('textarea');await note.fill('退出前尚未保存的备注');
  await application.evaluate(({dialog})=>{(globalThis as any).messages=[];dialog.showMessageBox=async(_win:any,options:any)=>{(globalThis as any).messages.push(options);return {response:0,checkboxChecked:false}}});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.close());
  await expect.poll(()=>application.evaluate(()=>(globalThis as any).messages.length)).toBe(1);
  expect(await application.evaluate(()=>(globalThis as any).messages[0].detail)).toContain('未保存');
  await expect(note).toHaveValue('退出前尚未保存的备注');
  await page.screenshot({path:'verification/desktop-shell/report-close-guard.png',fullPage:true});
  await page.getByRole('button',{name:'保存备注',exact:true}).click();
  for(const [label,extension,signature] of [['Word','docx','PK'],['PDF','pdf','%PDF']]){
    const file=path.join(root,'检测报告.'+extension);
    await application.evaluate(({dialog},target)=>{dialog.showSaveDialogSync=()=>target},file);
    await page.getByRole('button',{name:new RegExp(label!)}).click();
    await expect.poll(async()=>readFile(file).then(b=>b.subarray(0,signature!.length).toString()).catch(()=>''),{timeout:30000}).toBe(signature);
  }
  // Exercise the queued/running exit branch without injecting a fake task into the database.
  await application.evaluate(()=>{(globalThis as any).originalFetch=globalThis.fetch;globalThis.fetch=async()=>({ok:true,json:async()=>({data:{total:1}})}) as any});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.close());
  await expect.poll(()=>application.evaluate(()=>(globalThis as any).messages.length)).toBe(2);
  expect(await application.evaluate(()=>(globalThis as any).messages[1].detail)).toContain('运行或排队');
  await application.evaluate(()=>{globalThis.fetch=(globalThis as any).originalFetch});
  await page.getByRole('link',{name:'管网模型',exact:true}).click();
  await expect(page.locator('canvas#c')).toBeVisible();
  await page.screenshot({path:'verification/desktop-shell/model-window.png',fullPage:true});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.close());
  await new Promise<void>(resolve=>application.process().once('exit',()=>resolve()));
  const status=JSON.parse((await command(backend,['status','--json','--data-dir',data],{windowsHide:true})).stdout);
  expect(status.running).toBe(false);expect(errors).toEqual([]);
 }finally{await cleanup(application,data)}
});

test('端口冲突显示失败提示且退出不影响其他监听程序',async()=>{
 const server=net.createServer();await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
 const port=(server.address() as net.AddressInfo).port;
 const {application,data}=await launch('启动失败',port);
 try{
  const page=await application.firstWindow();await expect(page.locator('#message')).toHaveText('启动失败',{timeout:60000});
  await expect(page.getByRole('button',{name:'重新连接'})).toBeVisible();
  await page.screenshot({path:'verification/desktop-shell/startup-error.png',fullPage:true});
  expect(server.listening).toBe(true);
 }finally{await cleanup(application,data);await new Promise<void>(r=>server.close(()=>r()))}
});

test('复用外部服务、窗口尺寸恢复及显示异常重连',async()=>{
 const root=path.resolve('build/desktop-checks','复用服务-'+Date.now());await mkdir(root,{recursive:true});
 const data=path.join(root,'数据'),profile=path.join(root,'窗口'),port=await freePort();
 const args=['--data-dir',data,'--profile-dir',profile,'--port',String(port)];
 await command(backend,['start','--json','--no-browser','--data-dir',data,'--port',String(port)],{windowsHide:true,timeout:60000});
 let application=await _electron.launch({executablePath:exe!,args,env:cleanEnv,timeout:60000});
 try{
  let page=await application.firstWindow();await page.waitForURL(/\/model\?service=local/,{timeout:60000});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.setSize(1230,760));
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.close());
  await new Promise<void>(r=>application.process().once('exit',()=>r()));
  expect(JSON.parse((await command(backend,['status','--json','--data-dir',data],{windowsHide:true})).stdout).running).toBe(true);
  application=await _electron.launch({executablePath:exe!,args,env:cleanEnv,timeout:60000});
  page=await application.firstWindow();await page.waitForURL(/\/model\?service=local/,{timeout:60000});
  const size=await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.getSize());
  // Windows non-client borders and fractional DPI rounding vary by a few pixels.
  expect(Math.abs(size[0]!-1230)).toBeLessThanOrEqual(8);expect(Math.abs(size[1]!-760)).toBeLessThanOrEqual(8);
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.webContents.forcefullyCrashRenderer());
  // The old Playwright page target stays marked crashed. Inspect the recovered
  // renderer through the live Electron webContents rather than that stale target.
  await expect.poll(()=>application.evaluate(async({BrowserWindow})=>{
    const wc=BrowserWindow.getAllWindows()[0]!.webContents;
    return wc.isCrashed()?'':wc.executeJavaScript('document.getElementById("message")?.textContent');
  }).catch(()=>''),{timeout:15000}).toBe('窗口显示异常');
  await application.evaluate(async({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.webContents.executeJavaScript('document.getElementById("retry").click()'));
  await expect.poll(()=>application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.webContents.getURL()),{timeout:60000}).toContain('/model?service=local');
  await expect.poll(()=>application.evaluate(async({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.webContents.executeJavaScript('!!document.querySelector("canvas#c")')).catch(()=>false)).toBe(true);
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0]!.close());
  await new Promise<void>(r=>application.process().once('exit',()=>r()));
  expect(JSON.parse((await command(backend,['status','--json','--data-dir',data],{windowsHide:true})).stdout).running).toBe(true);
 }finally{await cleanup(application,data)}
});

test('识别旧服务界面，避免新窗口再次打开旧版页面',async()=>{
 const previous=process.env.SHAD_PREVIOUS_BACKEND_EXE;
 test.skip(!previous,'需要提供已保存的旧版后端运行包');
 const root=path.resolve('build/desktop-checks','旧界面识别-'+Date.now());await mkdir(root,{recursive:true});
 const data=path.join(root,'数据'),profile=path.join(root,'窗口'),port=await freePort();
 await command(previous!,['start','--json','--no-browser','--data-dir',data,'--port',String(port)],{windowsHide:true,timeout:60000});
 const application=await _electron.launch({executablePath:exe!,args:['--data-dir',data,'--profile-dir',profile,'--port',String(port)],env:cleanEnv,timeout:60000});
 try{
  const page=await application.firstWindow();await expect(page.locator('#message')).toHaveText('启动失败',{timeout:60000});
  await expect(page.locator('#details')).toContainText('另一版界面');
  expect(JSON.parse((await command(previous!,['status','--json','--data-dir',data],{windowsHide:true})).stdout).running).toBe(true);
 }finally{await cleanup(application,data)}
});
