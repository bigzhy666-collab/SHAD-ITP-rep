import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import ModePage from './views/ModePage.vue'
import './style.css'
import './theme.css'
import './local.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', component: ModePage, props:{page:'overview'} },
    { path: '/networks', component: ModePage, props:{page:'networks'} },
    { path: '/detections/:id?', component: ModePage, props:{page:'detections'} },
    { path: '/diagnosis/:id?', component: ModePage, props:{page:'diagnosis'} },
    { path: '/analysis/:id?', redirect: to => ({path:'/diagnosis'+(to.params.id?'/'+to.params.id:''),query:to.query}) },
    { path: '/reports/:id?', redirect: to => ({path:'/diagnosis'+(to.params.id?'/'+to.params.id:''),query:to.params.id?to.query:{...to.query,history:'reports'}}) },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

createApp(App).use(createPinia()).use(router).mount('#app')
