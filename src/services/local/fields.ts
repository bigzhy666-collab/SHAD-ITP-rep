export const fields=[
 {field:'outdoor_temperature',label:'室外温度',unit:'degC'},
 {field:'p_net_supply_temperature',label:'一次侧供水温度',unit:'degC'},
 {field:'p_net_return_temperature',label:'一次侧回水温度',unit:'degC'},
 {field:'p_net_meter_heat_power',label:'瞬时热功率',unit:'kW'},
 {field:'p_net_meter_flow',label:'一次侧瞬时流量',unit:'L/h'},
 {field:'p_hc1_return_temperature',label:'二次侧采暖回水温度',unit:'degC'},
 {field:'s_hc1_supply_temperature',label:'二次侧采暖供水温度',unit:'degC'},
 {field:'s_hc1_supply_temperature_setpoint',label:'二次侧供水温度设定值',unit:'degC'},
] as const
export const unitLabel=(unit:string)=>({degC:'℃','m3/h':'m³/h'}[unit]??unit)
export function parseCsv(text:string,delimiter=','):string[][] {
 const rows:string[][]=[],row:string[]=[];let cell='',quoted=false
 text=text.replace(/^\uFEFF/,'')
 for(let i=0;i<text.length;i++) {
  const c=text[i]
  if(c==='"') {if(quoted&&text[i+1]==='"'){cell+='"';i++}else if(quoted||cell==='')quoted=!quoted;else throw new Error('CSV 引号位置无效，请检查文件。')}
  else if(!quoted&&(c===delimiter||c==='\n'||c==='\r')) {row.push(cell);cell='';if(c!==delimiter){if(c==='\r'&&text[i+1]==='\n')i++;if(row.some(v=>v.trim()))rows.push([...row]);row.length=0}}
  else cell+=c
 }
 if(quoted)throw new Error('CSV 引号未闭合，请检查文件。')
 row.push(cell);if(row.some(v=>v.trim()))rows.push([...row])
 if(rows.length<2)throw new Error('CSV 至少需要表头和一行数据。')
 if(new Set(rows[0]).size!==rows[0]!.length||rows[0]!.some(v=>!v.trim()))throw new Error('CSV 表头为空或重名，请先修正。')
 if(rows.some(r=>r.length!==rows[0]!.length))throw new Error('CSV 各行列数不一致，请确认分隔符和引号。')
 return rows
}
export function zoned(value:string) {return value?`${value}:00+08:00`:''}
export function localTime(value:string|null) {if(!value)return '';return new Date(Date.parse(value)+8*3600000).toISOString().slice(0,16)}
export function validRange(start:string,end:string) {return Number.isFinite(Date.parse(start))&&Number.isFinite(Date.parse(end))&&Date.parse(start)<Date.parse(end)}
export const taskLabel={queued:'排队中',running:'运行中',success:'已完成',failed:'失败'}
export function eventIdsFromQuery(value:unknown):string[]{
 if(Array.isArray(value))return value.filter((v):v is string=>typeof v==='string')
 if(typeof value!=='string'||!value)return []
 if(value.startsWith('[')){try{const ids=JSON.parse(value);return Array.isArray(ids)?ids.filter((v):v is string=>typeof v==='string'):[]}catch{return []}}
 return value.split(',').filter(Boolean)
}
export const phaseLabel:Record<string,string>={queued:'等待执行',validating:'校验数据',detecting:'模型检测',saving:'保存结果',completed:'检测完成',failed:'执行失败'}
