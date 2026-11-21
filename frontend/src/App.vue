<script setup lang="ts">
// scroll-reset：切页/切站后回到顶部
if(!(window as any).__scrollReset){
  (window as any).__scrollReset=true
  const back=()=>window.scrollTo(0,0)
  const push=history.pushState.bind(history)
  history.pushState=function(this:History,data:any,unused:string,url?:string|URL|null){const r=push(data,unused,url);back();return r} as typeof history.pushState
  window.addEventListener('popstate',back)
}

import {onMounted,onBeforeUnmount,ref} from 'vue'
import HelpOverlay from './components/HelpOverlay.vue'
const helpOpen=ref(false)

let clockTimer:number|undefined
let observer:MutationObserver|undefined

function two(n:number){return String(n).padStart(2,'0')}
function bindHelp(){
  const btn=document.querySelector('.help-button') as HTMLElement|null
  if(btn)btn.onclick=()=>{helpOpen.value=true}
  // 关闭：× 按钮、点遮罩、Esc
  document.addEventListener('click',(e)=>{
    const t=e.target as HTMLElement|null
    if(!t)return
    if(t.closest('.help-x')||t.classList.contains('help-backdrop'))helpOpen.value=false
  },true)
  document.addEventListener('keydown',(e)=>{
    if(e.key==='Escape')helpOpen.value=false
  })
}

function tickClock(){
  const el=document.querySelector('.clock') as HTMLElement|null
  if(!el)return
  const d=new Date()
  el.textContent=`${d.getFullYear()}/${two(d.getMonth()+1)}/${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`
}

/* 实时模式：不渲染业务页，统一显示「未实装」占位（对照需求 5.1） */
function applyMode(){
  const sel=document.querySelector('select[aria-label="运行模式"]') as HTMLSelectElement|null
  const main=document.getElementById('main-content')
  if(!main)return
  const demo=sel?.value==='demo'
  let ph=document.getElementById('modePlaceholder') as HTMLElement|null
  if(demo){
    if(!ph){
      ph=document.createElement('div')
      ph.id='modePlaceholder'
      ph.setAttribute('role','status')
      ph.style.cssText='display:flex;align-items:center;justify-content:center;min-height:60vh;color:#64748b;font-size:14px;letter-spacing:.02em'
      ph.textContent='实时模式尚未接入数据源 · 未实装'
      main.appendChild(ph)
    }
    Array.from(main.children).forEach(c=>{if(c!==ph)(c as HTMLElement).style.display='none'})
  }else{
    ph?.remove()
    Array.from(main.children).forEach(c=>{(c as HTMLElement).style.display=''})
  }
}

function syncChrome(){
  const path=location.pathname.replace('/','')||'overview'
  document.querySelectorAll('.nav-item').forEach(el=>{
    const href=(el.getAttribute('href')||'').replace('/','')
    el.classList.toggle('active',href===path)
    if(href===path)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current')
  })
  const sel=document.querySelector('select[aria-label="运行模式"]') as HTMLSelectElement|null
  if(sel&&!sel.dataset.bound){
    sel.dataset.bound='1'
    sel.value='local'            // 本机数据：默认进入导入模式
    sel.addEventListener('change',applyMode)
  }
  applyMode()
}

function widenHeader(){
  const tools=document.querySelector('.header-tools') as HTMLElement|null
  if(tools){tools.style.gap='16px'}
}

onMounted(()=>{
  bindHelp()
  syncChrome();tickClock();widenHeader()
  clockTimer=window.setInterval(tickClock,1000)
  observer=new MutationObserver(()=>{syncChrome();widenHeader()})
  observer.observe(document.getElementById('app')!,{childList:true,subtree:true})
})
onBeforeUnmount(()=>{window.clearInterval(clockTimer);observer?.disconnect()})
</script>

<template>
<div id="app" ><a href="#main-content" class="skip-link">跳转到主要内容</a><!----><aside class="sidebar" aria-label="主导航"><a href="/overview" class="router-link-active router-link-exact-active brand" aria-label="SHAD 首页" aria-current="page"><img class="brand-mark" src="/shad-mark.svg" alt=""><div class="brand-copy"><div class="brand-title-row"><strong>SHAD</strong></div><small><i class="dot"></i> CONSOLE · 本机数据</small></div></a><button class="close-nav icon-button" aria-label="关闭导航"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-xicon"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg></button><div class="sidebar-object"><div class="flex between"><span class="orange">受析管段</span><span class="orange">导入模式</span></div><strong>1号二次供热管段 <!----></strong><div class="muted">城北主力供热网 <span class="orange">ST-P01</span></div></div><div class="nav-caption">核心监测模块</div><nav><a href="/overview" class="router-link-active router-link-exact-active nav-item active" aria-label="总览" aria-current="page"><svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-layout-dashboard-icon"><rect width="7" height="9" x="3" y="3" rx="1"></rect><rect width="7" height="5" x="14" y="3" rx="1"></rect><rect width="7" height="9" x="14" y="12" rx="1"></rect><rect width="7" height="5" x="3" y="16" rx="1"></rect></svg><span>总览</span><!----></a><a href="/networks" class="nav-item" aria-label="管网管理"><svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-network-icon"><rect x="16" y="16" width="6" height="6" rx="1"></rect><rect x="2" y="16" width="6" height="6" rx="1"></rect><rect x="9" y="2" width="6" height="6" rx="1"></rect><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"></path><path d="M12 12V8"></path></svg><span>管网管理</span><!----></a><a href="/detections" class="nav-item" aria-label="数据监测"><svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-activity-icon"><path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"></path></svg><span>数据监测</span><!----></a><a href="/diagnosis" class="nav-item" aria-label="检测报告"><svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-bot-icon"><path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg><span>检测报告</span><!----></a></nav><div class="sidebar-bottom"><button class="wide secondary help-button">使用说明与帮助</button><p>导入模式 · 历史由后端保存</p></div></aside><div class="workspace"><header class="topbar"><button class="mobile-menu icon-button" aria-label="打开导航菜单"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-menu-icon"><line x1="4" x2="20" y1="12" y2="12"></line><line x1="4" x2="20" y1="6" y2="6"></line><line x1="4" x2="20" y1="18" y2="18"></line></svg></button><div class="title-context"><a href="/overview" class="router-link-active router-link-exact-active" aria-current="page"><h1>智慧供热异常检测与辅助诊断平台</h1><p class="title-en">Smart Heating Anomaly Detection &amp; Diagnosis Platform</p></a></div><div class="header-tools"><select class="service-mode" aria-label="运行模式" value="local"><option value="demo">实时模式</option><option value="local">导入模式</option></select><span class="badge green">已连接</span><span class="clock mono">2026/11/21 21:24:19</span><button class="icon-button" aria-label="刷新数据" title="刷新数据 (Ctrl+R)"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw-icon"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg></button><span class="avatar">07</span><span class="user-name">本机用户</span></div></header><!----><!----><!----><main id="main-content" tabindex="-1"><router-view/></main></div><!---->  <HelpOverlay :open="helpOpen" @close="helpOpen=false" />
</div>
</template>
