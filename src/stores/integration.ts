import {defineStore} from 'pinia'
import {computed,ref} from 'vue'
import {errorText,localApi} from '../services/local/api'
import type {Mode,Runtime} from '../services/local/types'
export const useIntegration=defineStore('integration',()=>{
 const mode=ref<Mode>('demo'),runtime=ref<Runtime|null>(null),connection=ref<'idle'|'connecting'|'ready'|'error'>('idle'),error=ref(''),preferenceError=ref(''),revision=ref(0),updatedAt=ref('')
 try {if(localStorage.getItem('shad-service-mode')==='local')mode.value='local'}catch{preferenceError.value='运行模式无法保存，下次启动可能需要重新选择。'}
 let generation=0,controller:AbortController|undefined
 const local=computed(()=>mode.value==='local'),ready=computed(()=>local.value&&connection.value==='ready')
 async function connect(){
  const run=++generation;controller?.abort();controller=new AbortController();connection.value='connecting';error.value=''
  try {const value=await localApi.runtime(controller.signal);if(run!==generation)return
   if(value.contractVersion!=='1.0'||value.mode!=='local'||!value.capabilities)throw new Error('本机服务契约版本不兼容，需要接口约定 1.0。')
   runtime.value=value;connection.value='ready';updatedAt.value=new Date().toISOString();revision.value++
  }catch(e){if(run!==generation)return;runtime.value=null;connection.value='error';error.value=errorText(e)}
 }
 function setMode(value:Mode){if(value===mode.value)return;mode.value=value;try{localStorage.setItem('shad-service-mode',value);preferenceError.value=''}catch{preferenceError.value='运行模式无法保存，下次启动可能需要重新选择。'}
  if(value==='local')void connect();else{generation++;controller?.abort();runtime.value=null;connection.value='idle';error.value=''}
 }
 async function refresh(){if(connection.value==='connecting')return;await connect()}
 return {mode,local,ready,runtime,connection,error,preferenceError,revision,updatedAt,setMode,connect,refresh}
})
