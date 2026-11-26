import {reactive} from 'vue'

/* 仅存于内存：导航切换保留，刷新页面重置 */
export const ctx=reactive({
  entId:'',
  netId:'',
  segmentId:'',
  segmentName:'',
  stationId:'',
})

export function setContext(p:{entId?:string;netId?:string;segmentId?:string;segmentName?:string;stationId?:string}){
  if(p.entId!==undefined)ctx.entId=p.entId
  if(p.netId!==undefined)ctx.netId=p.netId
  if(p.segmentId!==undefined)ctx.segmentId=p.segmentId
  if(p.segmentName!==undefined)ctx.segmentName=p.segmentName
  if(p.stationId!==undefined)ctx.stationId=p.stationId
}

;(window as any).__ctx=ctx
