import {defineConfig} from '@playwright/test'
import path from 'node:path'

// A separate data directory prevents integration checks from touching user data.
const dataDir=path.resolve('backend/data',`browser-check-${Date.now()}`)
export default defineConfig({
 testDir:'./integration/backend',outputDir:'test-results-backend',workers:1,retries:0,timeout:45_000,
 reporter:[['list']],
 use:{baseURL:'http://127.0.0.1:18765',browserName:'chromium',channel:'chromium',
  viewport:{width:1366,height:900},locale:'zh-CN',timezoneId:'Asia/Shanghai',
  reducedMotion:'reduce',trace:'retain-on-failure',screenshot:'only-on-failure'},
 webServer:{command:`"${path.resolve('.venv-backend/Scripts/python.exe')}" -m backend.tests.browser_server --port 18765 --data-dir "${dataDir}"`,
  url:'http://127.0.0.1:18765/api/runtime',reuseExistingServer:false,timeout:30_000},
})
