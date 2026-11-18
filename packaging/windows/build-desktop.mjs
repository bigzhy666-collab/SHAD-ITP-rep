import {packager} from '@electron/packager'
import {cp,mkdir,writeFile,access,readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import path from 'node:path'
import {fileURLToPath} from 'node:url'

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..')
const backend=process.argv[2]
const {version}=JSON.parse(await readFile(path.join(root,'desktop/package.json'),'utf8'))
if(!backend)throw new Error('需要提供本轮生成的后端 SHAD 文件夹。')
const stamp=new Date().toISOString().replace(/[-:]/g,'').replace('T','-').slice(0,15)
const stage=path.join(root,'build','desktop',stamp)
await mkdir(stage,{recursive:true})
await cp(path.join(root,'desktop'),path.join(stage,'app'),{recursive:true,filter:source=>path.basename(source)!=='tests'})
await cp(path.resolve(backend),path.join(stage,'backend'),{recursive:true})
const zipDir=path.join(root,'build/tools/electron-zips')
const zipName='electron-v45.3.2-win32-x64.zip'
const cachedZip=await access(path.join(zipDir,zipName)).then(()=>true).catch(()=>false)
if(cachedZip){
  const expected=JSON.parse(await readFile(path.join(root,'node_modules/electron/checksums.json'),'utf8'))[zipName]
  const actual=createHash('sha256').update(await readFile(path.join(zipDir,zipName))).digest('hex')
  if(actual!==expected)throw new Error('桌面运行环境校验失败，已停止打包。')
}
const result=await packager({
  dir:path.join(stage,'app'),out:path.join(root,'release','desktop',stamp),
  name:'SHAD',platform:'win32',arch:'x64',electronVersion:'45.3.2',
  asar:true,prune:false,icon:path.join(root,'desktop','icon.ico'),
  appVersion:version,buildVersion:version,
  extraResource:[path.join(stage,'backend')],
  ...(cachedZip?{electronZipDir:zipDir}:{}),
  win32metadata:{CompanyName:'SHAD',FileDescription:'SHAD 智慧供热平台',ProductName:'SHAD 智慧供热平台'},
})
for(const output of result){
  // A versioned, explicit icon path also invalidates stale Windows shortcut icons.
  await cp(path.join(root,'desktop/icon.ico'),path.join(output,'resources',`shad-${version}.ico`))
  for(const [file,action] of [['停止SHAD','stop'],['查看状态','status'],['备份数据','backup']]){
    const body=`@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nresources\\backend\\SHAD.exe ${action} %*\r\npause\r\n`
    await writeFile(path.join(output,file+'.cmd'),body)
  }
  await cp(path.join(root,'packaging','windows','使用说明.txt'),path.join(output,'使用说明.txt'))
  console.log('桌面程序已生成：'+output)
}
