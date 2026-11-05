<script setup lang="ts">
import {computed,nextTick,reactive,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ArrowRight,ChevronDown,Copy,Download,History,Plus,RotateCcw,Search,TriangleAlert} from 'lucide-vue-next'
import Panel from '../components/Panel.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import {useWorkspace} from '../stores/workspace'
import {metricInfo,statusText} from '../domain'
import type {Detection,Metric,Sample} from '../domain'
import {samplesFor,validateDetection} from '../services/demo'
import {eventsInScope,sampleIssue,sampleState} from '../services/monitoring'
import {csv,time} from '../utils'

const store=useWorkspace(),route=useRoute(),router=useRouter()
const showList=ref(false),query=ref(''),status=ref(''),all=ref(false),listPage=ref(1)
const task=computed(()=>route.params.id?store.state.detections.find(d=>d.id===route.params.id):store.state.detections.find(d=>d.context.segment.id===store.context?.segment.id))
const context=computed(()=>task.value?.context??store.context)
const tasks=computed(()=>store.state.detections.filter(d=>(all.value||d.context.segment.id===store.context?.segment.id)&&(!query.value||(d.id+d.name).includes(query.value))&&(!status.value||d.status===status.value)))
const listRows=computed(()=>tasks.value.slice((listPage.value-1)*20,listPage.value*20)),listPages=computed(()=>Math.max(1,Math.ceil(tasks.value.length/20)))
const parameters=computed(()=>context.value?.segment.metrics??[])
const groups=[{name:'温度',metrics:['supply','return'] as Metric[]},{name:'压力',metrics:['pressure'] as Metric[]},{name:'流量',metrics:['flow'] as Metric[]}]
const collapsed=ref<string[]>([]),compare=ref(false),viewMetrics=ref<Metric[]>(['return']),focus=ref(''),selected=ref<string[]>([]),analysisFailure=ref(false)
const monitorStart=ref('2026-11-03T00:00'),monitorEnd=ref('2026-11-03T08:00'),draftStart=ref(monitorStart.value),draftEnd=ref(monitorEnd.value),rangeError=ref(''),dataPage=ref(1),onlyIssues=ref(false)
const eventScope=ref('selected')
const chart=ref<InstanceType<typeof TelemetryChart>>()
const form=reactive({name:'管段时序异常检测',start:'2026-11-03T00:00',end:'2026-11-03T08:00',metrics:[] as Metric[],threshold:3.4,scenario:'anomaly' as Detection['scenario'],parentId:''})
const error=ref(''),submitting=ref(false)
const running=computed(()=>task.value?.status==='queued'||task.value?.status==='running')
const resultEvents=computed(()=>task.value?.status==='success'?task.value.anomalies:[])
const rangeEvents=computed(()=>eventsInScope(resultEvents.value.map(a=>({...a,end:a.end??task.value!.end})),parameters.value,monitorStart.value,monitorEnd.value))
const viewEvents=computed(()=>rangeEvents.value.filter(a=>viewMetrics.value.includes(a.metric)))
const visibleEvents=computed(()=>eventScope.value==='all'?rangeEvents.value:viewEvents.value)
const focused=computed(()=>rangeEvents.value.find(a=>a.id===focus.value))
const rawSamples=computed(()=>context.value?samplesFor(context.value,monitorStart.value,monitorEnd.value):[])
const samples=computed(()=>rawSamples.value.filter(s=>viewMetrics.value.includes(s.metric)))
const chartSamples=computed(()=>samples.value.filter(s=>!sampleIssue(s)))
const qualityCount=computed(()=>samples.value.filter(s=>sampleIssue(s)).length)
const dataRows=computed(()=>samples.value.map(s=>({...s,state:sampleState(s,viewEvents.value)})).filter(s=>!onlyIssues.value||s.state.kind!=='valid').sort((a,b)=>Date.parse(b.time)-Date.parse(a.time)))
const pageRows=computed(()=>dataRows.value.slice((dataPage.value-1)*8,dataPage.value*8)),dataPages=computed(()=>Math.max(1,Math.ceil(dataRows.value.length/8)))
const latest=computed(()=>viewMetrics.value.map(metric=>({metric,sample:[...samples.value].reverse().find(s=>s.metric===metric&&!sampleIssue(s))})))
const coverageNotice=computed(()=>task.value?.status==='success'&&(Date.parse(monitorStart.value)<Date.parse(task.value.start)||Date.parse(monitorEnd.value)>Date.parse(task.value.end)))
function displayValue(s?:Sample){return s&&!sampleIssue(s)?s.value:'—'}
function parameterState(m:Metric){return !rawSamples.value.some(s=>s.metric===m)?'无数据':rawSamples.value.some(s=>s.metric===m&&sampleIssue(s))?'质量待核验':rangeEvents.value.some(a=>a.metric===m)?'存在异常':task.value?.status==='success'&&task.value.metrics.includes(m)?coverageNotice.value?'部分未检测':'未检出异常':'未检测'}
function choose(m:Metric){focus.value='';if(compare.value){viewMetrics.value=viewMetrics.value.includes(m)?viewMetrics.value.length>1?viewMetrics.value.filter(x=>x!==m):viewMetrics.value:[...viewMetrics.value,m]}else viewMetrics.value=[m]}
function toggleCompare(){compare.value=!compare.value;if(!compare.value)viewMetrics.value=viewMetrics.value.slice(0,1)}
function toggleGroup(name:string){collapsed.value=collapsed.value.includes(name)?collapsed.value.filter(x=>x!==name):[...collapsed.value,name]}
function applyRange(){rangeError.value=validateRange(draftStart.value,draftEnd.value);if(rangeError.value)return;monitorStart.value=draftStart.value;monitorEnd.value=draftEnd.value;focus.value=''}
function validateRange(start:string,end:string){const a=Date.parse(start),b=Date.parse(end);return !Number.isFinite(a)||!Number.isFinite(b)||a>=b?'监测开始时间必须早于结束时间。':''}
function preset(hours:number){const origin=Date.parse('2026-11-03T00:00'),end=Math.max(Date.parse(monitorEnd.value),origin+hours*3600000);const local=(t:number)=>{const d=new Date(t);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`};draftEnd.value=local(end);draftStart.value=local(end-hours*3600000);applyRange()}
function locate(id:string){const a=rangeEvents.value.find(a=>a.id===id);if(!a)return;if(!viewMetrics.value.includes(a.metric))viewMetrics.value=compare.value?[...viewMetrics.value,a.metric]:[a.metric];focus.value=id;onlyIssues.value=false;nextTick(()=>{const index=dataRows.value.findIndex(s=>s.metric===a.metric&&sampleState(s,[a]).kind==='anomaly');dataPage.value=index<0?1:Math.floor(index/8)+1;document.getElementById('monitor-trend')?.scrollIntoView({behavior:'smooth',block:'nearest'})})}
function toggleHistory(){showList.value=!showList.value;nextTick(()=>document.getElementById('detection-history')?.scrollIntoView({behavior:'smooth'}))}
function resetChart(){focus.value='';chart.value?.reset()}
function open(copy?:Detection){error.value='';const c=copy?.context??context.value;Object.assign(form,{name:copy?copy.name+'（副本）':'管段时序异常检测',start:copy?.start??monitorStart.value,end:copy?.end??monitorEnd.value,metrics:[...(copy?.metrics??parameters.value)],threshold:copy?.threshold??3.4,scenario:copy?.scenario??'anomaly',parentId:copy?.id??''});if(c&&c.segment.id!==store.context?.segment.id)store.select(c.segment.id);nextTick(()=>document.getElementById('detection-config')?.scrollIntoView({behavior:'smooth',block:'start'}))}
function useView(){form.start=monitorStart.value;form.end=monitorEnd.value;form.metrics=[...viewMetrics.value]}
function submit(){if(submitting.value||running.value)return;error.value='';try{submitting.value=true;const validation=validateDetection(context.value,form.start,form.end,form.metrics,form.threshold);if(validation)throw new Error(validation);const id=store.createDetection({...form,metrics:[...form.metrics],context:context.value!});router.push('/detections/'+id)}catch(e){error.value=(e as Error).message}finally{submitting.value=false}}
function retry(){if(!task.value)return;try{const id=store.createDetection({...task.value,name:task.value.name+'（重试）',scenario:'anomaly',parentId:task.value.id});router.push('/detections/'+id)}catch(e){store.notify((e as Error).message)}}
function analyze(){if(!task.value)return;try{router.push('/diagnosis/'+store.createAnalysis(task.value.id,selected.value,analysisFailure.value?'failure':'success'))}catch(e){store.notify((e as Error).message)}}
function report(){if(task.value)router.push('/diagnosis/'+store.createReport(task.value.id))}
function exportCsv(){if(!task.value)return;csv([['异常编号','参数','开始','结束','观测','基准','单位','程度'],...resultEvents.value.map(a=>[a.id,metricInfo[a.metric].label,time(a.start),a.end?time(a.end):'持续中',a.value,a.baseline,metricInfo[a.metric].unit,a.level])],task.value.id+'-异常.csv')}
function exportData(){csv([['采集时间','测点','参数','数值','单位','数据质量','运行状态'],...dataRows.value.map(s=>[time(s.time),s.point,metricInfo[s.metric].label,displayValue(s),s.unit,s.quality,s.state.label])],`${context.value?.segment.code}-监测数据.csv`)}
function syncSelection(){selected.value=typeof route.query.selected==='string'?resultEvents.value.filter(a=>String(route.query.selected).split(',').includes(a.id)).map(a=>a.id):resultEvents.value.map(a=>a.id)}
watch([query,status,all],()=>listPage.value=1)
watch([viewMetrics,monitorStart,monitorEnd,onlyIssues],()=>dataPage.value=1)
watch(()=>[task.value?.id,context.value?.segment.id],()=>{monitorStart.value=task.value?.start??'2026-11-03T00:00';monitorEnd.value=task.value?.end??'2026-11-03T08:00';draftStart.value=monitorStart.value;draftEnd.value=monitorEnd.value;const m=parameters.value.includes('return')?'return':parameters.value[0];viewMetrics.value=m?[m]:[];compare.value=false;focus.value='';rangeError.value='';showList.value=false;syncSelection();Object.assign(form,{start:monitorStart.value,end:monitorEnd.value,metrics:[...parameters.value],parentId:''})},{immediate:true})
watch(()=>task.value?.status,s=>{if(s==='success')syncSelection()})
watch(()=>route.query.selected,()=>syncSelection())
watch(()=>[route.query.create,route.query.start,route.query.end,route.query.metric],()=>{if(route.query.create){open();if(typeof route.query.start==='string')form.start=route.query.start;if(typeof route.query.end==='string')form.end=route.query.end;if(typeof route.query.metric==='string'&&parameters.value.includes(route.query.metric as Metric))form.metrics=[route.query.metric as Metric]}},{immediate:true})
</script>

<template>
<div class="page-stack monitoring-page">
 <div class="page-actions"><div><h2>数据监测</h2><p class="muted">参数监控、异常定位与检测记录</p></div><div class="flex wrap"><span class="badge orange">模拟数据</span><button class="secondary" @click="toggleHistory"><History :size="16"/>{{showList?'收起任务记录':'任务记录'}}</button><button class="primary" @click="open()"><Plus :size="16"/>新建检测</button></div></div>
 <div class="monitor-context"><span>{{context?.enterprise.name??'未选择企业'}} / {{context?.network.name??'未选择管网'}} / <b>{{context?.segment.name??'未选择管段'}}</b></span><span class="muted">数据来源：本地示例 · 历史采样，非实时连接</span></div>
 <nav class="monitor-shortcuts" aria-label="监测区域"><a href="#monitor-parameters">选参数</a><a href="#monitor-trend">看趋势</a><a href="#monitor-events">查异常</a><a href="#detection-config">做检测</a></nav>
 <p v-if="route.params.id&&!task" class="error" role="alert">该检测任务不存在。可以继续监测当前管段，或从底部历史记录选择有效任务。</p>
 <div v-if="!context" class="empty">请先选择监测对象。<RouterLink to="/networks?pick=1">进入管网管理</RouterLink></div>
 <div v-else class="monitor-layout">
  <Panel id="monitor-parameters" title="监测参数" class="monitor-parameters"><template #tools><span class="muted">{{parameters.length}} 项可用</span></template>
   <button class="secondary wide" :aria-pressed="compare" @click="toggleCompare">{{compare?'退出多参数对比':'多参数对比'}}</button>
   <div v-for="group in groups.filter(g=>g.metrics.some(m=>parameters.includes(m)))" :key="group.name" class="parameter-group"><button class="parameter-group-toggle" :aria-expanded="!collapsed.includes(group.name)" @click="toggleGroup(group.name)"><span>{{group.name}}</span><ChevronDown :size="15" :class="{collapsed:collapsed.includes(group.name)}"/></button>
    <div v-if="!collapsed.includes(group.name)"><button v-for="m in group.metrics.filter(m=>parameters.includes(m))" :key="m" :aria-label="'监测'+metricInfo[m].label" :aria-pressed="viewMetrics.includes(m)" :class="['parameter-item',{selected:viewMetrics.includes(m)}]" @click="choose(m)"><span class="flex"><i :style="{background:metricInfo[m].color}" class="dot"></i><strong>{{metricInfo[m].label}}</strong></span><small :class="parameterState(m)==='存在异常'?'red':parameterState(m)==='质量待核验'?'amber':'muted'">{{parameterState(m)}}</small></button></div>
   </div><div v-if="!parameters.length" class="empty">当前管段未配置监测参数。</div><p class="muted small">仅列出当前管段已提供的参数，不补造未接入测点。</p>
  </Panel>
  <div class="page-stack monitor-center">
   <Panel title="参数数值"><template #tools><span class="muted">所选范围最新有效采样</span></template><div v-if="latest.length" :class="['monitor-readings',{multiple:latest.length>1}]"><div v-for="item in latest" :key="item.metric" class="monitor-reading"><div class="flex between wrap"><strong>{{metricInfo[item.metric].label}}</strong><span :class="['badge',!item.sample?'amber':sampleState(item.sample,viewEvents).kind==='anomaly'?'red':'green']">{{item.sample?sampleState(item.sample,viewEvents).label:'无有效数据'}}</span></div><div class="metric-value" :style="{color:metricInfo[item.metric].color}">{{displayValue(item.sample)}}<small>{{metricInfo[item.metric].unit}}</small></div><small class="muted">{{item.sample?time(item.sample.time):'等待有效采样'}} · {{metricInfo[item.metric].point}}</small></div></div><div v-else class="empty">请先选择可用监测参数。</div></Panel>
   <Panel id="monitor-trend" title="历史趋势与异常标记"><template #tools><button class="icon-button" aria-label="复位视窗" @click="resetChart"><RotateCcw :size="16"/></button></template>
    <form class="monitor-range" @submit.prevent="applyRange"><label>监测开始时间<input v-model="draftStart" type="datetime-local" required/></label><label>监测结束时间<input v-model="draftEnd" type="datetime-local" required/></label><button class="secondary" type="submit">应用范围</button></form>
    <div class="flex between wrap mt"><div class="segmented"><button v-for="h in [1,6,8,24]" :key="h" @click="preset(h)">{{h}} 小时</button></div><span class="muted small">{{compare?'多参数对比 · 独立单位坐标':'单参数监测'}}</span></div>
    <p v-if="rangeError" class="error" role="alert">{{rangeError}}</p><p v-if="coverageNotice" class="notice mt">部分监测时段尚未检测，异常统计仅来自已有检测覆盖区间。</p>
    <TelemetryChart v-if="viewMetrics.length" :key="context.segment.id" ref="chart" :context="context" :metrics="viewMetrics" :samples="chartSamples" :start="monitorStart" :end="monitorEnd" :anomalies="viewEvents" :focus-id="focus" @select="locate"/>
    <p class="chart-caption">红点与虚线区间表示数值异常；点击右侧事件定位。{{focused?'已定位：'+focused.title:'可使用图例和缩放条查看历史变化。'}}</p>
   </Panel>
   <Panel title="采样数据明细"><template #tools><label class="check-label"><input v-model="onlyIssues" type="checkbox"/>仅异常 / 质量问题</label><button class="secondary" :disabled="!dataRows.length" @click="exportData"><Download :size="14"/>导出监测 CSV</button></template>
    <div class="monitor-quality"><span class="muted">{{samples.length}} 条采样 · {{viewEvents.length}} 项运行异常事件</span><span :class="qualityCount?'amber':'muted'">数据质量问题 {{qualityCount}} 条（单独统计）</span></div>
    <div class="table-wrap"><table><thead><tr><th>采集时间</th><th>参数 / 测点</th><th>数值</th><th>单位</th><th>运行 / 质量状态</th></tr></thead><tbody><tr v-for="s in pageRows" :key="s.time+s.metric" :class="{ 'sample-anomaly':s.state.kind==='anomaly','sample-quality':s.state.kind==='quality'}"><td class="mono">{{time(s.time)}}</td><td>{{metricInfo[s.metric].label}}<small>{{s.point}}</small></td><td class="mono">{{displayValue(s)}}</td><td>{{s.unit||'—'}}</td><td :class="s.state.kind==='anomaly'?'red':s.state.kind==='quality'?'amber':'muted'">{{s.state.label}}</td></tr><tr v-if="!dataRows.length"><td colspan="5" class="empty">{{onlyIssues?'当前筛选下没有异常或质量问题采样。':'当前监测范围暂无采样数据，请调整时间或管段。'}}</td></tr></tbody></table></div>
    <div class="pagination"><span>共 {{dataRows.length}} 条 · 第 {{dataPage}} / {{dataPages}} 页</span><button :disabled="dataPage===1" @click="dataPage--">上一页</button><button :disabled="dataPage>=dataPages" @click="dataPage++">下一页</button></div>
   </Panel>
  </div>
  <Panel id="monitor-events" title="异常信息" class="monitor-events"><template #tools><TriangleAlert :size="16" class="red"/></template>
   <label class="form-stack small">事件范围<select v-model="eventScope" aria-label="异常事件范围"><option value="selected">所选监测参数</option><option value="all">全部可用参数</option></select></label><div class="monitor-event-count mt"><strong class="red">{{visibleEvents.length}}</strong><span>项数值异常事件<br/><small class="muted">当前时间范围 · {{eventScope==='all'?'全部参数':'所选参数'}}</small></span></div><p class="muted small">选中参数涉及 {{viewEvents.length}} 项。仅识别数值异常，原因与解决建议在 AI诊断查看。</p>
   <div v-if="task?.status!=='success'" class="notice mt">{{running?'检测正在执行，完成后更新事件。':task?.status==='failed'?'检测失败，不将旧结果当作本次结论。':'尚无已完成检测，请使用底部检测区。'}}</div>
   <div class="monitor-event-list"><button v-for="a in visibleEvents" :key="a.id" :class="['monitor-event',{selected:focus===a.id}]" :aria-label="'定位'+a.title" @click="locate(a.id)"><span class="flex between wrap"><strong>{{a.title}}</strong><span class="badge red">{{a.level}}</span></span><small>{{time(a.start)}} · {{metricInfo[a.metric].label}}</small><span class="mono">{{a.baseline}} → <b class="red">{{a.value}} {{metricInfo[a.metric].unit}}</b></span><span class="text-button">查看并定位 <ArrowRight :size="13"/></span></button></div>
   <div v-if="!visibleEvents.length&&task?.status==='success'" class="empty">当前监测范围未检出异常事件。</div>
   <div v-if="focused" class="monitor-event-detail"><h3>异常详情</h3><p>{{focused.title}}</p><dl class="detail-list"><div><dt>发生时间</dt><dd>{{time(focused.start)}}</dd></div><div><dt>结束时间</dt><dd>{{resultEvents.find(a=>a.id===focused!.id)?.end?time(focused.end??undefined):'检测结束时仍持续（截至 '+time(task?.end)+'）'}}</dd></div><div><dt>观测值</dt><dd class="red">{{focused.value}} {{metricInfo[focused.metric].unit}}</dd></div><div><dt>基准值</dt><dd>{{focused.baseline}} {{metricInfo[focused.metric].unit}}</dd></div></dl><p class="muted small">{{focused.evidence}}</p></div>
  </Panel>
 </div>
 <section id="detection-config" aria-label="异常检测配置" class="monitor-detection-section">
 <Panel title="异常检测与记录"><template #tools><button class="text-button" @click="useView">使用当前监测范围与参数</button></template>
  <form class="monitor-detection-form" @submit.prevent="submit"><label>任务名称 *<input v-model="form.name" required maxlength="80"/></label><label>开始时间 *<input v-model="form.start" type="datetime-local" required/></label><label>结束时间 *<input v-model="form.end" type="datetime-local" required/></label><label>残差系数（σ，0–10）*<input v-model.number="form.threshold" type="number" min="0.1" max="10" step="0.1" required/></label>
   <fieldset><legend>检测参数 *</legend><label v-for="m in parameters" :key="m" class="check-label"><input v-model="form.metrics" type="checkbox" :value="m"/>{{metricInfo[m].label}}（{{metricInfo[m].unit}}）</label><p v-if="!parameters.length" class="error">当前管段未配置监测参数，请切换对象。</p></fieldset>
   <label>检测算法<select><option>时序残差聚类 V2.3（演示）</option></select></label><label>演示场景<select v-model="form.scenario"><option value="anomaly">检测到异常</option><option value="normal">未检出异常</option><option value="failure">服务失败（验证重试）</option></select></label><div class="monitor-submit"><button class="primary" type="submit" :disabled="submitting||running||!context||!parameters.length||!context.segment.hasData">{{running?'检测执行中…':'创建并执行检测'}}</button></div>
  </form><p class="muted small">可用演示数据：2026-11-03 00:00 至 2026-11-04 00:00。检测保存到本机；残差系数是演示配置，不连接真实算法。</p><p v-if="error" class="error" role="alert">{{error}}</p>
 </Panel></section>
 <Panel v-if="task" title="当前检测结果"><template #tools><button class="secondary" @click="open(task)"><Copy :size="15"/>复制配置</button><button class="secondary" :disabled="task.status!=='success'" @click="report">生成检测报告</button></template>
  <div class="flex between wrap"><div><h3>{{task.name}}</h3><p class="mono orange">{{task.id}}</p><p class="muted small">{{time(task.start)}} — {{time(task.end)}} · {{task.metrics.map(m=>metricInfo[m].label).join('、')}}</p></div><span :class="['badge',task.status==='failed'?'red':task.status==='success'?'green':'amber']">检测状态：{{statusText[task.status]}}<template v-if="task.status==='success'">（检出 {{task.anomalies.length}} 处异常）</template></span></div>
  <div v-if="running" class="notice mt"><span class="loader"></span> 演示检测正在处理所选参数，任务已保存，离开后可从任务记录恢复。</div><div v-else-if="task.status==='failed'" class="notice mt"><p class="error">{{task.error}}</p><button class="primary mt" @click="retry">重试检测</button></div>
  <template v-else><div class="flex between wrap mt"><h3>数值异常事件清单</h3><label class="check-label"><input type="checkbox" :checked="!!resultEvents.length&&selected.length===resultEvents.length" :disabled="!resultEvents.length" @change="selected=selected.length===resultEvents.length?[]:resultEvents.map(a=>a.id)"/>全选 {{selected.length}} / {{resultEvents.length}}</label></div>
   <div class="table-wrap"><table><thead><tr><th>分析选择 / 异常事件</th><th>发生时间</th><th>观测 / 基准</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="a in resultEvents" :key="a.id" :data-anomaly="a.id" :class="{selected:focus===a.id}"><td><label class="check-label"><input v-model="selected" type="checkbox" :value="a.id"/>{{a.title}}</label></td><td>{{time(a.start)}}</td><td class="mono">{{a.value}} / {{a.baseline}} {{metricInfo[a.metric].unit}}</td><td class="red">{{a.level}}</td><td><button class="text-button" @click="monitorStart=task.start;monitorEnd=task.end;draftStart=task.start;draftEnd=task.end;locate(a.id)">区间回放</button></td></tr></tbody></table></div>
   <div v-if="!resultEvents.length" class="empty"><h3 class="green">检测完成，未检出异常</h3><p>这是成功结果，可查看采样或生成阶段性检测报告。</p></div>
   <div class="flex between wrap mt"><button class="secondary" :disabled="!resultEvents.length" @click="exportCsv">导出异常时序 CSV</button><div class="flex wrap"><label class="check-label muted"><input v-model="analysisFailure" type="checkbox"/>演示分析失败场景</label><button class="primary" :disabled="!selected.length" @click="analyze">将选中异常（{{selected.length}} 项）送入 AI诊断 <ArrowRight :size="15"/></button></div></div>
  </template>
 </Panel>
 <Panel v-if="showList||!task" id="detection-history" title="历史检测任务"><div class="filter-bar"><label class="monitor-search"><Search :size="15"/><input v-model="query" aria-label="搜索检测任务" placeholder="搜索任务编号或名称"/></label><select v-model="status" aria-label="检测任务状态"><option value="">全部状态</option><option v-for="(text,s) in statusText" :key="s" :value="s">{{text}}</option></select><label class="check-label"><input v-model="all" type="checkbox"/>全部管段</label><button class="secondary" @click="query='';status='';all=false">重置</button></div><div class="table-wrap"><table><thead><tr><th>任务</th><th>所属管段</th><th>创建时间</th><th>状态</th><th>异常数</th><th>操作</th></tr></thead><tbody><tr v-for="d in listRows" :key="d.id"><td>{{d.name}}<small>{{d.id}}</small></td><td>{{d.context.segment.name}}</td><td>{{time(d.createdAt)}}</td><td>{{statusText[d.status]}}</td><td>{{d.status==='success'?d.anomalies.length:'—'}}</td><td><RouterLink :to="'/detections/'+d.id" class="text-button">查看</RouterLink></td></tr><tr v-if="!tasks.length"><td colspan="6" class="empty">当前范围没有匹配任务，请修改筛选或新建检测。</td></tr></tbody></table></div><div class="pagination"><span>共 {{tasks.length}} 条 · 第 {{listPage}} / {{listPages}} 页</span><button :disabled="listPage===1" @click="listPage--">上一页</button><button :disabled="listPage>=listPages" @click="listPage++">下一页</button></div></Panel>
</div>
</template>
