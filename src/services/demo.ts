import type { Analysis, Anomaly, Context, Detection, Metric, Sample, Workspace } from '../domain'
import { metricInfo } from '../domain'

export const causes = [
 { title: '次干支路电动调节阀开度异常扰动', weight: 87.4, evidence: '回水温度下降与支路流量增加同时出现，压力伴随轻度波动。示例特征与阀门扰动相似，尚需现场核验。', check: '核对 3 号换热站调节阀反馈开度、现场读数与执行机构状态。', solution: '现场确认反馈偏差后，由授权人员检查执行机构、传动连接与反馈信号，按设备规程校准或检修；记录处置前后的开度与运行参数。', verification: '复测阀门指令与反馈一致性，观察同等工况下回水温度、压力和流量是否恢复稳定。' },
 { title: '用户端旁通阀轻度内漏窜水', weight: 62.1, evidence: '供回水温差收缩与流量偏高存在关联。相关性是演示依据，不代表已证明因果。', check: '检查末端旁通及止回阀，结合现场测温确认有无窜水。', solution: '确认旁通或止回阀内漏后，按现场隔离和检修规程处理密封部件或阀门，恢复后记录阀位与测温结果。', verification: '对比检修前后的供回温差与支路流量，确认窜水现象消失且末端供热正常。' },
 { title: '换热器机组排污截断阀异常开启', weight: 18.2, evidence: '示例压力短周期变化可作为排查方向，当前数据不足以确认。', check: '核对排污阀状态及历史操作记录，不执行远程控制。', solution: '核实排污操作是否符合当前工况，确认异常开启或密封问题后，按运维规程恢复阀位或安排检修。', verification: '复核压力及补水变化，确认阀位记录与现场状态一致。' },
]
export function causesFor(detection: Detection, ids: string[]) {
 const selected = detection.anomalies.filter(a => ids.includes(a.id))
 if (!selected.length) return []
 if (selected.some(a => a.metric === 'return') && detection.metrics.includes('flow')) return causes.filter((_,i)=>i<2||selected.some(a=>a.metric==='pressure')).map(c=>({...c,evidence:selected.some(a=>a.metric==='pressure')?c.evidence:c.evidence.replace('，压力伴随轻度波动','')}))
 return [{ title: '测点变化或局部水力扰动', weight: 68.2, evidence: `所选异常涉及${selected.map(a => metricInfo[a.metric].label).join('、')}。当前仅依据已选参数给出单参数演示推测，无法验证温度与流量关联。`, check: '核对现场仪表与采集记录，补充相关温度、压力及流量数据后复核。', solution: '先比对现场仪表与采集值；确认测点故障时校验仪表或修复采集链路。若测点正常，补齐关联参数后重新诊断，再确定设备处理方案。', verification: '确认采集与现场读数一致，补充参数后复测异常是否仍然出现。' }]
}
export function anomaliesFor(metrics: Metric[], primary = false): Anomaly[] {
 return [
  { id: 'AN-01', title: '回水温度骤降异常', metric: 'return' as Metric, start: '2026-11-03T03:24:12', end: '2026-11-03T03:48:00', value: 33.2, baseline: 42, level: '显著偏差', evidence: '温度突变斜率超过示例检测条件，残差 -8.80℃。' },
  { id: 'AN-02', title: '回水压力微幅脉冲', metric: 'pressure' as Metric, start: '2026-11-03T06:15:30', end: null, value: .58, baseline: .5, level: '轻度波动', evidence: '压力振荡幅度 +0.08 MPa，超过配置中的示例门限。' },
 ].filter(a => metrics.includes(a.metric)).map(a => primary ? {...a, baseline:a.metric==='return'?72:1.62,value:a.metric==='return'?63.2:1.7} : a)
}
export function seedWorkspace(): Workspace {
 const enterprises = [{ id: 'ent-1', name: '北方热力有限责任公司', code: 'ENT-001', active: true }, { id: 'ent-2', name: '城东热力分公司', code: 'ENT-002', active: true }]
 const networks = [{ id: 'net-1', enterpriseId: 'ent-1', name: '城北主力供热网', code: 'NET-01', active: true }, { id: 'net-2', enterpriseId: 'ent-1', name: '城西供热网', code: 'NET-02', active: true }, { id: 'net-3', enterpriseId: 'ent-2', name: '高新片区热网', code: 'NET-03', active: true }]
 const segments = [
  { id: 'seg-1', networkId: 'net-1', name: '1号二次供热管段', code: 'ST-P01', diameter: 300, length: 840, kind: 'secondary' as const, metrics: ['supply', 'return', 'pressure', 'flow'] as Metric[], active: true, hasData: true },
  { id: 'seg-2', networkId: 'net-1', name: '2号一次供热管段', code: 'ST-P02', diameter: 500, length: 1260, kind: 'primary' as const, metrics: ['supply', 'return', 'pressure', 'flow'] as Metric[], active: true, hasData: true },
  { id: 'seg-3', networkId: 'net-1', name: '3号末端支路', code: 'ST-P03', diameter: 150, length: 360, kind: 'secondary' as const, metrics: [] as Metric[], active: true, hasData: false },
  { id: 'seg-4', networkId: 'net-2', name: '西区供热支线', code: 'ST-W01', diameter: 250, length: 600, kind: 'secondary' as const, metrics: ['supply', 'return'] as Metric[], active: true, hasData: false },
  { id: 'seg-5', networkId: 'net-3', name: '高新供热管段', code: 'ST-E01', diameter: 300, length: 900, kind: 'secondary' as const, metrics: ['supply', 'return', 'pressure'] as Metric[], active: true, hasData: true },
 ]
 const context = { enterprise: enterprises[0]!, network: networks[0]!, segment: segments[0]! }
 const detection: Detection = { id: 'DET-20261103-089', name: '城北管段时序残差检测', context, start: '2026-11-03T00:00', end: '2026-11-03T08:00', metrics: [...context.segment.metrics], algorithm: '时序残差聚类 V2.3（演示）', threshold: 3.4, createdAt: '2026-11-03T08:00:00', readyAt: 0, status: 'success', scenario: 'anomaly', anomalies: anomaliesFor(context.segment.metrics) }
 const analysis: Analysis = { id: 'AI-20261103-042', detectionId: detection.id, anomalyIds: detection.anomalies.map(a => a.id), context, model: 'ThermalNet-Mini v1.8（演示）', status: 'success', createdAt: '2026-11-03T08:10:00', readyAt: 0, scenario: 'success' }
 return { version: 3, enterprises, networks, segments, selectedId: 'seg-1', detections: [detection], analyses: [analysis], reports: [{ id: 'REP-20261103-018', title: '热力管网异常辅助诊断报告', detectionId: detection.id, analysisId: analysis.id, context, version: 1, createdAt: '2026-11-03T08:45:18', note: '', detection: structuredClone(detection), analysis: structuredClone(analysis), causes: structuredClone(causes) }] }
}
export function samplesFor(context: Context, start = '2026-11-03T00:00', end = '2026-11-03T08:00'): Sample[] {
 if (!context.segment.hasData) return []
 const a = new Date(start).getTime(), b = new Date(end).getTime()
 if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return []
 const origin = new Date('2026-11-03T00:00').getTime()
 if (a < origin || b > origin + 86400000) return []
 const count = Math.max(2, Math.ceil((b - a) / 120000))
 return Array.from({ length: count + 1 }, (_, i) => context.segment.metrics.map(metric => {
  const stamp = a + (b - a) * i / count, p = (stamp - origin) / 28800000, primary = context.segment.kind === 'primary'
  const base = metric === 'supply' ? (primary ? 109.8 : 68.4) : metric === 'return' ? (primary ? 72 : 42) : metric === 'pressure' ? (primary ? 1.62 : .5) : (primary ? 1520 : 186.5)
  const scale = metric === 'pressure' ? .008 : metric === 'flow' ? 2.8 : .55
  let value = base + Math.sin(p * 26) * scale
  if (p > .425 && p < .475 && metric === 'return') value -= 8.8 * Math.sin((p - .425) / .05 * Math.PI)
  if (p > .78 && metric === 'pressure') value += .08 * Math.abs(Math.sin(p * 100))
  return { time: new Date(stamp).toISOString(), metric, value: Number(value.toFixed(metric === 'pressure' ? 3 : 2)), unit: metricInfo[metric].unit, quality: '有效（演示）', point: metricInfo[metric].point }
 })).flat()
}
export function validateDetection(context: Context | null, start: string, end: string, metrics: Metric[], threshold: number): string {
 if (!context) return '请先选择企业、供热管网和管段。'
 if (!context.enterprise.active || !context.network.active || !context.segment.active) return '当前对象已停用，请选择有效管段。'
 if (!context.segment.hasData) return '当前管段暂无运行数据，请切换管段。'
 const a = new Date(start).getTime(), b = new Date(end).getTime()
 if (!Number.isFinite(a) || !Number.isFinite(b) || a >= b) return '起始时间必须早于结束时间。'
 if (b - a > 7 * 86400000) return '演示检测最大支持 7 天，请缩小范围。'
 if (a < new Date('2026-11-03T00:00').getTime() || b > new Date('2026-11-04T00:00').getTime()) return '演示数据可用范围为 2026-11-03 00:00 至 2026-11-04 00:00。'
 if (!metrics.length) return '至少选择一项监测参数。'
 if (metrics.some(m => !context.segment.metrics.includes(m))) return '所选参数不属于当前管段。'
 if (!(threshold > 0 && threshold <= 10)) return '残差系数须大于 0 且不超过 10。'
 return ''
}
