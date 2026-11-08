import {onBeforeUnmount,ref,watch,type Ref} from 'vue'
import {useIntegration} from '../stores/integration'
import {allPages,ApiError,errorText,localApi} from '../services/local/api'
import type {Event,Point,Result,Task} from '../services/local/types'
export function useDetection(id:Ref<string>){
 const service=useIntegration(),task=ref<Task>(),result=ref<Result>(),points=ref<Point[]>([]),events=ref<Event[]>([]),error=ref(''),loading=ref(false)
 let controller:AbortController|undefined,timer:ReturnType<typeof setTimeout>|undefined,loaded='',generation=0
 async function begin(){const run=++generation;clearTimeout(timer);controller?.abort();controller=new AbortController();const control=controller
  if(task.value?.id!==id.value){task.value=undefined;result.value=undefined;points.value=[];events.value=[];loaded=''}error.value=''
  if(!id.value||!service.ready){loading.value=false;return}loading.value=true
  async function read(){let failed=false,retryable=true
   try{const current=await localApi.task(id.value,control.signal);if(run!==generation)return;if(current.id!==id.value)throw new ApiError('SOURCE_MISMATCH','服务返回的任务来源不一致。');task.value=current
    if(current.status==='success'&&loaded!==current.id){const [r,p,e]=await Promise.all([localApi.result(current.id,control.signal),allPages(n=>localApi.points(current.id,n,control.signal)),allPages(n=>localApi.events(current.id,n,control.signal))]);if(run!==generation)return
     if(r.detectionId!==current.id||e.some(event=>event.detectionId!==current.id||event.stationId!==current.contextSnapshot.station.id))throw new ApiError('SOURCE_MISMATCH','检测结果来源不一致，已停止展示。')
     if(p.some(point=>!Number.isFinite(point.score)||!Number.isFinite(point.threshold)||!Number.isFinite(Date.parse(point.timestamp))))throw new ApiError('MODEL_OUTPUT_INVALID','模型返回无效分数或时间，已停止展示。')
     result.value=r;points.value=p;events.value=e;loaded=current.id
    }error.value=''
   }catch(e){if(run!==generation||control.signal.aborted)return;error.value=errorText(e);failed=true;retryable=e instanceof ApiError&&e.retryable}
   finally{if(run===generation&&!control.signal.aborted){loading.value=false;if(failed?retryable:task.value?.status==='queued'||task.value?.status==='running')timer=setTimeout(read,failed?8000:document.hidden?5000:1000)}}
  }await read()
 }
 watch([id,()=>service.ready,()=>service.revision],begin,{immediate:true});onBeforeUnmount(()=>{generation++;controller?.abort();clearTimeout(timer)})
 return {task,result,points,events,error,loading,reload:begin}
}
