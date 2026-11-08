import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {useWorkspace} from '../stores/workspace'
import {useIntegration} from '../stores/integration'
import {allPages,errorText,localApi} from '../services/local/api'
import type {Dataset,Model,Station} from '../services/local/types'
export function useStationData(){
 const workspace=useWorkspace(),service=useIntegration(),stations=ref<Station[]>([]),datasets=ref<Dataset[]>([]),models=ref<Model[]>([]),stationId=ref(''),loading=ref(false),loadingData=ref(false),error=ref('')
 const station=computed(()=>stations.value.find(s=>s.id===stationId.value));let stationController:AbortController|undefined,dataController:AbortController|undefined,loadedSegment='',loadedStation=''
 async function load(){
  stationController?.abort();dataController?.abort();stationController=new AbortController();const control=stationController
  error.value=''
  if(!service.ready||!workspace.context){loading.value=false;loadingData.value=false;return}
  if(loadedSegment!==workspace.context.segment.id){loadedSegment=workspace.context.segment.id;stationId.value='';stations.value=[];datasets.value=[];models.value=[];loadedStation=''}
  loading.value=true
  try{const rows=await allPages(p=>localApi.stations(workspace.context!.segment.id,p,control.signal));if(control.signal.aborted)return;stations.value=rows
   const selected=rows.some(s=>s.id===stationId.value)?stationId.value:rows.length===1?rows[0]!.id:''
   if(selected===stationId.value)await loadData();else stationId.value=selected
  }catch(e){if(!control.signal.aborted)error.value=errorText(e)}finally{if(!control.signal.aborted)loading.value=false}
 }
 async function loadData(){dataController?.abort();dataController=new AbortController();const control=dataController;error.value=''
  if(loadedStation!==stationId.value){loadedStation=stationId.value;datasets.value=[];models.value=[]}
  if(!service.ready||!stationId.value){loadingData.value=false;return}loadingData.value=true
  try{const [d,m]=await Promise.all([allPages(p=>localApi.datasets(stationId.value,p,control.signal)),allPages(p=>localApi.models(stationId.value,p,control.signal))]);if(control.signal.aborted)return;datasets.value=d;models.value=m}
  catch(e){if(!control.signal.aborted)error.value=errorText(e)}finally{if(!control.signal.aborted)loadingData.value=false}
 }
 watch([()=>workspace.context?.segment.id,()=>service.ready,()=>service.revision],load,{immediate:true});watch(stationId,loadData)
 onBeforeUnmount(()=>{stationController?.abort();dataController?.abort()})
 return {stations,stationId,station,datasets,models,loading,loadingData,error,reload:load,reloadData:loadData}
}
