// Contract-only fixtures. This is not a backend or real model execution.
import type {Page as BrowserPage,Request} from '@playwright/test'
import type {Dataset,Diagnosis,Event,Model,Point,Report,Station,Task} from '../../src/services/local/types'
import {fields} from '../../src/services/local/fields'
export const station:Station={id:'station-1',name:'接口联调换热站',code:'LOCAL-001',enterpriseId:'ent-1',networkId:'net-1',segmentId:'seg-1',timezone:'Asia/Shanghai'}
export const dataset:Dataset={id:'dataset-1',version:'1',stationId:station.id,name:'联调数据集',status:'ready',timezone:'Asia/Shanghai',start:'2026-11-08T00:00:00+08:00',end:'2026-11-08T08:00:00+08:00',rawRowCount:17,normalizedRowCount:17,columns:fields.map(f=>({...f,validCount:17,missingCount:0,invalidCount:0})),issues:[],preprocessingVersion:'adapter-test-1',sourceChecksum:'fixture-data'}
export const model:Model={id:'model-1',version:'1',stationId:station.id,name:'接口联调模型（非真实推理）',isDemo:true,status:'ready',trainingTimezone:'Asia/Shanghai',featureMode:'phys2',scoreKind:'mahalanobis',cyclic:true,adaptive:true,cThr:7,quantile:.99,artifactChecksum:'fixture-model',requiredFields:fields.map(f=>f.field)}
export function makeTask(id='det-seed'):Task{return {id,name:'本站检测联调任务',status:'success',createdAt:'2026-11-08T09:00:00+08:00',startedAt:'2026-11-08T09:00:01+08:00',finishedAt:'2026-11-08T09:00:02+08:00',phase:'completed',progress:null,contextSnapshot:{enterprise:{id:'ent-1',name:'北方热力有限责任公司'},network:{id:'net-1',name:'城北主力供热网'},segment:{id:'seg-1',name:'1号二次供热管段'},station:{id:station.id,name:station.name,timezone:station.timezone}},datasetSnapshot:dataset,modelSnapshot:model,range:{start:dataset.start!,end:dataset.end!},warnings:[],error:null,retryOf:null}}
export function makePoints(normal=false):Point[]{return Array.from({length:17},(_,i)=>({timestamp:new Date(Date.parse(dataset.start!)+i*1800000).toISOString(),blockId:'block-1',score:normal||i<6?.4:2,threshold:1,alarm:!normal&&i>=6,criticality:normal?0:Math.max(0,i-5),health:normal||i<6?.6:0,confirmed:!normal&&i>=12}))}
export function makeEvents(id:string,normal=false):Event[]{return normal?[]:[{id:`event-${id}`,detectionId:id,stationId:station.id,blockId:'block-1',kind:'station_state_anomaly',title:'换热站运行状态偏离正常水平',start:'2026-11-08T06:00:00+08:00',end:dataset.end!,hours:2,peak_score:2,max_criticality:11,affectedMetrics:null,cause:null,solution:null,boundary:'touches_range_end'}]}
export async function mockLocal(page:BrowserPage,options:{normal?:boolean;diagnosis?:boolean;reports?:boolean}={}){
 const tasks=[makeTask()],datasets=[structuredClone(dataset)],diagnoses:Diagnosis[]=[],reports:Report[]=[],requests:Request[]=[],reads=new Map<string,number>();let sequence=0
 const state={offline:false,conflict:false,failExportFont:false,requests,tasks,datasets,diagnoses,reports}
 function result(t:Task){return {detectionId:t.id,contextSnapshot:t.contextSnapshot,datasetSnapshot:t.datasetSnapshot,modelSnapshot:t.modelSnapshot,range:t.range,computedAt:t.finishedAt??t.createdAt,preprocessingVersion:'adapter-test-1',summary:{pointCount:17,alarmPointCount:options.normal?0:11,confirmedPointCount:options.normal?0:5,eventCount:options.normal?0:1,blockCount:1,qualityIssueCount:0},warnings:[]}}
 await page.route('**/api/**',async route=>{const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api',''),method=request.method();requests.push(request)
  const send=(data:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify({requestId:'fixture-request',data})}),fail=(code:string,message:string,status=422)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify({requestId:'fixture-request',error:{code,message,retryable:false,details:[]}})})
  const list=(items:unknown[],size=Number(url.searchParams.get('pageSize')??20))=>{const p=Number(url.searchParams.get('page')??1);return send({items:items.slice((p-1)*size,p*size),page:p,pageSize:size,total:items.length})}
  if(state.offline)return route.abort('connectionrefused')
  if(path==='/runtime')return send({serviceVersion:'contract-fixture',contractVersion:'1.0',mode:'local',capabilities:{dataImport:true,anomalyDetection:true,causeDiagnosis:!!options.diagnosis,reportPersistence:!!options.reports,offlineDetection:true}})
  if(path==='/stations'){if(method==='POST')return send({...request.postDataJSON(),id:station.id},201);return list(url.searchParams.get('segmentId')==='seg-1'?[station]:[])}
  if(path==='/models')return list([model])
  if(path==='/datasets/import'){const d={...structuredClone(dataset),id:'dataset-imported',name:'导入后的联调数据'};datasets.unshift(d);return send(d,201)}
  if(path==='/datasets')return list(datasets)
  if(path.endsWith('/samples'))return list(makePoints().map(p=>({timestamp:p.timestamp,values:Object.fromEntries(fields.map(f=>[f.field,f.unit==='L/h'?186500:50])),quality:Object.fromEntries(fields.map(f=>[f.field,'valid']))})),5)
  if(path==='/detections'&&method==='GET')return list(tasks)
  if(path==='/detections'&&method==='POST'){const t={...makeTask(`det-${++sequence}`),name:request.postDataJSON().name,status:'queued' as const,phase:'queued',finishedAt:null};tasks.unshift(t);reads.set(t.id,0);return send(t,202)}
  if(path.startsWith('/detections/')){
   const [, ,id,action]=path.split('/'),t=tasks.find(t=>t.id===id);if(!t)return fail('NOT_FOUND','记录不存在',404)
   if(action==='retry'){const next={...makeTask(`det-${++sequence}`),retryOf:t.id};tasks.unshift(next);return send(next,202)}
   if(action==='result')return send(result(t))
   if(action==='points')return list(makePoints(options.normal),5)
   if(action==='events')return list(makeEvents(t.id,options.normal))
   if(reads.has(t.id)){const n=reads.get(t.id)!+1;reads.set(t.id,n);t.status=n<2?'queued':n<3?'running':'success';t.phase=n<3?'detecting':'completed'}return send(t)
  }
  if(path==='/diagnoses'&&method==='GET')return list(diagnoses)
  if(path==='/diagnoses'&&method==='POST'){const body=request.postDataJSON(),d:Diagnosis={id:`diagnosis-${++sequence}`,detectionId:body.detectionId,eventIds:body.eventIds,status:'success',phase:'completed',error:null,steps:[{title:'核对实际证据',summary:'接口测试证据摘要',state:'done',evidence:['来源任务一致']}],observations:['接口测试观测'],hypotheses:[{title:'待核查方向',evidence:'接口联调测试',confidence:null}],recommendations:[{title:'核查仪表',action:'现场比对',verification:'重新检测'}],limitations:['此内容为接口测试数据，不是真实诊断']};diagnoses.push(d);return send(d,202)}
  if(path.startsWith('/diagnoses/')){const d=diagnoses.find(d=>d.id===path.split('/')[2]);return d?send(d):fail('NOT_FOUND','诊断不存在',404)}
  if(path==='/reports'&&method==='GET')return list(reports)
  if(path==='/reports'&&method==='POST'){const body=request.postDataJSON(),t=tasks.find(t=>t.id===body.detectionId)!,r:Report={id:`report-${++sequence}`,title:'换热站运行状态异常检测报告',detectionId:t.id,diagnosisId:body.diagnosisId,eventIds:body.eventIds,version:1,revision:1,createdAt:new Date().toISOString(),archivedAt:null,note:'',snapshot:{task:structuredClone(t),result:result(t),events:makeEvents(t.id).filter(e=>body.eventIds.includes(e.id)),points:makePoints(),diagnosis:diagnoses.find(d=>d.id===body.diagnosisId)??null}};reports.push(r);return send(r,201)}
  if(path.startsWith('/reports/')){const [, ,id,action]=path.split('/'),r=reports.find(r=>r.id===id);if(!r)return fail('NOT_FOUND','报告不存在',404)
   if(action){const body=request.postDataJSON();if(state.conflict||body.expectedRevision!==r.revision)return fail('REVISION_CONFLICT','报告已被修改，请重新加载后核对备注。',409)
    if(action==='versions'){const next={...structuredClone(r),id:`report-${++sequence}`,version:r.version+1,revision:1,archivedAt:null};reports.push(next);return send(next,201)}
    if(r.archivedAt)return fail('REVISION_CONFLICT','归档版本不可修改',409)
    if(action==='note')r.note=body.note;if(action==='archive')r.archivedAt=new Date().toISOString();r.revision++
   }return send(r)
  }
  return fail('NOT_FOUND','接口未实现：'+path,404)
 });return state
}
