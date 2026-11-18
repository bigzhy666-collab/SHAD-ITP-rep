import {expect,it} from 'vitest'
import type {Sample} from '../domain'
import {seedWorkspace,samplesFor} from './demo'
import {eventsInScope,sampleIssue,sampleState} from './monitoring'
const d=seedWorkspace().detections[0]!
const sample:Sample={time:'2026-11-03T03:30:00',metric:'return',value:33.5,unit:'℃',quality:'有效（演示）',point:'TE-102B'}
it('时间与参数共同决定事件范围，结束仍持续的事件保留',()=>{
 expect(eventsInScope(d.anomalies,['return'],'2026-11-03T03:00','2026-11-03T04:00').map(a=>a.metric)).toEqual(['return'])
 expect(eventsInScope(d.anomalies,['return'],'2026-11-03T04:00','2026-11-03T05:00')).toEqual([])
 expect(eventsInScope(d.anomalies,['pressure'],'2026-11-03T07:00','2026-11-03T08:00')).toHaveLength(1)
 expect(eventsInScope(d.anomalies,d.metrics,'bad','bad')).toEqual([])
})
it('异常区间内的有效数据才标记运行异常，正常采样保留独立状态',()=>{
 expect(sampleState(sample,d.anomalies).kind).toBe('anomaly')
 expect(sampleState({...sample,time:'2026-11-03T01:00:00'},d.anomalies).kind).toBe('valid')
 expect(sampleState({...sample,metric:'supply'},d.anomalies).kind).toBe('valid')
})
it('缺失、格式和质量错误不被归入运行异常',()=>{
 for(const row of [{...sample,value:null},{...sample,value:NaN},{...sample,time:'not-a-time'},{...sample,unit:''},{...sample,quality:'采集失败'}]){
  expect(sampleIssue(row as Sample)).not.toBe('');expect(sampleState(row as Sample,d.anomalies).kind).toBe('quality')
 }
})
it('当前演示参数来自对象，不生成供水压力等未接入数据',()=>{
 const rows=samplesFor(d.context);expect(new Set(rows.map(s=>s.metric))).toEqual(new Set(d.context.segment.metrics))
 expect(rows.every(s=>!sampleIssue(s))).toBe(true)
 expect(samplesFor({...d.context,segment:{...d.context.segment,hasData:false}})).toEqual([])
})
