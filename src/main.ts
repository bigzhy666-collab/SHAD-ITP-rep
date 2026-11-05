import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Overview from './views/Overview.vue'
import Networks from './views/Networks.vue'
import Detections from './views/Detections.vue'
import Diagnosis from './views/Diagnosis.vue'
import './style.css'
import './theme.css'

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
