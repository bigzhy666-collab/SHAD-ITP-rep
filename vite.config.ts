import { defineConfig } from 'vitest/config'
import {loadEnv} from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({mode})=>{
 const target=loadEnv(mode,process.cwd(),'SHAD_').SHAD_BACKEND_URL||'http://127.0.0.1:8765'
 const address=new URL(target)
 if(!['127.0.0.1','localhost','[::1]'].includes(address.hostname)||!['http:','https:'].includes(address.protocol))throw new Error('SHAD_BACKEND_URL 必须是本机 HTTP 服务地址。')
 return {
  plugins: [vue()],
  server:{proxy:{'/api':{target}}},
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
}})
