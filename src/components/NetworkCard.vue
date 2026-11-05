<script setup lang="ts">
import { ArrowDownRight, ArrowUpRight, Gauge, Thermometer, Waves } from 'lucide-vue-next'
import { metricMeta, networkMeta, networkReadings } from '../data/demo'
import type { MetricKey, NetworkKey } from '../data/demo'
defineProps<{ network: NetworkKey }>()
const metrics: MetricKey[] = ['temperature', 'pressure', 'flow']
const icons = { temperature: Thermometer, pressure: Gauge, flow: Waves }
</script>

<template>
  <section :class="['panel', 'network-card', network]" :aria-label="networkMeta[network].label + '运行指标'">
    <div class="network-heading"><div><span class="network-tag">{{ networkMeta[network].label }}</span><h2>{{ network === 'primary' ? '主网' : '次网' }}</h2></div><span class="network-description">{{ networkMeta[network].description }}<span class="point-count"> · {{ networkMeta[network].pointCount }} 个测点</span></span><i class="panel-glint"></i></div>
    <div v-for="metric in metrics" :key="metric" class="reading-row">
      <component :is="icons[metric]" :size="22" class="reading-icon" aria-hidden="true" />
      <span class="reading-label">{{ metricMeta[metric].label }}</span>
      <span class="reading-value">{{ networkReadings[network][metric].value.toFixed(metricMeta[metric].decimals) }}<small>{{ metricMeta[metric].unit }}</small></span>
      <span class="reading-reference">{{ networkReadings[network][metric].range.join('–') }}<small> {{ metricMeta[metric].unit }}</small></span>
      <span :class="['reading-delta', networkReadings[network][metric].delta >= 0 ? 'up' : 'down']"><component :is="networkReadings[network][metric].delta >= 0 ? ArrowUpRight : ArrowDownRight" :size="13" aria-hidden="true" />{{ networkReadings[network][metric].delta >= 0 ? '+' : '' }}{{ networkReadings[network][metric].delta }}</span>
    </div>
    <div class="network-footnote"><span>{{ network === 'primary' ? '异常前参考值' : '参考运行值' }}</span><span>参考区间 / 较上一采样点</span></div>
  </section>
</template>
