import { describe, expect, it } from 'vitest'
import {
  DEMO_END_TIME,
  getTrendData,
  metricMeta,
  networkReadings,
  recentEvents,
  type MetricKey,
  type NetworkKey,
  type RangeKey,
} from './demo'

const networks: NetworkKey[] = ['primary', 'secondary']
const metrics: MetricKey[] = ['temperature', 'pressure', 'flow']
const ranges: RangeKey[] = [1, 6, 12, 24]

describe('fixed demonstration data', () => {
  it('keeps reference readings and physical units explicit', () => {
    expect(metrics.map((metric) => networkReadings.primary[metric].value)).toEqual([109.8, 1.62, 1520])
    expect(metrics.map((metric) => networkReadings.secondary[metric].value)).toEqual([65.2, 0.86, 1280])
    expect(metrics.map((metric) => metricMeta[metric].unit)).toEqual(['°C', 'MPa', 'm³/h'])
  })

  for (const network of networks) {
    for (const metric of metrics) {
      for (const hours of ranges) {
        it(`${network}/${metric}/${hours}h is deterministic, chronological and in actual units`, () => {
          const trend = getTrendData(network, metric, hours)
          expect(trend).toEqual(getTrendData(network, metric, hours))
          expect(trend.points).toHaveLength(13)
          expect(trend.points.at(-1)?.time).toBe(DEMO_END_TIME)
          const times = trend.points.map((point) => Date.parse(point.time))
          expect(times.at(-1)! - times[0]!).toBe(hours * 60 * 60 * 1000)
          expect(times.every((time, index) => index === 0 || time > times[index - 1]!)).toBe(true)
          expect(trend.points.every((point) => point.time.endsWith('+08:00'))).toBe(true)

          const [minimum, maximum] = metric === 'temperature'
            ? [50, 130]
            : metric === 'pressure' ? [0.5, 2.5] : [900, 2000]
          expect(trend.points.every(({ value }) => value >= minimum && value <= maximum)).toBe(true)

          if (network === 'primary' && metric === 'pressure') {
            expect(trend.anomalyIndex).toBe(12)
            expect(trend.anomalyEndIndex).toBe(12)
            expect(trend.points[trend.anomalyIndex]!.time).toBe(DEMO_END_TIME)
            expect(trend.points.at(-1)?.value).toBe(1.2)
            expect(trend.points[trend.anomalyIndex]!.value).toBeLessThan(trend.points[trend.anomalyIndex - 1]!.value)
          } else {
            expect(trend.anomalyIndex).toBe(-1)
            expect(trend.anomalyEndIndex).toBe(-1)
          }
        })
      }
    }
  }

  it('changes both the covered time and the curve when the selected range changes', () => {
    const oneHour = getTrendData('primary', 'temperature', 1)
    const twentyFourHours = getTrendData('primary', 'temperature', 24)
    expect(oneHour.points[0]!.time).not.toBe(twentyFourHours.points[0]!.time)
    expect(oneHour.points.map(({ value }) => value)).not.toEqual(twentyFourHours.points.map(({ value }) => value))
  })

  it('has five distinguishable events and one pending diagnosis', () => {
    expect(recentEvents).toHaveLength(5)
    expect(new Set(recentEvents.map(({ id }) => id)).size).toBe(5)
    expect(recentEvents.filter(({ status }) => status === 'pending')).toHaveLength(1)
    expect(recentEvents[0]).toMatchObject({
      time: '10:35', type: '一次网压力异常下降', status: 'pending', statusLabel: '待诊断',
    })
    expect(recentEvents.every(({ parameter, statusLabel }) => parameter.length > 0 && statusLabel.length > 0)).toBe(true)
  })
})
