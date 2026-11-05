import type {Anomaly,Metric,Sample} from '../domain'

/** Quality failures are not heating anomalies and cannot contribute to diagnosis. */
export function sampleIssue(sample:Sample):string {
 if(sample.value===null||sample.value===undefined)return '数据缺失'
 if(typeof sample.value!=='number'||!Number.isFinite(sample.value))return '数值格式错误'
 if(!Number.isFinite(Date.parse(sample.time)))return '时间格式错误'
 if(!sample.unit)return '单位缺失'
 if(!/^(有效|正常|good|valid)/i.test(sample.quality))return '质量待核验'
 return ''
}
export function eventsInScope(events:Anomaly[],metrics:Metric[],start:string,end:string){
 const a=Date.parse(start),b=Date.parse(end)
 if(!Number.isFinite(a)||!Number.isFinite(b)||a>=b)return []
 return events.filter(e=>metrics.includes(e.metric)&&Date.parse(e.start)<=b&&Date.parse(e.end??end)>=a)
}
export function sampleState(sample:Sample,events:Anomaly[]){
 const issue=sampleIssue(sample)
 if(issue)return {kind:'quality' as const,label:issue}
 const t=Date.parse(sample.time)
 const event=events.find(e=>e.metric===sample.metric&&t>=Date.parse(e.start)&&(!e.end||t<=Date.parse(e.end)))
 return event?{kind:'anomaly' as const,label:'运行参数异常'}:{kind:'valid' as const,label:'有效采样'}
}
