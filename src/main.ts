import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Overview from './views/Overview.vue'
import Networks from './views/Networks.vue'
import Detections from './views/Detections.vue'
import Diagnosis from './views/Diagnosis.vue'
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
    { path: '/diagnosis/:id?', component: Diagnosis },
    { path: '/analysis/:id?', redirect: to => ({path:'/diagnosis'+(to.params.id?'/'+to.params.id:''),query:to.query}) },
    { path: '/reports/:id?', redirect: to => ({path:'/diagnosis'+(to.params.id?'/'+to.params.id:''),query:to.params.id?to.query:{...to.query,history:'reports'}}) },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

createApp(App).use(createPinia()).use(router).mount('#app')
