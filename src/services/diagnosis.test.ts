import {beforeEach,afterEach,expect,it,vi} from 'vitest'
import {createPinia,setActivePinia} from 'pinia'
import {useWorkspace} from '../stores/workspace'
import {diagnosisSteps,restoredSteps} from './diagnosis'
import {reportEvents,reportText} from './export'

beforeEach(()=>{setActivePinia(createPinia());const memory=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(k:string)=>memory.get(k)??null,setItem:(k:string,v:string)=>memory.set(k,v)});vi.useFakeTimers();vi.setSystemTime(new Date('2026-11-05T10:00:00Z'))})
afterEach(()=>vi.useRealTimers())
it('单选阶段及报告不混入未选事件，具体建议完整',()=>{
 const s=useWorkspace(),d=s.state.detections[0]!,ids=[d.anomalies[0]!.id]
 const id=s.createAnalysis(d.id,ids),a=s.state.analyses[0]!
 expect(diagnosisSteps(d,ids)[0]!.evidence).toHaveLength(1)
 vi.advanceTimersByTime(1100);s.tick();expect(a.steps?.[0]?.state).toBe('running');expect(a.steps?.[1]?.state).toBe('pending')
 vi.advanceTimersByTime(1700);s.tick();expect(a.steps?.[0]?.state).toBe('done');expect(a.steps?.[1]?.state).toBe('running')
 vi.advanceTimersByTime(7000);s.tick();expect(a.status).toBe('success');expect(a.steps?.every(x=>x.state==='done')).toBe(true)
 const report=s.state.reports.find(r=>r.analysisId===id)!;expect(report).toBeDefined();expect(reportEvents(report)).toHaveLength(1)
 const text=reportText(report).flatMap(s=>s.lines).join('\n');expect(text).toContain('解决建议：');expect(text).toContain('复核标准：');expect(text).toContain('核对异常事件');expect(text).not.toContain(d.anomalies[1]!.title)
 s.tick();s.ensureReport(id);expect(s.state.reports.filter(r=>r.analysisId===id)).toHaveLength(1)
})
it('多选去重、零选拒绝、失败保留过程且不生成报告',()=>{
 const s=useWorkspace(),d=s.state.detections[0]!,ids=d.anomalies.map(a=>a.id)
 expect(()=>s.createAnalysis(d.id,[])).toThrow('至少');const id=s.createAnalysis(d.id,[...ids,ids[0]!],'failure');expect(s.state.analyses[0]!.anomalyIds).toEqual(ids)
 expect(s.createAnalysis(d.id,ids)).toBe(id);vi.advanceTimersByTime(10000);s.tick();const a=s.state.analyses[0]!
 expect(a.status).toBe('failed');expect(a.steps?.[0]?.state).toBe('done');expect(a.steps?.[3]?.state).toBe('failed');expect(s.state.reports.some(r=>r.analysisId===id)).toBe(false)
})
it('兼容旧记录并保持已保存的报告快照和归档',()=>{
 const s=useWorkspace(),a=s.state.analyses[0]!,d=s.state.detections[0]!,r=s.state.reports[0]!
 expect(a.steps).toBeUndefined();expect(restoredSteps(a,d).every(s=>s.state==='done')).toBe(true)
 r.causes.forEach(c=>{delete c.solution;delete c.verification});expect(reportText(r)[2]!.lines.join()).toContain('解决建议：现场确认')
 s.archive(r.id,'原版备注');const newId=s.createReport(d.id,a.id);expect(s.state.reports.find(x=>x.id===newId)?.process).toHaveLength(5);expect(r.note).toBe('原版备注');expect(r.archivedAt).toBeTruthy()
})
it('缺少关联参数不构造散点结论，来源丢失可恢复提示',()=>{
 const s=useWorkspace(),d=s.state.detections[0]!;d.metrics=['pressure'];const ids=[d.anomalies[1]!.id]
 expect(diagnosisSteps(d,ids)[2]!.chart).toBe('timeseries');const id=s.createAnalysis(d.id,ids);s.state.detections=[];s.tick();expect(s.state.analyses.find(a=>a.id===id)?.error).toContain('来源检测')
})
