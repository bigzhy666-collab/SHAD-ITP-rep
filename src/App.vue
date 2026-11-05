<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue'
import {RouterLink,RouterView,useRoute,useRouter} from 'vue-router'
import {Activity,ArrowLeftRight,Bot,ChartNoAxesCombined,FileText,LayoutDashboard,Menu,Network,RefreshCw,X} from 'lucide-vue-next'
import {useWorkspace} from './stores/workspace'
import {time} from './utils'
const store=useWorkspace(),route=useRoute(),router=useRouter(),menu=ref(false)
const nav=[{name:'总览',path:'/overview',icon:LayoutDashboard},{name:'管网管理',path:'/networks',icon:Network},{name:'异常检测',path:'/detections',icon:Activity},{name:'AI 分析',path:'/analysis',icon:Bot},{name:'诊断报告',path:'/reports',icon:FileText}]
const c=computed(()=>store.context);let timer:ReturnType<typeof setInterval>
function key(e:KeyboardEvent){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='r'&&!e.shiftKey){e.preventDefault();store.refresh()}if(e.key==='Escape')menu.value=false}
function report(){const d=store.state.detections.find(d=>d.context.segment.id===c.value?.segment.id&&d.status==='success');if(!d){store.notify('当前管段还没有已完成的检测，请先发起检测。');router.push('/detections?create=1');return}const a=store.state.analyses.find(a=>a.detectionId===d.id&&a.status==='success');router.push('/reports/'+store.createReport(d.id,a?.id))}
onMounted(()=>{store.tick();timer=setInterval(store.tick,400);window.addEventListener('keydown',key)});onBeforeUnmount(()=>{clearInterval(timer);window.removeEventListener('keydown',key)})
</script>
<template>
<a href="#main-content" class="skip-link">跳转到主要内容</a><div v-if="menu" class="nav-shade" @click="menu=false"></div>
<aside :class="['sidebar',{open:menu}]" aria-label="主导航">
<RouterLink to="/overview" class="brand"><span class="brand-icon"><ChartNoAxesCombined :size="32" /></span><div><strong>SHAD · SMART</strong><small><i class="dot"></i> CONSOLE · 演示数据</small></div><span class="version">V0.3</span></RouterLink><button class="close-nav icon-button" aria-label="关闭导航" @click="menu=false"><X :size="20" /></button>
<div class="sidebar-object"><div class="flex between"><span class="orange">受析管段</span><span class="green">本地演示</span></div><strong>{{c?.segment.name??'未选择管段'}} <template v-if="c">（DN{{c.segment.diameter}}）</template></strong><div class="muted">{{c?.network.name??'请进入管网管理选择'}} <span class="orange">{{c?.segment.code}}</span></div></div>
<div class="nav-caption">核心监测模块</div><nav><RouterLink v-for="item in nav" :key="item.path" :to="item.path" :aria-label="item.name" :class="['nav-item',{active:route.path.startsWith(item.path)}]" :aria-current="route.path.startsWith(item.path)?'page':undefined" @click="menu=false"><component :is="item.icon" :size="21" /><span>{{item.name}}</span><span v-if="item.path==='/detections'" class="nav-count">{{store.state.detections.filter(d=>d.status==='success'&&d.anomalies.length).length}}</span></RouterLink></nav>
<div class="sidebar-bottom"><button class="wide secondary orange" @click="report"><FileText :size="17" />生成分析报告</button><p>演示服务 <i class="dot"></i> 数据保存在本机</p></div></aside>
<div class="workspace"><header class="topbar"><button class="mobile-menu icon-button" aria-label="打开导航菜单" @click="menu=true"><Menu :size="22" /></button><div class="title-context"><RouterLink to="/overview"><h1>SHAD 智慧供热异常检测与辅助诊断平台</h1></RouterLink><div class="object-path"><span>{{c?.enterprise.name??'未选择企业'}}</span><span>/</span><span>{{c?.network.name??'未选择管网'}}</span><span>/</span><strong>{{c?.segment.name??'未选择管段'}}<template v-if="c">（DN{{c.segment.diameter}}）</template></strong><RouterLink to="/networks?pick=1" class="icon-button" aria-label="切换管段对象" title="切换管段对象"><ArrowLeftRight :size="18" /></RouterLink></div></div><div class="header-tools"><span class="badge green">演示服务</span><span class="clock mono">{{time(store.updatedAt)}}</span><button class="icon-button" :disabled="store.refreshing" aria-label="刷新数据" title="刷新数据 (Ctrl+R)" @click="store.refresh"><RefreshCw :size="18" :class="{spin:store.refreshing}" /></button><span class="avatar">07</span><span class="user-name">演示用户</span></div></header>
<div v-if="store.storageError" class="storage-warning" role="alert">{{store.storageError}} <button @click="store.save">重试保存</button></div><main id="main-content" tabindex="-1"><RouterView /></main><footer class="app-footer"><span>SHAD · 前端交互演示</span><span>数据、检测、模型评分均为演示结果 · 不连接真实设备</span></footer></div>
<div v-if="store.message" class="toast" role="status"><span>{{store.message}}</span><button class="icon-button" aria-label="关闭提示" @click="store.message=''"><X :size="16" /></button></div>
</template>
