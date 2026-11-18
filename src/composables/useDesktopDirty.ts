import {onBeforeUnmount,watch} from 'vue'

declare global {
  interface Window {shadDesktop?: {setDirty:(id:string,dirty:boolean)=>void}}
}
let sequence=0
/** Notify the desktop close guard without exposing file or process operations. */
export function useDesktopDirty(getDirty:()=>boolean){
  const id='report-'+(++sequence)
  watch(getDirty,dirty=>window.shadDesktop?.setDirty(id,dirty),{immediate:true,flush:'sync'})
  onBeforeUnmount(()=>window.shadDesktop?.setDirty(id,false))
}
