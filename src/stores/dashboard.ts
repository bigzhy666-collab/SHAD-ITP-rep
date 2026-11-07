import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MetricKey, NetworkKey, RangeKey } from '../data/demo'

export const useDashboardStore = defineStore('dashboard', () => {
  const network = ref<NetworkKey>('primary')
  const metric = ref<MetricKey>('pressure')
  const range = ref<RangeKey>(1)
  return { network, metric, range }
})
