export type Metric = 'supply' | 'return' | 'pressure' | 'flow'
export type TaskStatus = 'queued' | 'running' | 'success' | 'failed'
export interface Enterprise { id: string; name: string; code: string; active: boolean }
export interface Network { id: string; enterpriseId: string; name: string; code: string; active: boolean }
export interface Segment { id: string; networkId: string; name: string; code: string; diameter: number; length: number; kind: 'primary' | 'secondary'; metrics: Metric[]; active: boolean; hasData: boolean }
export interface Context { enterprise: Enterprise; network: Network; segment: Segment }
export interface Sample { time: string; metric: Metric; value: number; unit: string; quality: string; point: string }
export interface Anomaly { id: string; title: string; metric: Metric; start: string; end: string | null; value: number; baseline: number; level: string; evidence: string }
export interface Detection { id: string; name: string; context: Context; start: string; end: string; metrics: Metric[]; algorithm: string; threshold: number; status: TaskStatus; createdAt: string; readyAt: number; scenario: 'anomaly' | 'normal' | 'failure'; anomalies: Anomaly[]; error?: string; parentId?: string }
export interface DiagnosisStep { id: string; title: string; summary: string; evidence: string[]; chart?: 'timeseries' | 'correlation' | 'causes'; state: 'pending' | 'running' | 'done' | 'failed' }
export interface Analysis { id: string; detectionId: string; anomalyIds: string[]; context: Context; model: string; status: TaskStatus; createdAt: string; readyAt: number; scenario: 'success' | 'failure'; error?: string; parentId?: string; steps?: DiagnosisStep[]; causes?: Cause[] }
export interface Cause { title: string; weight: number; evidence: string; check: string; solution?: string; verification?: string }
export interface Report { id: string; title: string; detectionId: string; analysisId?: string; context: Context; version: number; createdAt: string; archivedAt?: string; note: string; detection: Detection; analysis?: Analysis; causes: Cause[]; process?: DiagnosisStep[] }
export interface Workspace { version: 3; enterprises: Enterprise[]; networks: Network[]; segments: Segment[]; selectedId: string; detections: Detection[]; analyses: Analysis[]; reports: Report[] }
export const metricInfo: Record<Metric, { label: string; unit: string; color: string; point: string }> = {
 supply: { label: '供水温度', unit: '℃', color: '#ff7849', point: 'TE-101A' },
 return: { label: '回水温度', unit: '℃', color: '#00b4d8', point: 'TE-102B' },
 pressure: { label: '回水压力', unit: 'MPa', color: '#a855f7', point: 'PT-201' },
 flow: { label: '循环流量', unit: 'm³/h', color: '#4ea8ff', point: 'FT-098' },
}
export const statusText: Record<TaskStatus, string> = { queued: '排队中', running: '运行中', success: '已完成', failed: '失败' }
