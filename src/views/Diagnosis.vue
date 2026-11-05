<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ArrowLeft,ArrowRight,Check,ChevronRight,Clock3,LoaderCircle,History,Plus,TriangleAlert,FileText,Activity} from 'lucide-vue-next'
import Panel from '../components/Panel.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import DiagnosisReport from '../components/DiagnosisReport.vue'
import {useWorkspace} from '../stores/workspace'
import {metricInfo,statusText} from '../domain'
import {causesFor} from '../services/demo'
import {restoredSteps} from '../services/diagnosis'
import {time} from '../utils'

const store=useWorkspace(),route=useRoute(),router=useRouter()
const showHistory=ref(route.query.history==='reports'),historyTab=ref(route.query.history==='reports'?'reports':'tasks'),query=ref(''),all=ref(false),filter=ref(''),archived=ref(''),page=ref(1)
const sourceId=ref(''),selection=ref<string[]>([]),scenario=ref<'success'|'failure'>('success'),error=ref(''),activeStep=ref('evidence'),follow=ref(true),scatter=ref(true)
const requested=computed(()=>String(route.params.id??''))
const explicitReport=computed(()=>requested.value.startsWith('REP-')?store.state.reports.find(r=>r.id===requested.value):undefined)
const tasks=computed(()=>store.state.analyses.filter(a=>(all.value||a.context.segment.id===store.context?.segment.id)&&(!filter.value||a.status===filter.value)&&(!query.value||(a.id+a.context.segment.name+a.detectionId).includes(query.value))))
const reports=computed(()=>store.state.reports.filter(r=>(all.value||r.context.segment.id===store.context?.segment.id)&&(!archived.value||(archived.value==='yes'?!!r.archivedAt:!r.archivedAt))&&(!query.value||(r.id+r.title+r.context.segment.name).includes(query.value))))
const task=computed(()=>route.query.create==='1'?undefined:explicitReport.value?explicitReport.value.analysis:(requested.value?store.state.analyses.find(a=>a.id===requested.value):store.state.analyses.find(a=>a.context.segment.id===store.context?.segment.id)))
const detection=computed(()=>explicitReport.value?.detection??store.state.detections.find(d=>d.id===task.value?.detectionId))
const report=computed(()=>explicitReport.value??(task.value?store.state.reports.find(r=>r.analysisId===task.value!.id):undefined))
const available=computed(()=>store.state.detections.filter(d=>d.status==='success'&&d.context.segment.id===store.context?.segment.id))
const sources=computed(()=>detection.value&&!available.value.some(d=>d.id===detection.value!.id)?[detection.value,...available.value]:available.value)
const source=computed(()=>sources.value.find(d=>d.id===sourceId.value))
const events=computed(()=>detection.value?.anomalies.filter(a=>task.value?.anomalyIds.includes(a.id))??[])
const steps=computed(()=>task.value&&detection.value?(explicitReport.value?.process??restoredSteps(task.value,detection.value)):[])
const currentStep=computed(()=>steps.value.find(s=>s.id===activeStep.value)??steps.value[0])
const causes=computed(()=>{const fallback=detection.value&&task.value?causesFor(detection.value,task.value.anomalyIds):[];return (explicitReport.value?.causes??task.value?.causes??fallback).map(c=>({...fallback.find(x=>x.title===c.title),...c}))})
const paired=computed(()=>!!detection.value?.metrics.includes('return')&&!!detection.value?.metrics.includes('flow'))
const running=computed(()=>task.value?.status==='queued'||task.value?.status==='running')
const rowCount=computed(()=>historyTab.value==='tasks'?tasks.value.length:reports.value.length),pages=computed(()=>Math.max(1,Math.ceil(rowCount.value/20)))
const taskRows=computed(()=>tasks.value.slice((page.value-1)*20,page.value*20)),reportRows=computed(()=>reports.value.slice((page.value-1)*20,page.value*20))
watch([query,all,filter,archived,historyTab],()=>page.value=1)
watch(sourceId,()=>{selection.value=task.value?.detectionId===sourceId.value?[...task.value.anomalyIds]:(source.value?.anomalies.map(a=>a.id)??[]);error.value=''})
watch(()=>[requested.value,store.context?.segment.id,route.query.create,route.query.source],()=>{
 sourceId.value=typeof route.query.source==='string'?route.query.source:(detection.value?.id??available.value[0]?.id??'')
 selection.value=task.value&&sourceId.value===task.value.detectionId?[...task.value.anomalyIds]:(source.value?.anomalies.map(a=>a.id)??[])
 follow.value=true;activeStep.value='evidence';error.value=''
},{immediate:true})
watch(()=>[task.value?.id,task.value?.status],()=>{if(task.value?.status==='success'&&!explicitReport.value)store.ensureReport(task.value.id)},{immediate:true})
watch(()=>steps.value.map(s=>s.state).join(),()=>{if(follow.value&&running.value){const active=steps.value.find(s=>s.state==='running');if(active)activeStep.value=active.id}},{immediate:true})
function start(){try{const id=store.createAnalysis(sourceId.value,selection.value,scenario.value);showHistory.value=false;router.push('/diagnosis/'+id)}catch(e){error.value=(e as Error).message}}
function retry(){if(task.value){const id=store.createAnalysis(task.value.detectionId,task.value.anomalyIds,'success',task.value.id);router.push('/diagnosis/'+id)}}
function fresh(){router.push({path:'/diagnosis',query:{create:'1'}});selection.value=source.value?.anomalies.map(a=>a.id)??[];document.getElementById('event-picker')?.scrollIntoView({behavior:'smooth',block:'start'})}
function showReport(){document.getElementById('diagnosis-report')?.scrollIntoView({behavior:'smooth',block:'start'})}
function openRecord(id:string){showHistory.value=false;router.push('/diagnosis/'+id)}
</script>

<template>
<div class="page-stack diagnosis-page">
 <div class="page-actions"><div><h2>AI诊断</h2><p class="muted">从数值异常到原因判断与解决建议</p></div><div class="flex wrap"><button class="secondary" @click="showHistory=!showHistory"><History :size="16"/>历史记录</button><button class="primary" @click="fresh"><Plus :size="16"/>新建诊断</button></div></div>
 <Panel v-if="showHistory" title="诊断历史记录">
  <template #tools><div class="segmented"><button :class="{selected:historyTab==='tasks'}" @click="historyTab='tasks'">诊断任务</button><button :class="{selected:historyTab==='reports'}" @click="historyTab='reports'">报告与归档</button></div></template>
  <div class="filter-bar"><input v-model="query" aria-label="搜索诊断记录" placeholder="搜索编号、来源或管段"/><select v-if="historyTab==='tasks'" v-model="filter" aria-label="诊断任务状态"><option value="">全部状态</option><option v-for="(text,key) in statusText" :key="key" :value="key">{{text}}</option></select><select v-else v-model="archived" aria-label="归档状态"><option value="">全部归档状态</option><option value="yes">已归档</option><option value="no">待归档</option></select><label class="check-label"><input v-model="all" type="checkbox"/>全部管段</label></div>
  <div class="table-wrap"><table v-if="historyTab==='tasks'"><thead><tr><th>诊断编号</th><th>所属管段</th><th>所选事件</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="a in taskRows" :key="a.id"><td class="mono">{{a.id}}</td><td>{{a.context.segment.name}}</td><td>{{a.anomalyIds.length}} 项</td><td>{{time(a.createdAt)}}</td><td>{{statusText[a.status]}}</td><td><button class="text-button" @click="openRecord(a.id)">查看诊断</button></td></tr></tbody></table><table v-else><thead><tr><th>报告</th><th>管段</th><th>生成时间</th><th>版本</th><th>归档状态</th><th>操作</th></tr></thead><tbody><tr v-for="r in reportRows" :key="r.id"><td>{{r.title}}<small>{{r.id}}</small></td><td>{{r.context.segment.name}}</td><td>{{time(r.createdAt)}}</td><td>V{{r.version}}</td><td>{{r.archivedAt?'已归档':'待归档'}}</td><td><button class="text-button" @click="openRecord(r.id)">查看报告</button></td></tr></tbody></table><div v-if="!rowCount" class="empty">暂无匹配记录，请调整筛选或新建诊断。</div></div>
  <div class="pagination"><span>共 {{rowCount}} 条 · 第 {{page}} / {{pages}} 页</span><button :disabled="page===1" @click="page--">上一页</button><button :disabled="page>=pages" @click="page++">下一页</button></div>
 </Panel>
 <div class="diagnosis-concepts"><div><Activity :size="19"/><span><b>异常事件</b>观测值偏离数值规则，尚未确定原因</span></div><ChevronRight :size="20"/><div><FileText :size="19"/><span><b>AI诊断结果</b>分析可能原因，给出解决建议与复核方法</span></div></div>
 <p v-if="requested&&!task&&!explicitReport" class="error" role="alert">该诊断记录不存在，请从历史记录选择或新建诊断。</p>
 <div class="diagnosis-layout">
  <Panel id="event-picker" title="选择异常事件" class="event-picker"><template #tools><span class="badge orange">可单选 / 多选</span></template>
   <label class="form-stack">来源检测任务<select v-model="sourceId" aria-label="来源检测任务"><option value="">请选择已完成检测</option><option v-for="d in sources" :key="d.id" :value="d.id">{{d.name}} · {{d.id}}</option></select></label>
   <p v-if="source" class="muted small">{{source.context.network.name}} / {{source.context.segment.name}}</p>
   <template v-if="source?.anomalies.length"><div class="flex between mt"><span>已选 {{selection.length}} / {{source.anomalies.length}} 项</span><button class="text-button" @click="selection=selection.length===source.anomalies.length?[]:source.anomalies.map(a=>a.id)">{{selection.length===source.anomalies.length?'取消全选':'全选'}}</button></div>
   <label v-for="a in source.anomalies" :key="a.id" :class="['event-choice',{chosen:selection.includes(a.id)}]"><input v-model="selection" type="checkbox" :value="a.id"/><span><strong>{{a.title}}</strong><small class="mono">{{time(a.start)}}</small><span class="event-values">{{a.baseline}} <ArrowRight :size="13"/> <b>{{a.value}} {{metricInfo[a.metric].unit}}</b></span><small>{{a.level}} · 数值规则判定</small></span></label></template>
   <div v-else class="empty">{{source?'该检测未检出异常事件，无需发起原因诊断。':'请先完成异常检测。'}}<RouterLink to="/detections" class="text-button">进入异常检测</RouterLink></div>
   <label class="form-stack mt">演示场景<select v-model="scenario"><option value="success">诊断完成</option><option value="failure">诊断失败（验证重试）</option></select></label>
   <p v-if="error" class="error" role="alert">{{error}}</p><button class="primary wide mt" :disabled="!selection.length||running" @click="start">{{running?'诊断正在执行':'开始诊断（'+selection.length+' 项事件）'}}</button><p class="muted small">每次诊断固定所选事件。调整选择后发起新任务，历史结果保持不变。</p>
  </Panel>
  <div class="page-stack diagnosis-work">
   <Panel v-if="task&&detection" title="分析过程"><template #tools><span :class="['badge',task.status==='failed'?'red':task.status==='success'?'green':'orange']"><LoaderCircle v-if="running" :size="13" class="spin"/>{{statusText[task.status]}}</span><button v-if="report" class="secondary" @click="showReport">查看诊断报告</button></template>
    <div class="diagnosis-task-meta"><span class="mono orange">{{task.id}}</span><span>诊断范围：{{events.length}} 项事件</span><span>{{task.model}}</span><RouterLink :to="{path:'/detections/'+task.detectionId,query:{selected:task.anomalyIds.join(',')}}" class="text-button"><ArrowLeft :size="14"/>返回检测结果</RouterLink></div>
    <p class="muted small">{{task.context.enterprise.name}} / {{task.context.network.name}} / {{task.context.segment.name}} · {{time(task.createdAt)}}</p>
    <div class="process-banner"><i :class="['dot',{bad:task.status==='failed'}]"></i><span>{{task.status==='success'?'分析完成，过程摘要已保留':task.status==='failed'?'诊断中断，已完成阶段仍可查看':task.status==='queued'?'已接收事件，等待演示诊断服务':'正在整理证据与诊断依据'}}</span><button v-if="running&&!follow" class="text-button" @click="follow=true">跟随当前阶段</button></div>
    <div class="diagnosis-process"><ol class="process-rail"><li v-for="(step,i) in steps" :key="step.id" :data-state="step.state"><button :class="{selected:activeStep===step.id}" :aria-pressed="activeStep===step.id" @click="activeStep=step.id;follow=false"><span class="process-node"><Check v-if="step.state==='done'" :size="16"/><LoaderCircle v-else-if="step.state==='running'" :size="16" class="spin"/><TriangleAlert v-else-if="step.state==='failed'" :size="16"/><Clock3 v-else :size="15"/></span><span><strong>{{step.title}}</strong><small>{{step.state==='done'?'已完成':step.state==='running'?'进行中':step.state==='failed'?'失败':'待执行'}}</small></span><span class="mono muted">{{String(i+1).padStart(2,'0')}}</span></button></li></ol>
     <section v-if="currentStep" class="process-evidence" :aria-label="currentStep.title+'阶段详情'"><h3>{{currentStep.title}}</h3><template v-if="currentStep.state!=='pending'"><p>{{currentStep.summary}}</p><ul class="evidence-notes"><li v-for="line in currentStep.evidence" :key="line">{{line}}</li></ul>
      <div v-if="currentStep.chart==='timeseries'||currentStep.chart==='correlation'" class="process-chart"><div v-if="currentStep.id==='correlation'" class="segmented"><button :disabled="!paired" :class="{selected:paired&&scatter}" @click="scatter=true">关联散点流</button><button :class="{selected:!paired||!scatter}" @click="scatter=false">双轴时序对齐</button></div><TelemetryChart :key="task.id+currentStep.id+String(scatter)" :context="task.context" :metrics="currentStep.id==='correlation'&&paired?['return','flow']:detection.metrics" :start="detection.start" :end="detection.end" :anomalies="events" :scatter="currentStep.id==='correlation'&&paired&&scatter" compact/></div>
      <div v-if="currentStep.chart==='causes'&&currentStep.state==='done'" class="process-cause-bars"><div v-for="cause in causes" :key="cause.title" class="weight"><div class="flex between wrap"><span>{{cause.title}}</span><b class="orange">{{cause.weight}}%</b></div><div class="bar"><span :style="{width:cause.weight+'%'}"></span></div></div><small class="muted">示例权重，不代表真实模型置信度</small></div>
      <dl v-if="currentStep.id==='events'" class="event-facts"><div v-for="a in events" :key="a.id"><dt>{{a.title}}</dt><dd>{{a.baseline}} → {{a.value}} {{metricInfo[a.metric].unit}}</dd></div></dl>
     </template><div v-else class="empty">该阶段尚未开始，完成后会保留证据和摘要。</div>
     </section></div>
    <div v-if="task.status==='failed'" class="notice"><span class="red">{{task.error}}</span><button class="primary" @click="retry">重试诊断</button></div>
    <p class="muted small">展示的是可供核验的阶段与证据摘要；当前由演示服务生成，不代表真实模型内部思考或已确认的设备故障。</p>
   </Panel>
   <Panel v-else title="开始一次 AI诊断"><div class="empty"><FileText :size="34"/><h3>先选择需要分析的异常事件</h3><p>数值异常只是线索，诊断将进一步整理原因与解决建议。</p></div></Panel>
   <Panel v-if="task?.status==='success'" title="原因诊断与解决建议"><template #tools><span class="badge orange">待现场核验 · 演示结果</span></template>
    <p>本次针对 <b class="orange">{{events.map(a=>a.title).join('、')}}</b>，形成以下候选原因及对应处理建议。</p>
    <article v-for="(cause,i) in causes" :key="cause.title" class="diagnosis-cause"><div class="flex between wrap"><h3>{{i+1}}. {{cause.title}}</h3><span class="badge">示例权重 {{cause.weight}}%</span></div><p class="muted">{{cause.evidence}}</p><dl class="solution-list"><div><dt>核查方法</dt><dd>{{cause.check}}</dd></div><div><dt>解决建议</dt><dd>{{cause.solution??'补充现场参数并核验后确定处理方案。'}}</dd></div><div><dt>复核标准</dt><dd>{{cause.verification??'复测处置前后的参数变化并确认异常是否消失。'}}</dd></div></dl></article>
   </Panel>
  </div>
 </div>
 <section v-if="report" id="diagnosis-report" aria-label="诊断报告与归档"><DiagnosisReport :report-id="report.id" @created="openRecord"/></section>
</div>
</template>
