import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './styles/v89.css'

import Overview from './views/Overview.vue'
import Networks from './views/Networks.vue'
import Detections from './views/Detections.vue'
import Diagnosis from './views/Diagnosis.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', component: Overview },
    { path: '/networks', component: Networks },
    { path: '/detections', component: Detections },
    { path: '/diagnosis', component: Diagnosis },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

createApp(App).use(router).mount('#app')
