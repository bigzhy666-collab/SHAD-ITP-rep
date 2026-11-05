import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Overview from './views/Overview.vue'
import Networks from './views/Networks.vue'
import Detections from './views/Detections.vue'
import Analysis from './views/Analysis.vue'
import Reports from './views/Reports.vue'
import '@fontsource/space-grotesk/latin-400.css'
import '@fontsource/space-grotesk/latin-700.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-600.css'
import '@fontsource/barlow-condensed/latin-600.css'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/noto-sans-sc/600.css'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', component: Overview },
    { path: '/networks', component: Networks },
    { path: '/detections/:id?', component: Detections },
    { path: '/analysis/:id?', component: Analysis },
    { path: '/reports/:id?', component: Reports },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

createApp(App).use(createPinia()).use(router).mount('#app')
