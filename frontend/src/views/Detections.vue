<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,nextTick} from 'vue'
import * as echarts from 'echarts/core'
import {LineChart,ScatterChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,DataZoomComponent,LegendComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'

echarts.use([LineChart,ScatterChart,GridComponent,TooltipComponent,DataZoomComponent,LegendComponent,CanvasRenderer])

const FIELDS:Record<string,string>={
  outdoor_temperature:'室外温度',
  p_net_supply_temperature:'一次侧供水温度',
  p_net_return_temperature:'一次侧回水温度',
  p_net_meter_heat_power:'瞬时热功率',
  p_net_meter_flow:'一次侧瞬时流量',
  p_hc1_return_temperature:'二次侧采暖回水温度',
  s_hc1_supply_temperature:'二次侧采暖供水温度',
  s_hc1_supply_temperature_setpoint:'二次侧供水温度设定值',
}
const PAGE_SAMPLES=6, PAGE_HISTORY=3

const segmentId=ref(localStorage.getItem('shad-local-segment')||'seg-1')
const stations=ref<any[]>([])
const stationId=ref(localStorage.getItem('shad-current-station')||'')
const datasets=ref<any[]>([])
const datasetId=ref('')
const start=ref(''), end=ref('')
const allSamples=ref<any[]>([]), sampleTotal=ref(0), samplePage=ref(1), anomalyTs=ref<Set<string>>(new Set()), issues=ref<string[]>([])
const parameter=ref('outdoor_temperature')
const task=ref<any>(null), events=ref<any[]>([])
const history=ref<any[]>([]), historyPage=ref(1)
const busy=ref(false), message=ref(''), error=ref('')
const orgCtx=ref<{enterpriseId:string;networkId:string}>({enterpriseId:'',networkId:''})
const chartEl=ref<HTMLElement>()
let chart:echarts.ECharts|undefined

const samplePages=computed(()=>Math.max(1,Math.ceil(sampleTotal.value/PAGE_SAMPLES)))
const samples=computed(()=>allSamples.value.slice((samplePage.value-1)*PAGE_SAMPLES,samplePage.value*PAGE_SAMPLES))
const historyPages=computed(()=>Math.max(1,Math.ceil(history.value.length/PAGE_HISTORY)))
const params=computed(()=>stations.value.map((s:any)=>({id:s.id,name:s.name,code:s.code})))
const stationLabel=computed(()=>{
  const s=params.value.find((x:any)=>x.id===stationId.value)
  return s?`${s.name} · ${s.code}`:'请选择换热站'
})

async function getJson(url:string,opt?:RequestInit){
  const r=await fetch(url,opt)
  const body=await r.json().catch(()=>({}))
  if(!r.ok||body.error)throw new Error(body?.error?.message||`请求失败 (${r.status})`)
  return body.data
}
function qs(o:Record<string,unknown>){return Object.entries(o).map(([k,v])=>`${k}=${encodeURIComponent(String(v))}`).join('&')}
function toLocal(iso:string){return iso?iso.slice(0,16):''}
function fmtNum(v:any){return typeof v==='number'?Math.round(v*10)/10:v??'缺失'}
function fmtTableTime(iso:string){
  if(!iso)return ''
  const d=new Date(iso)
  const p=(n:number)=>String(n).padStart(2,'0')
  return `${d.getFullYear()}/${d.getMonth()+1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function qualityText(q:string){return q==='valid'?'有效':q==='missing'?'缺失':'可疑'}
function unitOf(field:string){
  const map:Record<string,string>={outdoor_temperature:'℃',p_net_supply_temperature:'℃',p_net_return_temperature:'℃',
    p_net_meter_heat_power:'kW',p_net_meter_flow:'L/h',p_hc1_return_temperature:'℃',s_hc1_supply_temperature:'℃',
    s_hc1_supply_temperature_setpoint:'℃'}
  return map[field]??''
}
function toIso(local:string){
  if(!local)return ''
  if(/[+-]\d{2}:\d{2}$/.test(local))return local
  const withSeconds=local.length===16?local+':00':local
  return withSeconds+'+08:00'
}

async function loadOrg(){
  try{
    const d=await getJson('/api/organizations')
    const seg=(d.segments||[]).find((x:any)=>x.id===segmentId.value)
    const net=(d.networks||[]).find((x:any)=>x.id===seg?.networkId)
    orgCtx.value={networkId:net?.id??'',enterpriseId:net?.enterpriseId??''}
  }catch{}
}

async function loadStations(){
  const d=await getJson('/api/stations?'+qs({segmentId:segmentId.value,page:1,pageSize:500}))
  stations.value=d.items||[]
  if(!stationId.value||!stations.value.some((s:any)=>s.id===stationId.value)){
    stationId.value=stations.value[0]?.id??''
  }
}

async function loadDatasets(){
  datasets.value=[]
  if(!stationId.value)return
  const d=await getJson('/api/datasets?'+qs({stationId:stationId.value,page:1,pageSize:500}))
  datasets.value=(d.items||[]).filter((x:any)=>x.status==='ready')
  datasetId.value=datasets.value[0]?.id??''

  // 传感器检查提示：取自数据集 sensorQuality.findings
  const labels:Record<string,string>={
    p_net_meter_heat_power:'瞬时热功率传感器检查',p_net_meter_flow:'瞬时流量传感器检查',
    outdoor_temperature:'室外温度传感器检查',p_net_supply_temperature:'一次侧供水温度传感器检查',
    p_net_return_temperature:'一次侧回水温度传感器检查',p_hc1_return_temperature:'二次侧回水温度传感器检查',
    s_hc1_supply_temperature:'二次侧供水温度传感器检查',s_hc1_supply_temperature_setpoint:'供水温度设定值传感器检查',
  }
  const findings=((datasets.value[0]?.sensorQuality?.findings||[]) as any[])
  if(findings.length){
    issues.value=findings.map((f:any)=>{
      const name=labels[f.field]??(f.field+'传感器检查')
      const why=(f.reasons||[]).join('、')
      return `${name}：${why}。请结合现场工况核查。`
    })
  }else{
    issues.value=((datasets.value[0]?.issues||[]) as any[]).filter((x:any)=>!x.blocking).map((x:any)=>x.message)
  }
}

async function loadSamples(){
  allSamples.value=[];sampleTotal.value=0
  if(!datasetId.value||!start.value||!end.value)return
  const rows:any[]=[]
  for(let page=1;page<=4;page++){
    const d=await getJson(`/api/datasets/${datasetId.value}/samples?`+qs({
      start:toIso(start.value),end:toIso(end.value),fields:Object.keys(FIELDS).join(','),page,pageSize:500,
    }))
    const items=d.items||[]
    rows.push(...items)
    if(rows.length>=(d.total??0)||items.length<500)break
  }
  allSamples.value=rows
  sampleTotal.value=rows.length
  await nextTick();drawChart();bindWheel()
}

function drawChart(){
  if(!chartEl.value)return
  // 重新渲染前先销毁旧实例，避免画到已脱离文档的 canvas 上
  if(chart){chart.dispose();chart=undefined}
  chart=echarts.init(chartEl.value)
  const field=parameter.value
  const label=FIELDS[field]??'数值'
  const line=allSamples.value.map((s:any)=>[s.timestamp,s.values?.[field]??null])

  // 异常点：只标每段超阈的起点（上升沿），避免整条曲线被红点覆盖
  const dots:any[]=[]
  const rows=allSamples.value
  for(let i=0;i<rows.length;i++){
    const cur=anomalyTs.value.has(rows[i].timestamp)
    const prev=i>0?anomalyTs.value.has(rows[i-1].timestamp):false
    if(cur&&!prev){
      const v=rows[i].values?.[field]
      if(v!=null)dots.push([rows[i].timestamp,v])
    }
  }

  const axisLabel=(v:number)=>{
    const d=new Date(v)
    if(d.getDate()===1) return (d.getMonth()+1)+'月'
    return String(d.getDate())
  }
  chart.setOption({
    grid:{left:56,right:24,top:56,bottom:56},
    tooltip:{trigger:'axis'},
    legend:{
      data:[label,'异常点'],top:6,left:'center',itemWidth:10,itemHeight:10,itemGap:18,
      icon:'circle',textStyle:{fontSize:12,color:'#475569'},
    },
    dataZoom:[{type:'inside'},{type:'slider',start:0,end:100,height:16,bottom:8}],
    xAxis:{
      type:'time',axisTick:{show:false},
      axisLine:{lineStyle:{color:'#e2e8f0'}},splitLine:{show:false},
      axisLabel:{fontSize:11,color:'#64748b',formatter:axisLabel},
    },
    yAxis:{
      name:'℃',nameLocation:'end',nameGap:14,nameTextStyle:{fontSize:11,color:'#64748b',align:'left'},
      type:'value',min:0,interval:3,
      axisLabel:{fontSize:11,color:'#64748b'},
      axisLine:{show:false},axisTick:{show:false},
      splitLine:{lineStyle:{color:'#eef2f6'}},
    },
    series:[
      {name:label,type:'line',showSymbol:false,lineStyle:{width:1.5,color:'#2563eb'},data:line},
      {name:'异常点',type:'scatter',symbolSize:5,itemStyle:{color:'#DC2626'},
        data:dots.length?dots:[[allSamples.value[0]?.timestamp??0,null]]},
    ],
  },true)
  chart.resize()
}

async function ensureDetection(){
  task.value=null;events.value=[]
  try{
    const list=await getJson('/api/detections?'+qs({segmentId:segmentId.value,page:1,pageSize:500}))
    const found=(list.items||[]).find((t:any)=>t.contextSnapshot?.station?.id===stationId.value
      && t.datasetId===datasetId.value && t.status==='success')
    if(found){task.value=found}
    else{
      const body={
        name:`${stationLabel.value} 运行状态检测`,
        context:{enterpriseId:'',networkId:'',segmentId:segmentId.value,stationId:stationId.value},
        datasetId:datasetId.value,
        modelId:'',modelVersion:'',
        range:{start:toIso(start.value),end:toIso(end.value)},
      }
      const models=await getJson('/api/models?'+qs({stationId:stationId.value,page:1,pageSize:500}))
      const model=(models.items||[]).find((m:any)=>m.status==='ready')
      if(!model)throw new Error('该站没有可用模型')
      body.modelId=model.id;body.modelVersion=model.version
      body.context.enterpriseId=orgCtx.value.enterpriseId
      body.context.networkId=orgCtx.value.networkId
      task.value=await getJson('/api/detections',{
        method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},
        body:JSON.stringify(body),
      })
      for(let i=0;i<40;i++){
        await new Promise(r=>setTimeout(r,700))
        const t=await getJson(`/api/detections/${task.value.id}`)
        task.value=t
        if(t.status==='success'||t.status==='failed')break
      }
    }
    if(task.value?.status==='success'){
      const ev=await getJson(`/api/detections/${task.value.id}/events?`+qs({page:1,pageSize:500}))
      events.value=ev.items||[]
      // 分页取全量点，标记点级超阈（alarm）时刻
      const set:Set<string>=new Set()
      for(let page=1;page<=4;page++){
        let ok=false
        for(let attempt=0;attempt<3&&!ok;attempt++){
          try{
            const pts=await getJson(`/api/detections/${task.value.id}/points?`+qs({page,pageSize:500}))
            ;(pts.items||[]).forEach((p:any)=>{if(p.confirmed)set.add(p.timestamp)})
            ok=true
            if((pts.items||[]).length<500)page=9
          }catch(e:any){(window as any).__pts={page,error:String(e?.message||e)};await new Promise(r=>setTimeout(r,600))}
        }
        if(!ok)break
      }
      anomalyTs.value=set
    }
  }catch(e:any){error.value=e.message}
}

async function loadHistory(){
  const d=await getJson('/api/detections?'+qs({segmentId:segmentId.value,page:1,pageSize:500}))
  history.value=d.items||[]
  if(historyPage.value>historyPages.value)historyPage.value=1
}

function saveSelection(){
  try{
    localStorage.setItem('shad-detection-form',JSON.stringify({
      stationId:stationId.value,datasetId:datasetId.value,start:start.value,end:end.value,parameter:parameter.value,
    }))
  }catch{}
}
function restoreSelection(){
  try{
    const raw=localStorage.getItem('shad-detection-form')
    if(!raw)return null
    return JSON.parse(raw)
  }catch{return null}
}

async function runAll(){
  error.value='';message.value=''
  busy.value=true
  const t0=Date.now()
  try{
    const saved=restoreSelection()
    await loadDatasets()
    const prefer=saved&&saved.stationId===stationId.value?datasets.value.find((d:any)=>d.id===saved.datasetId):null
    if(prefer)datasetId.value=prefer.id
    const ds=datasets.value.find((d:any)=>d.id===datasetId.value)??datasets.value[0]
    if(ds){
      start.value=(saved&&saved.datasetId===ds.id&&saved.start)?saved.start:toLocal(ds.start)
      end.value=(saved&&saved.datasetId===ds.id&&saved.end)?saved.end:toLocal(ds.end)
    }
    if(saved&&saved.parameter)parameter.value=saved.parameter
    saveSelection();
    await loadSamples()
    await ensureDetection()
    await nextTick()
    drawChart()      // 异常点要等检测结果回来后再画一次
    await loadHistory()
    const wait=Math.max(0,500-(Date.now()-t0))
    if(wait)await new Promise(r=>setTimeout(r,wait))
  }finally{busy.value=false}
}

function addToPending(){
  if(!task.value||!events.value.length)return
  try{
    const box=JSON.parse(localStorage.getItem('shad-pending-box')||'[]')
    const item={key:task.value.id,taskId:task.value.id,taskName:task.value.name,
      station:task.value.contextSnapshot?.station?.name??'',
      segment:task.value.contextSnapshot?.segment?.name??'',
      eventIds:events.value.map((e:any)=>e.id),eventCount:events.value.length,addedAt:Date.now()}
    const rest=box.filter((x:any)=>x.key!==item.key)
    localStorage.setItem('shad-pending-box',JSON.stringify([item,...rest]))
    message.value=`已加入待处理异常集：${item.eventCount} 条异常（6 秒后自动消失）`
    setTimeout(()=>{message.value=''},6000)
  }catch{}
}

function viewTask(t:any){
  location.href=`/diagnosis?detectionId=${encodeURIComponent(t.id)}`
}

async function changeStation(){
  window.scrollTo(0,0)
  localStorage.setItem('shad-current-station',stationId.value)
  localStorage.setItem('shad-current-station',stationId.value)
  samplePage.value=1;historyPage.value=1
  await runAll()
}
async function changeParam(){await nextTick();drawChart()}
async function page(dir:number){samplePage.value+=dir;await loadSamples()}

let ro:ResizeObserver|undefined
let zoomStart=0, zoomEnd=100
function bindWheel(){
  const el=chartEl.value
  if(!el)return
  el.addEventListener('wheel',(e:WheelEvent)=>{
    if(!chart)return
    e.preventDefault()
    const step=e.deltaY>0?5:-5              // 上划（deltaY<0）放大
    const span=zoomEnd-zoomStart
    const next=Math.min(100,Math.max(5,span+step))
    const center=(zoomStart+zoomEnd)/2
    zoomStart=Math.max(0,Math.min(100-next,center-next/2))
    zoomEnd=zoomStart+next
    chart.setOption({dataZoom:[{type:'inside',start:zoomStart,end:zoomEnd,disabled:true}]})
  },{passive:false})
}
onMounted(async()=>{
  window.scrollTo(0,0)
  await loadOrg()
  try{await loadStations()}catch(e:any){error.value=e.message}
  if(stationId.value)await changeStation()
  ro=new ResizeObserver(()=>chart?.resize())
  if(chartEl.value)ro.observe(chartEl.value)
})
onBeforeUnmount(()=>{ro?.disconnect();chart?.dispose()})
</script>

<template>
<div class="page-stack local-page">
  <section class="panel">
    <header class="panel-heading"><h2>本站检测配置</h2><div class="panel-tools"></div></header>
    <div class="panel-body">
      <form @submit.prevent>
        <fieldset class="local-form-grid">
          <legend>选择实际数据与检测范围</legend>
          <p class="local-source" style="grid-column: 1 / -1;">
            {{ stationId ? '当前管段' : '未选择管段' }}<span class="muted"> · 该管段下共 {{ stations.length }} 个换热站</span>
          </p>
          <label>换热站
            <select v-model="stationId" aria-label="检测换热站" @change="changeStation">
              <option value="">请选择换热站</option>
              <option v-for="s in stations" :key="s.id" :value="s.id">{{s.name}} · {{s.code}}</option>
            </select>
          </label>
          <label>数据集
            <select v-model="datasetId" aria-label="检测数据集">
              <option value="">请选择数据集</option>
              <option v-for="d in datasets" :key="d.id" :value="d.id">{{d.name}}</option>
            </select>
          </label>
          <label style="grid-column: 1;">开始时间<input v-model="start" type="datetime-local" aria-label="本机检测开始时间" /></label>
          <label>结束时间<input v-model="end" type="datetime-local" aria-label="本机检测结束时间" /></label>
        </fieldset>
      </form>
      <p v-if="busy" class="local-notice" role="status">正在加载数据并运行检测…</p>
      <ul v-if="issues.length" class="muted" style="margin:7px 0 0 18px;line-height:1.9">
        <li v-for="(m,i) in issues" :key="i">{{m}}</li>
      </ul>
      <p v-else-if="datasetId" class="muted">传感器检查未发现需要提示的问题。</p>
      <p v-if="error" class="error" role="alert">{{error}}</p>
    </div>
  </section>

  <section class="panel">
    <header class="panel-heading">
      <h2>监测采样与趋势</h2>
      <div class="panel-tools">
        <label>曲线参数
          <select v-model="parameter" aria-label="本机图表参数" @change="changeParam">
            <option v-for="(label,key) in FIELDS" :key="key" :value="key">{{label}}</option>
          </select>
        </label>
        <button :disabled="!samples.length">导出监测 CSV</button>
      </div>
    </header>
    <div class="panel-body">
      <button class="primary" :disabled="!events.length" @click="addToPending"
        :title="events.length?'把本次检测的确认告警加入待处理异常集':'本次检测无确认告警'">
        加入待处理异常集（{{events.length}}）
      </button>
      <span class="muted" style="margin-left:10px">本次检测有 {{events.length}} 条确认告警</span>
      <p v-if="!events.length && task" class="muted">本次检测无确认告警</p>
      <p v-if="message" class="local-notice" role="status">{{message}}</p>

      <div ref="chartEl" style="width:100%;height:360px"></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>采样时间</th><th>{{FIELDS[parameter]}}</th><th>质量</th></tr></thead>
          <tbody>
            <tr v-for="s in samples" :key="s.timestamp">
              <td>{{fmtTableTime(s.timestamp)}}</td>
              <td>{{fmtNum(s.values?.[parameter])}} {{unitOf(parameter)}}</td>
              <td>{{qualityText(s.quality?.[parameter] ?? 'missing')}}</td>
            </tr>
            <tr v-if="!samples.length"><td colspan="3" class="empty">选择换热站后会自动读取本站采样；没有数据时不显示模拟读数。</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <span>{{sampleTotal}} 条 · {{samplePage}} / {{samplePages}}</span>
        <button :disabled="samplePage<=1" @click="page(-1)">上一页</button>
        <button :disabled="samplePage>=samplePages" @click="page(1)">下一页</button>
      </div>
    </div>
  </section>

  <section class="panel">
    <header class="panel-heading"><h2>本站检测历史</h2><div class="panel-tools"></div></header>
    <div class="panel-body">
      <div class="table-wrap">
        <table>
          <thead><tr><th>任务</th><th>站点</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="t in history.slice((historyPage-1)*PAGE_HISTORY, historyPage*PAGE_HISTORY)" :key="t.id">
              <td>{{t.name}}</td><td>{{t.contextSnapshot?.station?.name}}</td>
              <td>{{t.status==='success'?'已完成':t.status}}</td><td>{{fmtTableTime(t.createdAt)}}</td>
              <td><button class="link" @click="viewTask(t)">查看任务</button></td>
            </tr>
            <tr v-if="!history.length"><td colspan="5" class="empty">当前管段暂无真实检测记录。</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <span>{{history.length}} 条 · {{historyPage}} / {{historyPages}}</span>
        <button :disabled="historyPage<=1" @click="historyPage--">上一页</button>
        <button :disabled="historyPage>=historyPages" @click="historyPage++">下一页</button>
      </div>
    </div>
  </section>
</div>
</template>
