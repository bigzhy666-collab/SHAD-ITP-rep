export function time(value?:string){return value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—'}
export function download(blob:Blob,name:string){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000)}
export function csv(rows:(string|number)[][],name:string){download(new Blob(['\uFEFF'+rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),name)}
