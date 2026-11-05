export type NetworkKey = 'primary' | 'secondary'
export type MetricKey = 'temperature' | 'pressure' | 'flow'
export type RangeKey = 1 | 6 | 12 | 24

export interface MetricMeta {
  label: string
  unit: string
  color: string
  decimals: number
}

export const metricMeta: Record<MetricKey, MetricMeta> = {
  temperature: { label: '温度', unit: '°C', color: '#F5C76C', decimals: 1 },
  pressure: { label: '压力', unit: 'MPa', color: '#B494FF', decimals: 2 },
  flow: { label: '流量', unit: 'm³/h', color: '#53DDC2', decimals: 0 },
}

export const networkMeta: Record<NetworkKey, {
  label: string
  shortLabel: string
  description: string
  pointCount: number
}> = {
  primary: { label: '一次网', shortLabel: '主网', description: '热源厂 → 换热站', pointCount: 12 },
  secondary: { label: '二次网', shortLabel: '次网', description: '换热站 → 居民区', pointCount: 36 },
}

export interface NetworkReading {
  value: number
  range: [number, number]
  delta: number
}

// These fixed cards show the reference operating values; the pressure scenario
// in the trend below demonstrates the subsequent drop from 1.62 to 1.20 MPa.
export const networkReadings: Record<NetworkKey, Record<MetricKey, NetworkReading>> = {
  primary: {
    temperature: { value: 109.8, range: [100, 150], delta: 0.2 },
    pressure: { value: 1.62, range: [1.6, 2.5], delta: -0.01 },
    flow: { value: 1520, range: [1000, 2000], delta: 12 },
  },
  secondary: {
    temperature: { value: 65.2, range: [60, 70], delta: -1.3 },
    pressure: { value: 0.86, range: [0.6, 1], delta: 0.02 },
    flow: { value: 1280, range: [900, 1600], delta: -24 },
  },
}

export const DEMO_END_TIME = '2026-11-02T10:35:00+08:00'
const endTimestamp = Date.parse(DEMO_END_TIME)
const wave = [0, 0.35, 0.7, 0.28, -0.25, 0.2, 0.62, 0.12, -0.42, -0.15, 0.32, 0.5, 0]
const amplitude: Record<NetworkKey, Record<MetricKey, number>> = {
  primary: { temperature: 2.8, pressure: 0.04, flow: 48 },
  secondary: { temperature: 1.4, pressure: 0.025, flow: 34 },
}

export interface TrendPoint {
  /** ISO timestamp with an explicit Beijing offset; independent of browser timezone. */
  time: string
  value: number
}

export interface TrendData {
  points: TrendPoint[]
  anomalyIndex: number
  anomalyEndIndex: number
}

function toBeijingIso(timestamp: number): string {
  return `${new Date(timestamp + 8 * 60 * 60 * 1000).toISOString().slice(0, 19)}+08:00`
}

/** A repeatable snapshot, not a live data feed or an anomaly-detection algorithm. */
export function getTrendData(network: NetworkKey, metric: MetricKey, hours: RangeKey): TrendData {
  const base = networkReadings[network][metric].value
  const decimals = metricMeta[metric].decimals
  const rangeScale = 1 + Math.log2(hours) * 0.12
  const hasAnomaly = network === 'primary' && metric === 'pressure'
  const points = wave.map((offset, index): TrendPoint => {
    const timestamp = endTimestamp - (12 - index) * hours * 60 * 60 * 1000 / 12
    let value = base + offset * amplitude[network][metric] * rangeScale

    if (hasAnomaly && index === 12) {
      value = 1.2
    }

    return { time: toBeijingIso(timestamp), value: Number(value.toFixed(decimals)) }
  })

  return {
    points,
    anomalyIndex: hasAnomaly ? 12 : -1,
    anomalyEndIndex: hasAnomaly ? 12 : -1,
  }
}

export type EventStatus = 'pending' | 'diagnosed' | 'resolved'

export interface DemoEvent {
  id: string
  time: string
  network: NetworkKey
  type: string
  parameter: string
  status: EventStatus
  statusLabel: string
}

export const recentEvents: DemoEvent[] = [
  { id: 'DEMO-001', time: '10:35', network: 'primary', type: '一次网压力异常下降', parameter: '1.62 → 1.20 MPa', status: 'pending', statusLabel: '待诊断' },
  { id: 'DEMO-002', time: '10:12', network: 'primary', type: '一次网温度偏高', parameter: '112.4 °C', status: 'diagnosed', statusLabel: '已诊断' },
  { id: 'DEMO-003', time: '09:48', network: 'secondary', type: '二次网温度波动', parameter: '62.1 → 59.3 °C', status: 'diagnosed', statusLabel: '已诊断' },
  { id: 'DEMO-004', time: '09:20', network: 'primary', type: '一次网流量异常升高', parameter: '1520 → 1680 m³/h', status: 'resolved', statusLabel: '已处理' },
  { id: 'DEMO-005', time: '08:52', network: 'secondary', type: '补水流量偏低', parameter: '0.60 → 0.42 m³/h', status: 'resolved', statusLabel: '已处理' },
]
