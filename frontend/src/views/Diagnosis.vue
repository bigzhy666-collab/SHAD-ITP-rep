<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,nextTick} from 'vue'
import * as echarts from 'echarts/core'
import {LineChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,LegendComponent,DataZoomComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'

echarts.use([LineChart,GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,CanvasRenderer])

const box=ref<any[]>([])
const task=ref<any>(null), result=ref<any>(null), events=ref<any[]>([]), points=ref<any[]>([])
const busy=ref(false), error=ref('')
const showScore=ref(false), showReport=ref(false), note=ref('')
const report=ref<any>(null), saving=ref(false), reportMsg=ref('')
const reports=ref<any[]>([]), archiveFilter=ref('all')
const chartEl=ref<HTMLElement>()
let chart:echarts.ECharts|undefined

const summary=computed(()=>result.value?.summary??{})
const eventIds=computed(()=>events.value.map((e:any)=>e.id))
function fmtTime(iso:string){return iso?iso.slice(0,16).replace('T',' '):''}
function fmtNum(v:any){return typeof v==='number'?Math.round(v*10)/10:v??'—'}
function uuid(){return crypto.randomUUID()}

function loadBox(){
  try{box.value=JSON.parse(localStorage.getItem('shad-pending-box')||'[]')}catch{box.value=[]}
}
function persist(){localStorage.setItem('shad-pending-box',JSON.stringify(box.value))}
function removeItem(key:string){box.value=box.value.filter(x=>x.key!==key);persist()}
function clearAll(){box.value=[];persist()}

async function getJson(url:string,init?:RequestInit){
  const r=await fetch(url,init)
  const b=await r.json().catch(()=>({}))
  if(!r.ok||b.error)throw new Error(b?.error?.message||`请求失败 (${r.status})`)
  return b.data
}

async function loadItem(item:any){
  busy.value=true;error.value='';task.value=null;result.value=null;events.value=[];points.value=[]
  try{
    task.value=await getJson(`/api/detections/${item.taskId}`)
    result.value=await getJson(`/api/detections/${item.taskId}/result`)
    const ev=await getJson(`/api/detections/${item.taskId}/events?page=1&pageSize=500`)
    events.value=ev.items||[]
    const pt=await getJson(`/api/detections/${item.taskId}/points?page=1&pageSize=500`)
    points.value=pt.items||[]
  }catch(e:any){error.value=e.message}
  finally{busy.value=false}
}

async function loadReports(){
  try{
    const d=await getJson('/api/reports?page=1&pageSize=500')
    reports.value=d.items||[]
  }catch{reports.value=[]}
}
const filteredReports=computed(()=>reports.value.filter(r=>archiveFilter.value==='all'||(archiveFilter.value==='archived'?!!r.archivedAt:!r.archivedAt)))

async function openScore(){
  showScore.value=true
  await nextTick()
  if(!chartEl.value)return
  if(!chart)chart=echarts.init(chartEl.value)
  chart.setOption({
    grid:{left:64,right:24,top:40,bottom:56},
    tooltip:{trigger:'axis'},
    legend:{data:['异常分数','阈值'],top:4,left:'center',itemWidth:14,itemHeight:8,textStyle:{fontSize:11,color:'#64748b'}},
    dataZoom:[{type:'inside',start:0,end:100},{type:'slider',start:0,end:100,height:18,bottom:12}],
    xAxis:{type:'time',axisLabel:{fontSize:10,color:'#64748b'}},
    yAxis:{name:'分数',type:'value',axisLabel:{fontSize:10,color:'#64748b'},splitLine:{lineStyle:{color:'#eef2f6'}}},
    series:[
      {name:'异常分数',type:'line',showSymbol:false,lineStyle:{width:1.6,color:'#2563eb'},
        data:points.value.map((p:any)=>[p.timestamp,p.score])},
      {name:'阈值',type:'line',showSymbol:false,lineStyle:{width:1.4,color:'#c2410c',type:'dashed'},
        data:points.value.map((p:any)=>[p.timestamp,p.threshold])},
    ],
  },true)
  chart.resize()
}

const reportSections=computed(()=>{
  if(!task.value||!result.value)return []
  const t:any=task.value
  const s=summary.value
  const ds=t.datasetSnapshot||{}
  const md=t.modelSnapshot||{}
  const seg=t.contextSnapshot?.segment?.name??''
  const st=t.contextSnapshot?.station?.name??''
  return [
    {h:'',p:`数据校验值：${ds.sourceChecksum??'—'}`},
    {h:'',p:`模型：${md.name??md.id??'—'}${md.stationId?'（'+seg+'·'+st+'）':''} / ${md.version??'—'}`},
    {h:'',p:`模型校验值：${md.checksum??'—'}`},
    {h:'',p:`预处理：${ds.preprocessingVersion??'—'}`},
    {h:'',p:'来源标识：示例模型结果，不适用于本站运行判断'},
    {h:'异常检测与证据',p:`检测点 ${s.pointCount??'—'}，点级超阈 ${s.alarmPointCount??'—'}，全部确认事件 ${s.eventCount??'—'} 段。`},
    {h:'',p:`本报告选择事件 ${events.value.length} 项。`},
    ...events.value.map((e:any)=>({h:'',
      p:`${e.id}：${e.title}，${fmtTime(e.start)} — ${fmtTime(e.end)}，持续 ${fmtNum(e.hours)} 小时，峰值分数 ${fmtNum(e.peak_score)}；触及检测区间边界，不能据此判断已恢复。`})),
    {h:'',p:'检测提示：部分可选测点未提供或存在缺失；依据这些测点的缺失特征按模型训练期补偿处理。'},
    {h:'',p:'检测提示：正在执行示例模型；结果用于接口验证，不构成本站模型适用性或诊断准确性证明。'},
    {h:'备注、版本与适用边界',p:report.value?`备注：${report.value.note||'无'}\n归档状态：${report.value.archivedAt?'已归档':'未归档'}（V${report.value.version}）`:'备注：无\n归档状态：临时导出，未保存到本机后端'},
    {h:'',p:'异常事件表示偏离正常行为，不等于已确认的设备故障；结论边界以检测区间与模型适用范围为准。'},
  ]
})

async function saveReport(){
  if(!task.value)return
  saving.value=true;reportMsg.value=''
  try{
    if(!report.value){
      report.value=await getJson('/api/reports',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':uuid()},
        body:JSON.stringify({detectionId:task.value.id,eventIds:eventIds.value,diagnosisId:null})})
    }
    report.value=await getJson(`/api/reports/${report.value.id}/note`,{method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({note:note.value,expectedRevision:report.value.revision})})
    reportMsg.value=`已保存 · V${report.value.version}`
    await loadReports()
  }catch(e:any){reportMsg.value=e.message}
  finally{saving.value=false}
}

async function archiveReport(){
  if(!report.value)return
  saving.value=true
  try{
    report.value=await getJson(`/api/reports/${report.value.id}/archive`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({expectedRevision:report.value.revision})})
    reportMsg.value='已归档 · 证据与备注已锁定'
    await loadReports()
  }catch(e:any){reportMsg.value=e.message}
  finally{saving.value=false}
}

function exportPrint(){window.print()}

async function openSaved(r:any){
  try{
    const full=await getJson(`/api/reports/${r.id}`)
    const snap=full.snapshot||{}
    task.value=snap.task||null;result.value=snap.result||null
    events.value=snap.events||[];points.value=snap.points||[]
    report.value=full;note.value=full.note||''
    showReport.value=true
  }catch(e:any){error.value=e.message}
}

function onKey(e:KeyboardEvent){if(e.key==='Escape'){showScore.value=false;showReport.value=false}}

onMounted(async()=>{loadBox();window.addEventListener('keydown',onKey);await loadReports()})
onBeforeUnmount(()=>{window.removeEventListener('keydown',onKey);chart?.dispose()})
</script>

<template>
<div class="page-stack local-page">
  <section class="panel">
    <header class="panel-heading">
      <h2>选择待处理异常集</h2>
      <div class="panel-tools"><span class="muted">共 {{box.length}} 个</span><button v-if="box.length" class="secondary" @click="clearAll">清空全部</button></div>
    </header>
    <div class="panel-body">
      <div v-if="box.length" class="table-wrap">
        <table>
          <thead><tr><th>名称</th><th>异常条数</th><th>加入时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="it in box" :key="it.key">
              <td>{{it.station}} · {{it.taskName}}</td>
              <td>{{it.eventCount}}</td>
              <td>{{new Date(it.addedAt).toLocaleString('zh-CN',{hour12:false})}}</td>
              <td>
                <span class="local-actions">
                  <button class="primary" :disabled="busy" @click="loadItem(it)">载入处理</button>
                  <button @click="removeItem(it.key)">移除</button>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!box.length" class="empty">暂无待处理异常集。请到“数据监测”选择换热站完成检测后，点“加入待处理异常集”。</p>
      <p v-if="busy" class="local-notice" role="status">正在载入检测结果…</p>
      <p v-if="error" class="error" role="alert">{{error}}</p>
    </div>
  </section>

  <p v-if="!task" class="empty">请从数据监测单选或多选确认告警事件，或打开下面的历史记录。</p>

  <section v-if="task" class="panel">
    <header class="panel-heading">
      <h2>检测任务与结果</h2>
      <div class="panel-tools">
        <button class="primary" @click="openScore">查看异常分数曲线</button>
        <button class="primary" @click="showReport=true">查看报告</button>
      </div>
    </header>
    <div class="panel-body">
      <p class="muted" style="margin-bottom:6px">{{task.name}} · {{task.contextSnapshot?.station?.name}}</p>
      <p class="muted">有效点 {{summary.pointCount??'—'}} · 超阈点 {{summary.alarmPointCount??'—'}} · 确认告警 {{summary.eventCount??'—'}} 段 · 质量问题 {{summary.qualityIssueCount??0}}</p>
      <div class="table-wrap" style="margin-top:10px">
        <table>
          <thead><tr><th>起止时间</th><th>持续小时</th><th>峰值 · 计数</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="e in events" :key="e.id">
              <td>{{fmtTime(e.start)}} — {{fmtTime(e.end)}}</td>
              <td>{{fmtNum(e.hours)}}</td>
              <td>{{fmtNum(e.peak_score)}} · {{e.max_criticality??'—'}}</td>
              <td><button class="link" @click="showReport=true">查看报告</button></td>
            </tr>
            <tr v-if="!events.length"><td colspan="4" class="empty">本次检测无确认告警。</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <section class="panel">
    <header class="panel-heading">
      <h2>报告历史与归档</h2>
      <div class="panel-tools"><button class="secondary" @click="loadReports">刷新历史</button></div>
    </header>
    <div class="panel-body">
      <label>归档状态
        <select v-model="archiveFilter" aria-label="本机报告归档状态">
          <option value="all">全部报告</option>
          <option value="archived">已归档</option>
          <option value="draft">未归档</option>
        </select>
      </label>
      <div class="table-wrap">
        <table>
          <thead><tr><th>报告</th><th>版本</th><th>存档状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="r in filteredReports" :key="r.id">
              <td>{{r.title}}</td><td>{{r.version}}</td>
              <td>{{r.archivedAt?'已归档':'未归档'}}</td>
              <td><button class="link" @click="openSaved(r)">查看报告</button></td>
            </tr>
            <tr v-if="!filteredReports.length"><td colspan="4" class="empty">暂无已保存报告</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination"><span>{{filteredReports.length}} 条 · 第 1 页</span><button disabled>上一页</button><button disabled>下一页</button></div>
    </div>
  </section>

  <div v-if="showScore" class="modal-backdrop" @click.self="showScore=false">
    <div class="modal" style="width:1180px;max-width:96vw" role="dialog" aria-label="异常分数曲线">
      <header><strong>异常分数曲线</strong><button class="icon-button" aria-label="关闭" @click="showScore=false">×</button></header>
      <div class="modal-content">
        <p class="muted" style="margin-bottom:6px">• 正在执行示例模型结果，用于接口验证，不构成本站模型适用性或诊断准确性证明。</p>
        <p class="muted">有效点 {{summary.pointCount??'—'}} · 超阈点 {{summary.alarmPointCount??'—'}} · 确认告警 {{summary.eventCount??'—'}} 段 · 质量问题 {{summary.qualityIssueCount??0}}</p>
        <div ref="chartEl" style="width:100%;height:52vh"></div>
        <p class="muted" style="margin-top:6px">滑轮可缩放，图上可拖动平移；告警事件不代表具体原因。</p>
      </div>
    </div>
  </div>

  <div v-if="showReport" class="modal-backdrop" @click.self="showReport=false">
    <div class="modal" style="width:1040px;max-width:96vw" role="dialog" aria-label="报告预览与导出">
      <header><strong>报告预览与导出</strong><button class="icon-button" aria-label="关闭" @click="showReport=false">×</button></header>
      <div class="modal-content">
        <template v-for="(s,i) in reportSections" :key="i">
          <h4 v-if="s.h" style="margin:14px 0 6px">{{s.h}}</h4>
          <p style="margin:0 0 8px;white-space:pre-line">{{s.p}}</p>
        </template>
        <label style="display:block;margin-top:12px">备注
          <textarea v-model="note" rows="3" style="width:100%"></textarea>
        </label>
        <p v-if="reportMsg" class="local-notice" role="status">{{reportMsg}}</p>
        <div class="local-actions" style="margin-top:14px;justify-content:flex-end;gap:8px;display:flex">
          <button class="primary" :disabled="saving" @click="saveReport">保存报告与备注</button>
          <button class="secondary" :disabled="saving||!report||!!report.archivedAt" @click="archiveReport">保存并归档</button>
          <button class="secondary" @click="exportPrint">导出</button>
        </div>
      </div>
    </div>
  </div>
</div>
</template>
