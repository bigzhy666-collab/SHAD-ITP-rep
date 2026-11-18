import {expect,it} from 'vitest'
import type {Report} from './types'
import {assertReportSource,localReportText} from './report'
const task={id:'d-1',contextSnapshot:{enterprise:{name:'企业'},network:{name:'管网'},segment:{name:'管段'},station:{id:'s-1',name:'站点'}},datasetSnapshot:{name:'数据',version:'1',sourceChecksum:'data-checksum'},modelSnapshot:{name:'本站模型',version:'1',artifactChecksum:'model-checksum',isDemo:false},range:{start:'2026-11-08T00:00:00+08:00',end:'2026-11-08T01:00:00+08:00'}}
function fixture():Report{return {id:'report-1',version:1,note:'人工备注',eventIds:['e-1'],diagnosisId:null,detectionId:'d-1',snapshot:{task:structuredClone(task),result:{detectionId:'d-1',contextSnapshot:structuredClone(task.contextSnapshot),modelSnapshot:structuredClone(task.modelSnapshot),datasetSnapshot:structuredClone(task.datasetSnapshot),range:{...task.range},preprocessingVersion:'1',summary:{pointCount:3,alarmPointCount:2,eventCount:1},warnings:[]},events:[{id:'e-1',detectionId:'d-1',stationId:'s-1',title:'综合状态偏离',start:task.range.start,end:task.range.end,hours:1,peak_score:2,max_criticality:7,boundary:'touches_range_end'}],points:[],diagnosis:null}} as unknown as Report}
it('报告只包含实际检测事件和备注，不调用演示原因规则',()=>{
 const r=fixture(),text=localReportText(r).flatMap(s=>s.lines).join('\n');expect(text).toContain('人工备注');expect(text).not.toContain('原因诊断与核查建议');expect(text).toContain('触及检测结束边界');expect(text).not.toContain('示例权重');expect(assertReportSource(r)).toBe(r)
})
it('拒绝模型、数据版本、对象路径、时间范围或缺失诊断的来源混用',()=>{
 for(const change of [(r:Report)=>r.snapshot.result.modelSnapshot.version='other',(r:Report)=>r.snapshot.result.datasetSnapshot.sourceChecksum='other',(r:Report)=>r.snapshot.result.contextSnapshot.network.name='其他管网',(r:Report)=>r.snapshot.result.range.end='other',(r:Report)=>r.diagnosisId='missing']){const r=fixture();change(r);expect(()=>assertReportSource(r)).toThrow('报告快照与来源')}
})
it('来源字段顺序不影响同一快照的校验',()=>{
 const r=fixture();r.snapshot.result.range={end:task.range.end,start:task.range.start};expect(assertReportSource(r)).toBe(r)
})
it('拒绝跨任务、跨站点或事件列表不符的报告快照',()=>{
 for(const change of [(r:Report)=>r.detectionId='other',(r:Report)=>r.snapshot.events[0]!.stationId='other',(r:Report)=>r.eventIds.push('other')]){const r=structuredClone(fixture());change(r);expect(()=>assertReportSource(r)).toThrow('报告快照与来源')}
})
