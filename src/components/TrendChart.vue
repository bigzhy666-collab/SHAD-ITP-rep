<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { init, use } from 'echarts/core'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkPointComponent, AriaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useDashboardStore } from '../stores/dashboard'
import { getTrendData, metricMeta, networkMeta } from '../data/demo'

use([LineChart, GridComponent, TooltipComponent, MarkPointComponent, AriaComponent, CanvasRenderer])
const store = useDashboardStore()
const { network, metric, range } = storeToRefs(store)
const element = ref<HTMLDivElement>()
let chart: EChartsType | undefined
let observer: ResizeObserver | undefined
const data = computed(() => getTrendData(network.value, metric.value, range.value))
const summary = computed(() => `${networkMeta[network.value].label}${metricMeta[metric.value].label}，最近${range.value}小时，单位${metricMeta[metric.value].unit}，共${data.value.points.length}个采样点。${data.value.anomalyIndex >= 0 ? '已标注10:35压力异常下降时点。' : '当前指标未标记异常。'}`)
const timeFormatter = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false })
function renderChart() {
  if (!chart) return
  const meta = metricMeta[metric.value]
  const points = data.value.points
  const values = points.map(point => point.value)
  const width = element.value?.clientWidth ?? 900
  const minValue = Math.min(...values)
  const maxValue = Math.max(...values)
  const padding = Math.max((maxValue - minValue) * .5, maxValue * .035)
  const option: EChartsCoreOption = {
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    animationDuration: 300,
    aria: { enabled: true, label: { description: summary.value } },
    grid: { left: 13, right: 20, top: 34, bottom: 12, containLabel: true },
    tooltip: { trigger: 'axis', confine: true, backgroundColor: '#242239', borderColor: '#57506f', textStyle: { color: '#f3f0ff', fontSize: 12 }, valueFormatter: (value: unknown) => `${Number(value).toFixed(meta.decimals)} ${meta.unit}` },
    xAxis: { type: 'category', boundaryGap: false, data: points.map(point => timeFormatter.format(new Date(point.time))), axisLine: { lineStyle: { color: '#333249' } }, axisTick: { show: false }, axisLabel: { color: '#a6a3b8', fontSize: 11, margin: 17, interval: width < 500 ? 5 : 2, showMaxLabel: true, hideOverlap: true } },
    yAxis: { type: 'value', name: meta.unit, nameTextStyle: { color: '#b2aec6', fontSize: 11, align: 'left', padding: [0, 0, 0, -12] }, min: Math.max(0, Number((minValue - padding).toFixed(meta.decimals + 1))), max: Number((maxValue + padding).toFixed(meta.decimals + 1)), splitNumber: 4, axisLabel: { color: '#a6a3b8', fontSize: 11, formatter: (value: number) => value.toFixed(meta.decimals) }, splitLine: { lineStyle: { color: 'rgba(165,157,204,0.09)' } } },
    series: [{ type: 'line', name: meta.label, data: values, smooth: .3, symbol: 'circle', symbolSize: width < 500 ? 4 : 6, itemStyle: { color: '#151426', borderColor: meta.color, borderWidth: 2 }, lineStyle: { color: meta.color, width: 2.5, shadowBlur: 9, shadowColor: `${meta.color}55` }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${meta.color}25` }, { offset: 1, color: `${meta.color}00` }] } },
      ...(data.value.anomalyIndex >= 0 ? {
        markPoint: { symbol: 'circle', symbolSize: 11, itemStyle: { color: '#ff789e', borderWidth: 3, borderColor: '#6b324f' }, label: { show: true, formatter: '压力异常', position: 'top', align: 'right', distance: 13, color: '#ffd4e1', fontSize: 11, backgroundColor: '#74314d', borderRadius: 4, padding: [6, 9] }, data: [{ coord: [data.value.anomalyIndex, points[data.value.anomalyIndex]!.value] }] },
      } : {}),
    }],
  }
  chart.setOption(option, true)
}
onMounted(() => {
  if (!element.value) return
  chart = init(element.value, undefined, { renderer: 'canvas' })
  renderChart()
  observer = new ResizeObserver(() => { chart?.resize(); renderChart() })
  observer.observe(element.value)
})
watch([network, metric, range], renderChart)
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<template>
  <div ref="element" class="trend-chart" role="img" :aria-label="summary" data-testid="trend-chart" :data-network="network" :data-metric="metric" :data-range="range"></div>
</template>
