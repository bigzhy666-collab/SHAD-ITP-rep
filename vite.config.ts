import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
          framework: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
  test: { include: ['src/**/*.test.ts'] },
})
