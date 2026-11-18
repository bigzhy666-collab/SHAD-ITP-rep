import {defineConfig} from '@playwright/test'
export default defineConfig({
  testDir:'./desktop/tests',workers:1,timeout:90000,
  reporter:[['list']],use:{locale:'zh-CN',timezoneId:'Asia/Shanghai'},
  outputDir:'test-results/desktop',
})
