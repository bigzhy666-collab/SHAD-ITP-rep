const {app, BrowserWindow, Menu, ipcMain, dialog, screen, shell} = require('electron');
const {execFile, spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {createHash} = require('node:crypto');

app.setName('SHAD');
app.setAppUserModelId('SHAD.Desktop');
function argument(name) {const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];}
const localRoot=process.env.LOCALAPPDATA || app.getPath('appData');
const dataDir=path.resolve(argument('--data-dir') || process.env.SHAD_DATA_DIR || path.join(localRoot,'SHAD','data'));
app.setPath('userData',path.resolve(argument('--profile-dir') || path.join(localRoot,'SHAD','desktop')));
const profile=app.getPath('userData');fs.mkdirSync(profile,{recursive:true});
const port=Number(argument('--port') || 8765);
const backend=app.isPackaged?path.join(process.resourcesPath,'backend','SHAD.exe'):process.env.SHAD_BACKEND_EXE;
const shellFile=path.join(__dirname,'shell.html');
const shellUrl=pathToFileURL(shellFile).href;
const iconFile=app.isPackaged?path.join(process.resourcesPath,`shad-${app.getVersion()}.ico`):path.join(__dirname,'icon.ico');
const ownerFile=path.join(profile,'owned-service.json'),boundsFile=path.join(profile,'window.json');
let win, guard, current, ownedInstance, starting=false, exiting=false, confirmedQuit=false, state={message:'正在启动本机服务…'};
const dirty=new Set();
function log(message){try{fs.appendFileSync(path.join(profile,'desktop.log'),new Date().toISOString()+' '+String(message)+'\n');}catch{console.error(String(message));}}
function readJson(file){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch{return null;}}
function writeJson(file,value){fs.writeFileSync(file,JSON.stringify(value));}
function validUrl(url){return url===shellUrl || (current && new URL(url).origin===current.url);}
function trusted(event){try{return event.sender===win?.webContents && event.senderFrame===win.webContents.mainFrame && validUrl(event.senderFrame.url);}catch{return false;}}
function run(action,extra=[]){
  return new Promise((resolve,reject)=>{
    execFile(backend,[action,'--json','--data-dir',dataDir,...extra],{windowsHide:true,timeout:70000,maxBuffer:1024*1024},(error,stdout,stderr)=>{
      if(error)return reject(new Error(stderr.trim() || error.message));
      try{resolve(JSON.parse(stdout));}catch{reject(new Error('本机服务返回格式异常，请查看日志。'));}
    });
  });
}
function showState(value){state=value;win?.webContents.send('shad:state',state);}
async function shellState(value){showState(value);if(win.webContents.getURL()!==shellUrl)await win.loadFile(shellFile);}
function ownInstance(value){const owner=readJson(ownerFile);return !!value?.instanceId&&(ownedInstance===value.instanceId || (owner?.instanceId===value.instanceId && owner?.dataDir===dataDir));}
async function start(){
  if(starting || exiting)return;starting=true;
  await shellState({message:'正在启动本机服务…',details:'界面、模型和数据均在本机运行。'});
  try{
    if(!backend || !fs.existsSync(backend))throw new Error('找不到本机服务程序，请重新安装 SHAD。');
    if(!Number.isInteger(port)||port<1||port>65535)throw new Error('启动端口无效。');
    if(!guard){
      guard=spawn(backend,['guard'],{windowsHide:true,stdio:['pipe','ignore','pipe']});
      guard.on('error',error=>{log(error.message);guard=null;});
    }
    current=await run('start',['--no-browser','--port',String(port)]);
    if(!current.running || !/^http:\/\/127\.0\.0\.1:\d+$/.test(current.url))throw new Error('本机服务未就绪。');
    if(!current.reused){ownedInstance=current.instanceId;try{writeJson(ownerFile,{instanceId:current.instanceId,dataDir});}catch(error){log(error.message);}}
    if(current.reused){
      const expected=fs.readFileSync(path.join(path.dirname(backend),'_internal','dist','index.html'));
      const response=await fetch(current.url+'/index.html',{signal:AbortSignal.timeout(5000),redirect:'error'});
      const served=Buffer.from(await response.arrayBuffer());
      const hash=value=>createHash('sha256').update(value).digest('hex');
      if(!response.ok || hash(served)!==hash(expected))throw new Error('已有本机服务正在使用另一版界面。请先退出旧版 SHAD 或停止旧版服务，再重新连接；没有停止原服务或更改业务数据。');
    }
    await win.loadURL(current.url+'/model?service=local');
  }catch(error){log(error.stack);await shellState({message:'启动失败',details:error.message+'\n日志位置：'+path.join(profile,'desktop.log'),retry:true});}
  finally{starting=false;}
}
async function activeTasks(){
  if(!current)return 0;
  const counts=await Promise.all(['queued','running'].map(async status=>{
    const response=await fetch(current.url+'/api/detections?status='+status+'&pageSize=1',{signal:AbortSignal.timeout(4000),redirect:'error'});
    if(!response.ok)throw new Error('无法查询检测任务状态');
    return (await response.json()).data.total;
  }));
  return counts.reduce((a,b)=>a+b,0);
}
async function quit(){
  if(exiting || confirmedQuit)return;exiting=true;
  try{
    if(starting){await dialog.showMessageBox(win,{type:'info',message:'本机服务仍在启动，请稍后再退出。'});return;}
    let tasks=0,unknown=false;
    try{tasks=await activeTasks();}catch{unknown=true;}
    if(dirty.size || tasks || (unknown && current)){
      const detail=[dirty.size?'有未保存的报告备注，退出会放弃这些修改。':'',tasks?'存在运行或排队中的检测。退出可能中断检测，历史保留；排队任务会在下次启动继续，已中断任务可重试。':'',unknown?'无法确认后台任务状态，请确认是否继续退出。':''].filter(Boolean).join('\n');
      const choice=await dialog.showMessageBox(win,{type:'question',message:'确认退出 SHAD？',detail,buttons:['返回软件','退出软件'],defaultId:0,cancelId:0,noLink:true});
      if(choice.response!==1)return;
    }
    const owned=ownInstance(current);
    if(owned){
      await shellState({message:'正在安全停止本机服务…',details:'请稍候，正在保存任务状态。'});
      await run('stop',['--expected-instance',current.instanceId]);
      try{fs.rmSync(ownerFile,{force:true});}catch(error){log(error.message);}
    }
    confirmedQuit=true;guard?.stdin.end();app.quit();
  }catch(error){log(error.stack);await dialog.showMessageBox(win,{type:'error',message:'尚未完成安全退出',detail:error.message+'\n请稍后再次关闭窗口重试。'});if(current?.running)await win.loadURL(current.url+'/model?service=local').catch(()=>{});}
  finally{exiting=false;}
}
function createWindow(){
  const saved=readJson(boundsFile);const restore=saved?.bounds;
  const visible=restore && [restore.x,restore.y,restore.width,restore.height].every(Number.isFinite) && restore.width>=1024 && restore.height>=700 && screen.getAllDisplays().some(d=>{
    const a=d.workArea;return restore.x+restore.width>a.x+100&&restore.x<a.x+a.width-100&&restore.y+restore.height>a.y+100&&restore.y<a.y+a.height-100;
  });
  let bounds={width:1440,height:900};
  if(visible){const a=screen.getDisplayMatching(restore).workArea;const width=Math.min(restore.width,a.width),height=Math.min(restore.height,a.height);bounds={width,height,x:Math.max(a.x,Math.min(restore.x,a.x+a.width-width)),y:Math.max(a.y,Math.min(restore.y,a.y+a.height-height))};}
  win=new BrowserWindow({...bounds,minWidth:1024,minHeight:700,show:false,title:'SHAD 智慧供热平台',icon:iconFile,backgroundColor:'#f8fafc',webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true}});
  if(process.platform==='win32')win.setAppDetails({appId:'SHAD.Desktop',appIconPath:iconFile,appIconIndex:0});
  win.once('ready-to-show',()=>{if(saved?.maximized)win.maximize();win.show();});
  win.on('close',event=>{try{writeJson(boundsFile,{bounds:win.getNormalBounds(),maximized:win.isMaximized()});}catch(error){log(error.message);}if(!confirmedQuit){event.preventDefault();void quit();}});
  win.webContents.on('will-navigate',(event,url)=>{try{if(!validUrl(url))event.preventDefault();}catch{event.preventDefault();}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  win.webContents.session.setPermissionCheckHandler(()=>false);
  win.webContents.session.webRequest.onHeadersReceived((details,callback)=>{
    const headers={...details.responseHeaders};
    if(current && details.url.startsWith(current.url+'/'))headers['Content-Security-Policy']=["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-src 'none'"];
    callback({responseHeaders:headers});
  });
  win.webContents.on('render-process-gone',()=>{dirty.clear();void shellState({message:'窗口显示异常',details:'可重新连接本机服务，已保存的数据不受影响。',retry:true});});
  win.webContents.session.on('will-download',(event,item,contents)=>{
    const name=path.basename(item.getFilename());const ext=path.extname(name).toLowerCase();
    if(contents!==win.webContents || !['.pdf','.docx','.csv','.zip'].includes(ext)){event.preventDefault();return;}
    const target=dialog.showSaveDialogSync(win,{title:'保存导出文件',defaultPath:path.join(app.getPath('downloads'),name),filters:[{name:'导出文件',extensions:[ext.slice(1)]}]});
    if(!target){item.cancel();return;}item.setSavePath(target);
    item.once('done',(_event,status)=>{if(status!=='completed'&&status!=='cancelled')void dialog.showMessageBox(win,{type:'error',message:'文件保存失败，请重新导出。'});});
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {label:'软件',submenu:[{label:'退出 SHAD',click:()=>void quit()}]},
    {label:'查看',submenu:[{label:'刷新数据',accelerator:'CmdOrCtrl+R',click:()=>win.webContents.send('shad:refresh')},{role:'togglefullscreen'},{role:'resetZoom'},{role:'zoomIn'},{role:'zoomOut'}]},
    {label:'帮助',submenu:[{label:'打开日志文件夹',click:()=>void shell.openPath(profile)},{label:'关于 SHAD',click:()=>void dialog.showMessageBox(win,{message:`SHAD 智慧供热平台 ${app.getVersion()}`,detail:'本机离线运行 · 原因及方案诊断未启用'})}]},
  ]));
}
if(!app.requestSingleInstanceLock())app.quit();
else{
  app.on('second-instance',()=>{if(win){if(win.isMinimized())win.restore();win.show();win.focus();}});
  app.on('before-quit',event=>{if(!confirmedQuit){event.preventDefault();void quit();}});
  app.on('window-all-closed',()=>{if(confirmedQuit)app.quit();});
  ipcMain.on('shad:dirty',(event,value)=>{if(trusted(event)&&typeof value?.id==='string'&&value.id.length<100&&typeof value.dirty==='boolean'){if(value.dirty)dirty.add(value.id);else dirty.delete(value.id);}});
  ipcMain.on('shad:retry',event=>{if(trusted(event)&&event.senderFrame.url===shellUrl)void start();});
  ipcMain.on('shad:shell-ready',event=>{if(trusted(event))win.webContents.send('shad:state',state);});
  app.whenReady().then(()=>{createWindow();return start();}).catch(error=>{log(error.stack);dialog.showErrorBox('SHAD 启动失败',error.message);confirmedQuit=true;guard?.stdin.end();app.quit();});
}
