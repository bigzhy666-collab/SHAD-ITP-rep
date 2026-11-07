import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { causesFor, samplesFor, seedWorkspace, validateDetection } from './demo'
import { useWorkspace } from '../stores/workspace'

beforeEach(()=>{setActivePinia(createPinia());const memory=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(k:string)=>memory.get(k)??null,setItem:(k:string,v:string)=>memory.set(k,v)})})
describe('检测与数据边界',()=>{
 const c=seedWorkspace().detections[0]!.context
 it('拒绝无对象和无参数检测',()=>{expect(validateDetection(null,'','',[],3)).toContain('选择');expect(validateDetection(c,'2026-11-03T00:00','2026-11-03T08:00',[],3.4)).toContain('至少')})
 it('拒绝倒置时间与超出可用范围',()=>{expect(validateDetection(c,'2026-11-03T09:00','2026-11-03T08:00',['return'],3.4)).toContain('早于');expect(validateDetection(c,'2026-11-01T00:00','2026-11-03T08:00',['return'],3.4)).toContain('可用范围')})
 it('无数据管段不合成采样',()=>{expect(samplesFor({...c,segment:{...c.segment,hasData:false}})).toEqual([])})
 it('采样固定可复现并保持工程单位',()=>{const rows=samplesFor(c);expect(samplesFor(c)).toEqual(rows);expect(rows.find(s=>s.metric==='pressure')?.unit).toBe('MPa')})
 it('切换视窗不改变同一时刻读数，所有时间点处于选择范围',()=>{const long=samplesFor(c,'2026-11-03T00:00','2026-11-04T00:00'),short=samplesFor(c);expect(long[long.length-1]?.time).toBe(new Date('2026-11-04T00:00').toISOString());const hit=short.find(s=>s.metric==='return'&&s.time===new Date('2026-11-03T03:36').toISOString())!;expect(long.find(s=>s.time===hit.time&&s.metric===hit.metric)?.value).toBe(hit.value)})
 it('超出演示时间窗口不补造采样',()=>{expect(samplesFor(c,'2026-11-02T00:00','2026-11-03T08:00')).toEqual([])})
 it('没有流量参数时不产生温度流量关联结论',()=>{const d=seedWorkspace().detections[0]!;d.metrics=['pressure'];d.anomalies=d.anomalies.filter(a=>a.metric==='pressure');const result=causesFor(d,d.anomalies.map(a=>a.id));expect(result).toHaveLength(1);expect(result[0]?.evidence).toContain('无法验证')})
})
describe('任务与报告来源',()=>{
 it('切换当前对象不改变历史任务快照',()=>{const s=useWorkspace();s.select('seg-2');expect(s.context?.segment.id).toBe('seg-2');expect(s.state.detections[0]?.context.segment.id).toBe('seg-1')})
 it('报告拒绝不匹配分析',()=>{const s=useWorkspace();expect(()=>s.createReport(s.state.detections[0]!.id,'missing')).toThrow('不一致')})
 it('阶段性报告不产生 AI 结论，新版本独立保留',()=>{const s=useWorkspace(),d=s.state.detections[0]!;const id=s.createReport(d.id);const r=s.state.reports.find(r=>r.id===id)!;expect(r.causes).toEqual([]);expect(r.version).toBe(2);expect(r.analysis).toBeUndefined();d.name='已改名';expect(r.detection.name).not.toBe('已改名')})
 it('运行任务去重并保留异常选择',()=>{const s=useWorkspace(),d=s.state.detections[0]!,ids=[d.anomalies[0]!.id];const id=s.createAnalysis(d.id,ids);expect(s.createAnalysis(d.id,ids)).toBe(id);expect(s.state.analyses[0]?.anomalyIds).toEqual(ids)})
 it('成功与无异常结果独立于失败',()=>{const s=useWorkspace();const id=s.createDetection({name:'无异常',start:'2026-11-03T00:00',end:'2026-11-03T08:00',metrics:['return'],threshold:3.4,scenario:'normal'});const task=s.state.detections.find(d=>d.id===id)!;task.readyAt=0;s.tick();expect(task.status).toBe('success');expect(task.anomalies).toEqual([])})
 it('检测时间不包含异常区间时成功返回空结果',()=>{const s=useWorkspace();const id=s.createDetection({name:'短区间',start:'2026-11-03T00:00',end:'2026-11-03T01:00',metrics:['return','pressure'],threshold:3.4,scenario:'anomaly'});const task=s.state.detections.find(d=>d.id===id)!;task.readyAt=0;s.tick();expect(task.status).toBe('success');expect(task.anomalies).toEqual([])})
 it('归档不可改写已归档备注',()=>{const s=useWorkspace(),r=s.state.reports[0]!;s.archive(r.id,'首次');s.archive(r.id,'覆盖');expect(r.note).toBe('首次')})
 it('保存失败发出明确错误',()=>{const s=useWorkspace();vi.stubGlobal('localStorage',{setItem:()=>{throw new Error('quota')}});s.save();expect(s.storageError).toContain('本地保存失败')})
})

