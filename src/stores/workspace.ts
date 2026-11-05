import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { Analysis, Context, Detection, Metric, Report, Workspace } from '../domain'
import { anomaliesFor, causesFor, seedWorkspace, validateDetection } from '../services/demo'
const KEY = 'shad-workspace-v3'
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
 const context = computed<Context | null>(() => contextFor(state.value.selectedId))
 function contextFor(id: string): Context | null {
  const segment = state.value.segments.find(s => s.id === id); const network = state.value.networks.find(n => n.id === segment?.networkId); const enterprise = state.value.enterprises.find(e => e.id === network?.enterpriseId)
  return segment && network && enterprise ? { segment, network, enterprise } : null
 }
 function notify(text: string) { message.value = text }
 function select(id: string) { if (contextFor(id)) { state.value.selectedId = id; save() } }
 function tick() {
  const now = Date.now()
  for (const t of [...state.value.detections, ...state.value.analyses]) {
   if (t.status === 'queued' && now >= t.readyAt - 2200) t.status = 'running'
   if ((t.status === 'running' || t.status === 'queued') && now >= t.readyAt) {
    t.status = t.scenario === 'failure' ? 'failed' : 'success'
    if (t.status === 'failed') t.error = '演示服务故障，请重试；原任务记录已保留。'
    if ('anomalies' in t && t.status === 'success') t.anomalies = t.scenario === 'normal' ? [] : anomaliesFor(t.metrics,t.context.segment.kind==='primary').filter(a => new Date(a.start).getTime() < new Date(t.end).getTime() && new Date(a.end ?? t.end).getTime() > new Date(t.start).getTime()).map(a => ({ ...a, id: `${t.id}-${a.id}`, start: new Date(Math.max(new Date(t.start).getTime(), new Date(a.start).getTime())).toISOString() }))
   }
  }
 }
 function createDetection(input: { name: string; start: string; end: string; metrics: Metric[]; threshold: number; scenario: Detection['scenario']; parentId?: string; context?: Context }) {
  const c = input.context ?? context.value
  const error = validateDetection(c, input.start, input.end, input.metrics, input.threshold); if (error) throw new Error(error)
  const t: Detection = { ...input, id: `DET-${Date.now()}`, context: clone(c!), algorithm: '时序残差聚类 V2.3（演示）', status: 'queued', createdAt: new Date().toISOString(), readyAt: Date.now() + 3500, anomalies: [] }
  state.value.detections.unshift(t); save(); return t.id
 }
 function createAnalysis(detectionId: string, anomalyIds: string[], scenario: Analysis['scenario'] = 'success', parentId?: string) {
  const d = state.value.detections.find(t => t.id === detectionId)
  if (!d || d.status !== 'success') throw new Error('请选择已完成的检测任务。')
  if (!anomalyIds.length || anomalyIds.some(id => !d.anomalies.some(a => a.id === id))) throw new Error('至少选择一项有效异常。')
  const pending = state.value.analyses.find(a => a.detectionId === detectionId && [...a.anomalyIds].sort().join() === [...anomalyIds].sort().join() && ['running', 'queued'].includes(a.status))
  if (pending) { notify('已有相同分析正在执行，已打开原任务。'); return pending.id }
  const a: Analysis = { id: `AI-${Date.now()}`, detectionId, anomalyIds: [...anomalyIds], context: clone(d.context), model: 'ThermalNet-Mini v1.8（演示）', status: 'queued', createdAt: new Date().toISOString(), readyAt: Date.now() + 3500, scenario, parentId }
  state.value.analyses.unshift(a); save(); return a.id
 }
 function createReport(detectionId: string, analysisId?: string): string {
  const d = state.value.detections.find(t => t.id === detectionId); const a = state.value.analyses.find(t => t.id === analysisId)
  if (!d || d.status !== 'success') throw new Error('报告需要已完成的检测任务。')
  if (analysisId && (!a || a.status !== 'success' || a.detectionId !== d.id || a.context.segment.id !== d.context.segment.id)) throw new Error('分析任务与检测来源不一致或尚未完成。')
  const r: Report = { id: `REP-${Date.now()}`, title: a ? '热力管网异常辅助诊断报告' : '管段异常检测阶段性报告', detectionId, analysisId, context: clone(d.context), version: Math.max(0, ...state.value.reports.filter(r => r.detectionId === detectionId).map(r => r.version)) + 1, createdAt: new Date().toISOString(), note: '', detection: clone(d), analysis: a ? clone(a) : undefined, causes: a ? clone(causesFor(d, a.anomalyIds)) : [] }
  state.value.reports.unshift(r); save(); return r.id
 }
 function archive(id: string, note: string) { const r = state.value.reports.find(r => r.id === id); if (!r || r.archivedAt) return; r.note = note; r.archivedAt = new Date().toISOString(); save(); notify(storageError.value ? '已在本次会话归档；本地持久化失败。' : '报告已归档，当前版本已锁定。') }
 async function refresh() { if (refreshing.value) return; refreshing.value = true; await new Promise(r => setTimeout(r, 450)); tick(); updatedAt.value = new Date().toISOString(); refreshing.value = false; notify('演示数据已刷新，筛选与任务记录已保留。') }
 return { state, context, contextFor, select, storageError, message, notify, save, tick, createDetection, createAnalysis, createReport, archive, refresh, refreshing, updatedAt }
})
