import type {Dataset,Diagnosis,DetectionInput,Event,Manifest,Model,Page,Point,Report,Result,Runtime,Sample,Station,Task,Failure} from './types'
import {assertReportSource} from './report'

export class ApiError extends Error {
 constructor(public code:string,message:string,public retryable=false,public requestId='',public details:Failure['details']=[]) { super(message); this.name='ApiError' }
}
export function errorText(error:unknown) { return error instanceof ApiError ? `${error.message}${error.requestId?`（错误编号：${error.requestId}）`:''}` : error instanceof Error?error.message:'操作失败，请重试。' }
type Options = Omit<RequestInit,'body'> & {body?:unknown;timeout?:number}
export async function request<T>(path:string, options:Options={}):Promise<T> {
 const {body,timeout=15000,signal,...rest}=options, controller=new AbortController()
 const abort=()=>controller.abort(); signal?.addEventListener('abort',abort,{once:true}); if(signal?.aborted)controller.abort()
 let expired=false
 const timer=setTimeout(()=>{expired=true;controller.abort()},timeout)
 try {
  const form=body instanceof FormData, headers=new Headers(rest.headers)
  if(body!==undefined&&!form)headers.set('Content-Type','application/json')
  const response=await fetch(`/api${path}`,{...rest,headers,body:body===undefined?undefined:form?body:JSON.stringify(body),signal:controller.signal})
  const text=await response.text(); let envelope:any
  try { envelope=JSON.parse(text) } catch { throw new ApiError('INVALID_RESPONSE','本机接口未返回有效 JSON，请确认后端已启动且 /api 代理配置正确。') }
  if(!response.ok)throw new ApiError(envelope.error?.code??`HTTP_${response.status}`,envelope.error?.message??'本机服务请求失败。',envelope.error?.retryable??false,envelope.requestId??'',envelope.error?.details??[])
  if(!envelope||!Object.hasOwn(envelope,'data'))throw new ApiError('INVALID_RESPONSE','本机接口响应缺少 data 字段。')
  return envelope.data as T
 } catch(error) {
  if(error instanceof ApiError)throw error
  if(signal?.aborted)throw new DOMException('请求已取消','AbortError')
  throw new ApiError(expired?'TIMEOUT':'CONNECTION_ERROR',expired?'本机服务响应超时。请先查询任务状态，避免重复提交。':'本机服务未启动或连接中断，请启动服务后重新连接。',true)
 } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort)}
}
export function query(values:Record<string,string|number|undefined>) { const params=new URLSearchParams();for(const [key,value]of Object.entries(values))if(value!==undefined&&value!=='')params.set(key,String(value));return params.size?`?${params}`:'' }
export async function allPages<T>(load:(page:number)=>Promise<Page<T>>):Promise<T[]> {
 const items:T[]=[];let total:number|undefined
 for(let page=1;page<=10000;page++) {
  const result=await load(page)
  if(!Array.isArray(result.items)||result.page!==page||!Number.isInteger(result.total)||result.total<0||result.pageSize<=0)throw new ApiError('INVALID_RESPONSE','分页结果格式错误，已停止读取。')
  if(total!==undefined&&total!==result.total)throw new ApiError('RESULT_CHANGED','读取期间记录数量变化，请重新读取。')
  total=result.total;items.push(...result.items)
  if(items.length===total)return items
  if(!result.items.length||items.length>total)throw new ApiError('INCOMPLETE_RESULT','结果分页不完整，已停止读取，未导出部分数据。')
 }
 throw new ApiError('RESULT_TOO_LARGE','结果分页过多，请缩小时间范围。')
}
const id=(value:string)=>encodeURIComponent(value)
const list=<T>(path:string,values:Record<string,string|number|undefined>,signal?:AbortSignal)=>request<Page<T>>(path+query(values),{signal})
export const localApi={
 runtime:(signal?:AbortSignal)=>request<Runtime>('/runtime',{signal}),
 stations:(segmentId:string,page=1,signal?:AbortSignal)=>list<Station>('/stations',{segmentId,page,pageSize:500},signal),
 createStation:(body:Omit<Station,'id'>)=>request<Station>('/stations',{method:'POST',body}),
 models:(stationId:string,page=1,signal?:AbortSignal)=>list<Model>('/models',{stationId,page,pageSize:500},signal),
 datasets:(stationId:string,page=1,signal?:AbortSignal)=>list<Dataset>('/datasets',{stationId,page,pageSize:500},signal),
 importDataset:(file:File,manifest:Manifest)=>{const body=new FormData();body.append('file',file);body.append('manifest',JSON.stringify(manifest));return request<Dataset>('/datasets/import',{method:'POST',body,timeout:120000})},
 samples:(datasetId:string,start:string,end:string,fields:string[],page=1,signal?:AbortSignal)=>list<Sample>(`/datasets/${id(datasetId)}/samples`,{start,end,fields:fields.join(','),page,pageSize:500},signal),
 detections:(segmentId:string,page=1,signal?:AbortSignal)=>list<Task>('/detections',{segmentId,page,pageSize:500},signal),
 createDetection:(body:DetectionInput,key:string)=>request<Task>('/detections',{method:'POST',body,headers:{'Idempotency-Key':key}}),
 task:(taskId:string,signal?:AbortSignal)=>request<Task>(`/detections/${id(taskId)}`,{signal}),
 retry:(taskId:string,key:string)=>request<Task>(`/detections/${id(taskId)}/retry`,{method:'POST',body:{},headers:{'Idempotency-Key':key}}),
 result:(taskId:string,signal?:AbortSignal)=>request<Result>(`/detections/${id(taskId)}/result`,{signal}),
 points:(taskId:string,page=1,signal?:AbortSignal)=>list<Point>(`/detections/${id(taskId)}/points`,{page,pageSize:500},signal),
 events:(taskId:string,page=1,signal?:AbortSignal)=>list<Event>(`/detections/${id(taskId)}/events`,{page,pageSize:500},signal),
 createDiagnosis:(detectionId:string,eventIds:string[],key:string)=>request<Diagnosis>('/diagnoses',{method:'POST',body:{detectionId,eventIds},headers:{'Idempotency-Key':key}}),
 diagnosis:(diagnosisId:string,signal?:AbortSignal)=>request<Diagnosis>(`/diagnoses/${id(diagnosisId)}`,{signal}),
 diagnoses:(page=1,signal?:AbortSignal)=>list<Diagnosis>('/diagnoses',{page,pageSize:500},signal),
 createReport:(detectionId:string,eventIds:string[],diagnosisId:string|null,key:string)=>request<Report>('/reports',{method:'POST',body:{detectionId,eventIds,diagnosisId},headers:{'Idempotency-Key':key}}).then(assertReportSource),
 reports:(page=1,signal?:AbortSignal)=>list<Report>('/reports',{page,pageSize:500},signal),
 report:(reportId:string)=>request<Report>(`/reports/${id(reportId)}`).then(assertReportSource),
 note:(reportId:string,note:string,expectedRevision:number)=>request<Report>(`/reports/${id(reportId)}/note`,{method:'PATCH',body:{note,expectedRevision}}).then(assertReportSource),
 archive:(reportId:string,expectedRevision:number)=>request<Report>(`/reports/${id(reportId)}/archive`,{method:'POST',body:{expectedRevision}}).then(assertReportSource),
 version:(reportId:string,expectedRevision:number)=>request<Report>(`/reports/${id(reportId)}/versions`,{method:'POST',body:{expectedRevision}}).then(assertReportSource),
}
