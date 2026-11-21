<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'

const segmentId=ref(localStorage.getItem('shad-local-segment')||'seg-1')
const stations=ref<any[]>([])
const stationId=ref(localStorage.getItem('shad-current-station')||'')
const datasets=ref<any[]>([])
const error=ref(''), notice=ref(''), busy=ref(false)

const FIELDS=[
  {key:'outdoor_temperature',label:'室外温度',required:true,unit:'℃'},
  {key:'p_net_supply_temperature',label:'一次侧供水温度',required:true,unit:'℃'},
  {key:'p_net_return_temperature',label:'一次侧回水温度',required:true,unit:'℃'},
  {key:'p_net_meter_heat_power',label:'瞬时热功率',required:true,unit:'kW'},
  {key:'p_net_meter_flow',label:'一次侧瞬时流量',required:true,unit:'L/h'},
  {key:'p_hc1_return_temperature',label:'二次侧采暖回水温度',required:false,unit:'℃'},
  {key:'s_hc1_supply_temperature',label:'二次侧采暖供水温度',required:true,unit:'℃'},
  {key:'s_hc1_supply_temperature_setpoint',label:'二次侧供水温度设定值',required:true,unit:'℃'},
]
const UNITS=['℃','kW','L/h','m3/h','kWh']

const fileName=ref(''), header=ref<string[]>([]), previewRows=ref<string[][]>([]), rowCount=ref(0)
const delimiter=ref(','), timeColumn=ref(''), datasetName=ref(''), timezone='Asia/Shanghai'
const mapping=ref<Record<string,string>>({})
const units=ref<Record<string,string>>({})

const stationLabel=computed(()=>{
  const s=stations.value.find((x:any)=>x.id===stationId.value)
  return s?`${s.name} · ${s.code}`:'未选择换热站'
})

async function getJson(url:string,init?:RequestInit){
  const r=await fetch(url,init)
  const b=await r.json().catch(()=>({}))
  if(!r.ok||b.error)throw new Error(b?.error?.message||`请求失败 (${r.status})`)
  return b.data
}
function qs(o:Record<string,unknown>){return Object.entries(o).map(([k,v])=>`${k}=${encodeURIComponent(String(v))}`).join('&')}

async function loadStations(){
  const d=await getJson('/api/stations?'+qs({segmentId:segmentId.value,page:1,pageSize:500}))
  stations.value=d.items||[]
  if(!stationId.value||!stations.value.some((s:any)=>s.id===stationId.value))stationId.value=stations.value[0]?.id??''
}

async function loadDatasets(){
  datasets.value=[]
  if(!stationId.value)return
  const d=await getJson('/api/datasets?'+qs({stationId:stationId.value,page:1,pageSize:500}))
  datasets.value=d.items||[]
}

function guess(field:any,cols:string[]){
  const exact=cols.find(c=>c.trim()===field.key)
  if(exact)return exact
  return cols.find(c=>c.includes(field.label))||''
}

async function pickFile(e:Event){
  const input=e.target as HTMLInputElement
  const file=input.files?.[0]
  if(!file)return
  fileName.value=file.name
  datasetName.value=file.name.replace(/\.csv$/i,'')
  busy.value=true;error.value=''
  try{
    const text=await file.text()
    const sep=delimiter.value==='\\t'?'\t':delimiter.value
    const lines=text.split(/\r?\n/).filter(l=>l.trim())
    if(!lines.length)throw new Error('CSV 为空')
    header.value=lines[0].split(sep).map(s=>s.trim().replace(/^"|"$/g,''))
    previewRows.value=lines.slice(1,6).map(l=>l.split(sep))
    rowCount.value=lines.length-1
    FIELDS.forEach(f=>{
      mapping.value[f.key]=guess(f,header.value)
      units.value[f.key]=f.unit
    })
    timeColumn.value=header.value.find(c=>/时间|time/i.test(c))??header.value[0]
  }catch(ex:any){error.value=ex.message}
  finally{busy.value=false}
}

function downloadTemplate(){
  const cols=['时间',...FIELDS.map(f=>f.key)]
  const csv='\uFEFF'+cols.join(',')+'\n'
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'})
  const a=document.createElement('a')
  a.href=URL.createObjectURL(blob)
  a.download='换热站运行数据_空白模板.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function doImport(){
  error.value='';notice.value=''
  const file=(document.getElementById('csvFile') as HTMLInputElement)?.files?.[0]
  if(!file)return error.value='请先选择 CSV 文件'
  const missing=FIELDS.filter(f=>f.required&&!mapping.value[f.key])
  if(missing.length)return error.value='缺少必需测点映射：'+missing.map(f=>f.label).join('、')
  busy.value=true
  try{
    const columnMapping:Record<string,string>={}
    const sourceUnits:Record<string,string>={}
    FIELDS.forEach(f=>{
      if(mapping.value[f.key]){columnMapping[f.key]=mapping.value[f.key];sourceUnits[f.key]=units.value[f.key]||f.unit}
    })
    const manifest={name:datasetName.value||fileName.value,stationId:stationId.value,timezone,encoding:'utf-8',
      delimiter:delimiter.value==='\\t'?'\t':delimiter.value,timeColumn:timeColumn.value,columnMapping,sourceUnits}
    const body=new FormData()
    body.append('file',file)
    body.append('manifest',JSON.stringify(manifest))
    const d=await getJson('/api/datasets/import',{method:'POST',body})
    notice.value=`导入成功：${d.name}（${d.normalizedRowCount} 行，状态 ${d.status}）`
    localStorage.setItem('shad-current-station',stationId.value)
    localStorage.setItem('shad-last-import-station',stationId.value)
    await loadDatasets()
  }catch(e:any){error.value=e.message}
  finally{busy.value=false}
}

onMounted(async()=>{
  const sidebar=document.querySelector('.sidebar-object') as HTMLElement|null
  if(sidebar){
    const strong=sidebar.querySelector('strong')?.textContent?.trim()??''
    const sel=document.querySelector('select[aria-label="本机管段选择"]') as HTMLSelectElement|null
    if(sel&&strong){const hit=Array.from(sel.options).find(o=>o.value&&strong.includes(o.textContent!.trim()));if(hit)sel.value=hit.value}
  }
  try{await loadStations();await loadDatasets()}catch(e:any){error.value=e.message}
})
</script>

<template>
<div class="page-stack local-page">
<section class="panel"><header class="panel-heading"><h2>企业 / 供热管网 / 管段选择</h2><div class="panel-tools"></div></header><div class="panel-body"><!----><!----><div class="local-form-grid"><label>企业<select aria-label="本机企业选择"><option value="">请选择企业</option><option value="ent-1">北方热力有限责任公司</option><option value="ent-2">城东热力分公司</option></select></label><label>供热管网<select aria-label="本机供热管网选择"><option value="">请选择管网</option><option value="net-1">城北主力供热网</option><option value="net-2">城西供热网</option></select></label><label>管段<select aria-label="本机管段选择"><option value="">请选择管段</option><option value="seg-1">1号二次供热管段</option><option value="seg-2">2号一次供热管段</option><option value="seg-3">3号末端支路</option></select></label><button class="primary">确认选择</button></div><p class="muted">组织数据由本机后端保存；停用上级后，其下管段不可选，历史记录保留。</p></div></section>
  <section class="panel">
    <header class="panel-heading"><h2>管段关联换热站</h2><div class="panel-tools"></div></header>
    <div class="panel-body">
      <p>当前管段：1号二次供热管段</p>
      <p class="muted">模型检测换热站设备及控制状态，不检测埋地管道本体缺陷。</p>
      <label>换热站
        <select v-model="stationId" aria-label="关联换热站" @change="loadDatasets">
          <option value="">请选择换热站</option>
          <option v-for="s in stations" :key="s.id" :value="s.id">{{s.name}} · {{s.code}}</option>
        </select>
      </label>
    </div>
  </section>

  <section class="panel">
    <header class="panel-heading"><h2>本站运行数据导入</h2><div class="panel-tools"></div></header>
    <div class="panel-body">
      <p>导入 <strong>{{stationLabel}}</strong> 的运行数据</p>
      <p class="muted">CSV 需使用 UTF-8 编码；确认测点、时间列与单位，转换和质量校验由本机后端执行。</p>
      <div class="local-form-grid">
        <label>运行数据 CSV
          <input id="csvFile" type="file" accept=".csv,text/csv" @change="pickFile" />
        </label>
        <label>分隔符
          <select v-model="delimiter"><option value=",">逗号</option><option value=";">分号</option><option value="\t">制表符</option></select>
        </label>
        <label>数据集名称<input v-model="datasetName" type="text" placeholder="例如 1#换热站_2016-11-03至12-02_故障" /></label>
        <label>时间列
          <select v-model="timeColumn"><option value="">请选择</option><option v-for="c in header" :key="c" :value="c">{{c}}</option></select>
        </label>
      </div>
      <p class="muted">数据时区：{{timezone}}；预览 {{rowCount}} 行</p>

      <div class="table-wrap" v-if="header.length">
        <table>
          <thead><tr><th>模型必需测点</th><th>CSV 原始列</th><th>原始单位（请确认）</th></tr></thead>
          <tbody>
            <tr v-for="f in FIELDS" :key="f.key">
              <td>{{f.label}}<span v-if="!f.required" class="muted">（可选）</span></td>
              <td>
                <select v-model="mapping[f.key]">
                  <option value="">不导入</option>
                  <option v-for="c in header" :key="c" :value="c">{{c}}</option>
                </select>
              </td>
              <td>
                <select v-model="units[f.key]">
                  <option v-for="u in UNITS" :key="u" :value="u">{{u}}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="muted">可选测点（有数据时建议一并导入）：二次侧采暖回水温度</p>
      <p class="muted">
        <a href="#" @click.prevent="downloadTemplate">下载空白字段模板</a>
      </p>

      <details v-if="previewRows.length">
        <summary>查看前 {{previewRows.length}} 行原始数据</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th v-for="c in header" :key="c">{{c}}</th></tr></thead>
            <tbody><tr v-for="(r,i) in previewRows" :key="i"><td v-for="(v,j) in r" :key="j">{{v}}</td></tr></tbody>
          </table>
        </div>
      </details>

      <p v-if="busy" class="local-notice" role="status">正在处理…</p>
      <p v-if="notice" class="local-notice" role="status">{{notice}}</p>
      <p v-if="error" class="error" role="alert">{{error}}</p>
      <button class="primary" :disabled="busy||!fileName" @click="doImport">导入并校验</button>
    </div>
  </section>

  <section class="panel">
    <header class="panel-heading"><h2>历史数据集</h2><div class="panel-tools"><button class="secondary" @click="loadDatasets">刷新数据集</button></div></header>
    <div class="panel-body">
      <div class="table-wrap">
        <table>
          <thead><tr><th>名称 / 版本</th><th>点数</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="d in datasets" :key="d.id">
              <td>{{d.name}} / {{d.version}}</td>
              <td>{{d.normalizedRowCount??'—'}}</td>
              <td><RouterLink :to="`/detections?stationId=${stationId}&datasetId=${d.id}`">查看采样与检测</RouterLink></td>
            </tr>
            <tr v-if="!datasets.length"><td colspan="3" class="empty">当前换热站暂无数据集。</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
<section class="panel"><header class="panel-heading"><h2>组织维护</h2><div class="panel-tools"></div></header><div class="panel-body"><div class="local-form-grid"><label>管理层级<select aria-label="组织管理层级"><option value="enterprises">企业</option><option value="networks">供热管网</option><option value="segments">管段</option></select></label><label>搜索名称或编码<input aria-label="搜索组织"></label><button>新增企业</button><button>刷新组织</button></div><form class="local-form-grid mt"><label>企业名称<input aria-label="组织名称" maxlength="200" required></label><label>编码<input aria-label="组织编码" maxlength="100" pattern="[A-Za-z0-9_.-]+" required></label><!----><!----><button class="primary" disabled>创建组织</button></form><p class="muted mt">编码使用字母、数字、点、下划线或短横线。已有对象不更换上级，避免改变站点归属。停用不会删除历史；停用上级后，下属对象暂停创建新检测。</p><!----><!----><div class="table-wrap mt"><table><thead><tr><th>名称</th><th>编码</th><th>状态</th><th>操作</th></tr></thead><tbody><tr><td>北方热力有限责任公司</td><td>ENT-001</td><td>启用</td><td><button aria-label="编辑组织 北方热力有限责任公司">编辑</button></td></tr><tr><td>城东热力分公司</td><td>ENT-002</td><td>启用</td><td><button aria-label="编辑组织 城东热力分公司">编辑</button></td></tr><!----></tbody></table></div></div></section>
</div>
</template>
