import type { Analysis, Detection, DiagnosisStep } from '../domain'
import { metricInfo } from '../domain'

/** Public evidence summaries, never a model's private chain of thought. */
export function diagnosisSteps(d: Detection, ids: string[]): DiagnosisStep[] {
 const events = d.anomalies.filter(a => ids.includes(a.id))
 const paired = d.metrics.includes('return') && d.metrics.includes('flow')
 return [
  { id:'events', title:'核对异常事件', summary:`锁定 ${events.length} 项数值异常，保留观测值、基准和来源。`, evidence:events.map(a=>`${a.title}：${a.value} ${metricInfo[a.metric].unit}，基准 ${a.baseline} ${metricInfo[a.metric].unit}；${a.evidence}`), state:'pending' },
  { id:'evidence', title:'对齐时序证据', summary:'将异常区间与同一管段的运行参数对齐，检查数据边界。', evidence:[`来源检测：${d.id}`,`参数：${d.metrics.map(m=>metricInfo[m].label).join('、')}`,'数值偏差只能说明观测异常，尚未确定设备故障原因。'], chart:'timeseries', state:'pending' },
  { id:'correlation', title:'检查参数关联', summary:paired?'对比回水温度与流量的演示关联图，保留关联局限。':'关联参数不足，仅展示可用参数，不补造缺失数据。', evidence:[paired?'散点是演示关联示意，未执行真实统计或模型推理。':'缺少回水温度或流量，不能形成温度—流量关联结论。','参数相关不代表已证明因果，需结合现场仪表和设备状态核验。'], chart:paired?'correlation':'timeseries', state:'pending' },
  { id:'causes', title:'研判可能原因', summary:'结合选定事件与证据形成候选原因，区分事实与推测。', evidence:['候选原因和权重由演示规则生成，不是已确认故障或真实模型置信度。','仅使用本次选定事件，未选事件不作为本次诊断结论。'], chart:'causes', state:'pending' },
  { id:'solutions', title:'形成解决建议', summary:'将原因、核查方法、解决建议和复核标准整理为诊断报告。', evidence:['建议由技术人员确认后按现场规程执行，不自动控制设备。','生成后保留过程摘要及来源快照，可保存备注、归档或导出 Word / PDF。'], chart:'causes', state:'pending' },
 ]
}

export function restoredSteps(a: Analysis, d: Detection): DiagnosisStep[] {
 if (a.steps?.length) return a.steps
 return diagnosisSteps(d,a.anomalyIds).map((step,i)=>({...step,state:a.status==='success'?'done':a.status==='failed'?(i<3?'done':i===3?'failed':'pending'):'pending'}))
}
