import {useIntegration} from './integration'
import {localApi,errorText} from '../services/local/api'
import type {Organizations} from '../services/local/types'
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { Analysis, Context, Detection, Metric, Report, Workspace } from '../domain'
import { anomaliesFor, causesFor, seedWorkspace, validateDetection } from '../services/demo'
import { diagnosisSteps, restoredSteps } from '../services/diagnosis'
const KEY = 'shad-workspace-v3'
let sequence=0
function nextId(prefix:string){return `${prefix}-${Date.now()}-${sequence++}`}
function clone<T>(x: T): T { return JSON.parse(JSON.stringify(x)) as T }
export const useWorkspace = defineStore('workspace', () => {
 const storageError = ref(''), message = ref(''), refreshing = ref(false), updatedAt = ref(new Date().toISOString())
 function load(): Workspace {
  try { const raw = localStorage.getItem(KEY); if (!raw) return seedWorkspace(); const v = JSON.parse(raw); if (v.version !== 3 || !Array.isArray(v.detections) || !Array.isArray(v.reports) || !Array.isArray(v.segments) || !Array.isArray(v.networks) || !Array.isArray(v.enterprises) || !Array.isArray(v.analyses)) throw new Error(); return v }
  catch { storageError.value = '本地记录读取失败，已载入演示初始数据。'; return seedWorkspace() }
 }
 const state = ref<Workspace>(load())
 function save() { try { localStorage.setItem(KEY, JSON.stringify(state.value)); storageError.value = '' } catch { storageError.value = '本地保存失败：浏览器存储不可用或空间不足，当前修改仅在本次会话有效。' } }
 watch(state, save, { deep: true })
 const integration=useIntegration(), localOrganizations=ref<Organizations>({enterprises:[],networks:[],segments:[]}), organizationError=ref(''),organizationLoading=ref(false),localSelected=ref('')
 try{localSelected.value=localStorage.getItem('shad-local-segment')??''}catch{}
 const supportsOrganizations=ref(false)
 watch(()=>integration.runtime,value=>{if(value?.capabilities.organizationManagement)supportsOrganizations.value=true},{immediate:true})
 const managed=computed(()=>integration.local&&supportsOrganizations.value)
 const organizations=computed<Organizations>(()=>managed.value?localOrganizations.value:{enterprises:state.value.enterprises.map(e=>({...e,revision:1})),networks:state.value.networks.map(n=>({...n,revision:1})),segments:state.value.segments.map(s=>({...s,revision:1}))})
 let organizationRun=0
 async function reloadOrganizations(){const run=++organizationRun;if(!managed.value||!integration.ready)return;organizationLoading.value=true;organizationError.value='';try{const rows=await localApi.organizations();if(run===organizationRun&&managed.value){localOrganizations.value=rows;if(!localSelected.value&&contextFor(state.value.selectedId))select(state.value.selectedId)}}catch(e){if(run===organizationRun)organizationError.value=errorText(e)}finally{if(run===organizationRun)organizationLoading.value=false}}
 watch(()=>[integration.ready,integration.revision],()=>{if(managed.value)void reloadOrganizations();else{organizationRun++;organizationLoading.value=false;localOrganizations.value={enterprises:[],networks:[],segments:[]}}},{immediate:true})
 const context = computed<Context | null>(() => integration.local&&!integration.ready?null:contextFor(managed.value?localSelected.value:state.value.selectedId))
 function contextFor(id: string): Context | null {
  if(managed.value){
   const segment=localOrganizations.value.segments.find(s=>s.id===id),network=localOrganizations.value.networks.find(n=>n.id===segment?.networkId),enterprise=localOrganizations.value.enterprises.find(e=>e.id===network?.enterpriseId)
   return segment?.active&&network?.active&&enterprise?.active?{enterprise,network:{...network,enterpriseId:network.enterpriseId!},segment:{...segment,networkId:segment.networkId!,diameter:0,length:0,kind:'secondary',metrics:[],hasData:false}}:null
  }
  const segment = state.value.segments.find(s => s.id === id); const network = state.value.networks.find(n => n.id === segment?.networkId); const enterprise = state.value.enterprises.find(e => e.id === network?.enterpriseId)
  return segment && network && enterprise ? { segment, network, enterprise } : null
 }
 function notify(text: string) { message.value = text }
 function select(id: string) { if (contextFor(id)) {if(managed.value){localSelected.value=id;try{localStorage.setItem('shad-local-segment',id)}catch{organizationError.value='对象选择无法保存，下次启动请重新选择。'}}else{state.value.selectedId = id; save()} } }
 function tick() {
  const now = Date.now()
  for (const t of [...state.value.detections, ...state.value.analyses]) {
   if (t.status === 'queued' && now >= t.readyAt - ('anomalies' in t ? 2200 : 8000)) t.status = 'running'
   if (!('anomalies' in t) && (t.status === 'queued' || t.status === 'running')) {
    const source=state.value.detections.find(d=>d.id===t.detectionId)
    if(!source){t.status='failed';t.error='来源检测任务不存在，请从有效检测重新发起诊断。';continue}
    t.steps ??= diagnosisSteps(source,t.anomalyIds)
    const stage=Math.max(0,Math.min(4,Math.floor((now-(t.readyAt-8000))/1600)))
    t.steps.forEach((step,i)=>step.state=t.status==='queued'?'pending':i<stage?'done':i===stage?'running':'pending')
   }
   if ((t.status === 'running' || t.status === 'queued') && now >= t.readyAt) {
    t.status = t.scenario === 'failure' ? 'failed' : 'success'
    if (!('anomalies' in t)) {
     t.steps?.forEach((step,i)=>step.state=t.status==='success'?'done':i<3?'done':i===3?'failed':'pending')
     if(t.status==='success'){const d=state.value.detections.find(d=>d.id===t.detectionId);if(d)t.causes=clone(causesFor(d,t.anomalyIds))}
    }
    if (t.status === 'failed') t.error = '演示服务故障，请重试；原任务记录已保留。'
    if ('anomalies' in t && t.status === 'success') t.anomalies = t.scenario === 'normal' ? [] : anomaliesFor(t.metrics,t.context.segment.kind==='primary').filter(a => new Date(a.start).getTime() < new Date(t.end).getTime() && new Date(a.end ?? t.end).getTime() > new Date(t.start).getTime()).map(a => ({ ...a, id: `${t.id}-${a.id}`, start: new Date(Math.max(new Date(t.start).getTime(), new Date(a.start).getTime())).toISOString() }))
   }
  }
  for(const a of state.value.analyses)if(a.status==='success'&&a.steps?.length)ensureReport(a.id)
 }
 function createDetection(input: { name: string; start: string; end: string; metrics: Metric[]; threshold: number; scenario: Detection['scenario']; parentId?: string; context?: Context }) {
  const c = input.context ?? context.value
  const error = validateDetection(c, input.start, input.end, input.metrics, input.threshold); if (error) throw new Error(error)
  const t: Detection = { ...input, id: nextId('DET'), context: clone(c!), algorithm: '时序残差聚类 V2.3（演示）', status: 'queued', createdAt: new Date().toISOString(), readyAt: Date.now() + 3500, anomalies: [] }
  state.value.detections.unshift(t); save(); return t.id
 }
 function createAnalysis(detectionId: string, anomalyIds: string[], scenario: Analysis['scenario'] = 'success', parentId?: string) {
  const d = state.value.detections.find(t => t.id === detectionId)
  if (!d || d.status !== 'success') throw new Error('请选择已完成的检测任务。')
  if (!anomalyIds.length || anomalyIds.some(id => !d.anomalies.some(a => a.id === id))) throw new Error('至少选择一项有效异常。')
  anomalyIds=[...new Set(anomalyIds)]
  const pending = state.value.analyses.find(a => a.detectionId === detectionId && [...a.anomalyIds].sort().join() === [...anomalyIds].sort().join() && ['running', 'queued'].includes(a.status))
  if (pending) { notify('已有相同分析正在执行，已打开原任务。'); return pending.id }
  const a: Analysis = { id: nextId('AI'), detectionId, anomalyIds: [...new Set(anomalyIds)], context: clone(d.context), model: 'ThermalNet-Mini v1.8（演示）', status: 'queued', createdAt: new Date().toISOString(), readyAt: Date.now() + 9000, scenario, parentId, steps:diagnosisSteps(d,anomalyIds) }
  state.value.analyses.unshift(a); save(); return a.id
 }
 function createReport(detectionId: string, analysisId?: string): string {
  const d = state.value.detections.find(t => t.id === detectionId); const a = state.value.analyses.find(t => t.id === analysisId)
  if (!d || d.status !== 'success') throw new Error('报告需要已完成的检测任务。')
  if (analysisId && (!a || a.status !== 'success' || a.detectionId !== d.id || a.context.segment.id !== d.context.segment.id)) throw new Error('分析任务与检测来源不一致或尚未完成。')
  const r: Report = { id: nextId('REP'), title: a ? '热力管网异常辅助诊断报告' : '管段异常检测阶段性报告', detectionId, analysisId, context: clone(d.context), version: Math.max(0, ...state.value.reports.filter(r => r.detectionId === detectionId).map(r => r.version)) + 1, createdAt: new Date().toISOString(), note: '', detection: clone(d), analysis: a ? clone(a) : undefined, causes: a ? clone(a.causes??causesFor(d, a.anomalyIds)) : [], process: a ? clone(restoredSteps(a,d)) : undefined }
  state.value.reports.unshift(r); save(); return r.id
 }
 function ensureReport(analysisId:string):string {
  const a=state.value.analyses.find(a=>a.id===analysisId);if(!a||a.status!=='success')throw new Error('诊断尚未完成，不能生成报告。')
  return state.value.reports.find(r=>r.analysisId===analysisId)?.id??createReport(a.detectionId,a.id)
 }
 function archive(id: string, note: string) { const r = state.value.reports.find(r => r.id === id); if (!r || r.archivedAt) return; r.note = note; r.archivedAt = new Date().toISOString(); save(); notify(storageError.value ? '已在本次会话归档；本地持久化失败。' : '报告已归档，当前版本已锁定。') }
 async function refresh() { if (refreshing.value) return; refreshing.value = true; await new Promise(r => setTimeout(r, 450)); tick(); updatedAt.value = new Date().toISOString(); refreshing.value = false; notify('演示数据已刷新，筛选与任务记录已保留。') }
 return { state, context, contextFor, select, organizations, managed, organizationLoading, organizationError, reloadOrganizations, storageError, message, notify, save, tick, createDetection, createAnalysis, createReport, ensureReport, archive, refresh, refreshing, updatedAt }
})
