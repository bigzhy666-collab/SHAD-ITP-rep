<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue'
import '../model/scene.css'
const props=withDefaults(defineProps<{embedded?:boolean}>(),{embedded:false})
const root=ref<HTMLElement>(),error=ref(''),loading=ref(true),index=ref(0),count=ref(0),times=ref<string[]>([]),playing=ref(false)
let api:ReturnType<typeof import('../model/scene').mountScene>|undefined
let timer:ReturnType<typeof setInterval>|undefined,disposed=false
function pause(){clearInterval(timer);playing.value=false}
function play(){
  if(playing.value){pause();return}
  playing.value=true
  // 整段演示固定 24 秒播完，按真实流逝时间映射，避免定时器漂移
  const TOTAL=24000, t0=performance.now(), base=index.value
  timer=setInterval(()=>{
    const el=(performance.now()-t0)%TOTAL
    api?.setIndex(Math.floor((base+count.value*el/TOTAL)%count.value))
  },40)
}
function seek(e:Event){pause();api?.setIndex(Number((e.target as HTMLInputElement).value))}
onMounted(async()=>{
  ;(globalThis as any).__SHAD_NO_DEMO__ = true
  try{const {mountScene}=await import('../model/scene');if(disposed)return;api=mountScene(root.value!,i=>index.value=i);count.value=api.count;times.value=api.times;bindToggles()}catch(e){error.value='模型加载失败，请重新打开页面。';console.error(e)}finally{loading.value=false}})
function bindToggles(){
  // 图例移到场景右上角（脱离左栏）
  const lg=document.getElementById('legend')
  const sc=document.querySelector('.pipe-model-scene')
  if(lg&&sc){
    if(lg.parentElement!==sc)sc.appendChild(lg)
    lg.style.position='absolute';lg.style.right='14px';lg.style.top='64px';lg.style.zIndex='12'
  }
  const panelBtn=document.querySelector('.panels-toggle') as HTMLElement|null
  const panels=document.querySelector('.model-panels') as HTMLElement|null
  if(panelBtn&&panels){
    panelBtn.onclick=()=>{
      const expanded=panelBtn.getAttribute('aria-expanded')!=='false'   // 当前是否展开
      panelBtn.setAttribute('aria-expanded',String(!expanded))
      // 只收起指标卡，图例保持显示
      const card=document.getElementById('kpiCard')
      if(card)card.style.display=expanded?'none':''
      panelBtn.style.left=expanded?'16px':'228px'
      const svg=panelBtn.querySelector('svg'); if(svg)(svg as SVGElement).style.transform=expanded?'rotate(180deg)':''
    }
  }
  const pbBtn=document.querySelector('.playback-toggle') as HTMLElement|null
  const pb=document.querySelector('.model-playback') as HTMLElement|null
  if(pbBtn&&pb){
    pbBtn.onclick=()=>{
      const next=pbBtn.getAttribute('aria-expanded')!=='false'
      pbBtn.setAttribute('aria-expanded',String(!next))
      pb.style.display=next?'':'none'
      const svg=pbBtn.querySelector('svg'); if(svg)(svg as SVGElement).style.transform=next?'':'rotate(180deg)'
    }
  }
}

onBeforeUnmount(()=>{disposed=true;pause();api?.dispose()})
// 开发期改动模板后强制整页刷新，避免 HMR 留下“控件空、画布空”的中间态
if((import.meta as any).hot)(import.meta as any).hot.accept(()=>{location.reload()})
</script>
<template><div :class="['model-page',{'is-embedded':embedded}]"><div v-if="!embedded" class="page-actions"><div><h2>管网模型</h2><p class="muted">示意街区 · 演示时序 · 未联动真实检测；场景选择不改变本机业务对象。</p></div></div><p v-if="loading" role="status">正在加载管网模型…</p><p v-if="error" role="alert">{{error}} <button @click="$router.go(0)">重新加载</button></p><div ref="root" v-show="!error" class="pipe-model-scene">
  <canvas id="c"></canvas>
  <div class="grid-ov" id="gridOv"></div>
  <button class="panels-toggle" type="button" aria-expanded="true" aria-label="隐藏运行指标与图例" title="隐藏运行指标与图例"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6.5 9 12l5.5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>

  <header class="top">

    <div class="pick">
      <select id="entSel" aria-label="选择企业"></select>
      <span class="slash">/</span>
      <select id="netSel" aria-label="选择管网"></select>
      <span class="slash">/</span>
      <select id="segSel" aria-label="选择管段"></select>
    </div>
    <div class="spacer"></div>
    <div class="seg" id="modeSeg">
      <button data-mode="ground" class="on">地面</button>
      <button data-mode="under">地下</button>
      <button data-mode="clear">透明地面</button>
      <button data-mode="cut">剖切</button>
    </div>
    <button class="tbtn" id="btnLayers">图层</button>
    <button class="tbtn" id="btnReset">复位视角</button>
  </header>

  <div class="model-panels">
  <div class="left" tabindex="0" aria-label="运行指标，可滚动查看">
    <div class="card" id="kpiCard"><h4>运行指标 · 未选择换热站</h4><div class="kpi-meta" id="kpiMeta">点击场景中的换热站查看该站读数</div></div>

    <div class="legend" id="legend">
      <div class="row"><i style="--c:var(--p1)"></i>一次网供水</div>
      <div class="row"><i class="dashed" style="--c:var(--p1r)"></i>一次网回水</div>
      <div class="row"><i style="--c:var(--p2)"></i>二次网供水</div>
      <div class="row"><i class="dashed" style="--c:var(--p2r)"></i>二次网回水</div>
      <div class="row"><i style="background:#E23B3B"></i>异常管段</div>
      <div class="row" style="margin-top:3px;padding-top:5px;border-top:1px solid var(--line)">
        <span class="sw" style="background:#EDEFF2;border:1px solid #cfd6de"></span>建筑
        <span class="sw" style="background:#E4E1D8;margin-left:8px"></span>道路
      </div>
  </div>
  </div>



  </div>
  <aside class="info" id="info">
    <div class="hd"><span class="tag" id="infoTag">管线</span><button class="x" id="infoClose">×</button></div>
    <h3 id="infoName">—</h3>
    <div class="sub" id="infoSub">—</div>
    <dl id="infoDl"></dl>
    <div class="state ok" id="infoState">正常运行</div>
  </aside>

  <div class="hint" id="hint">点击站点居中并拉近 · 拖动旋转 · 右键平移 · 滚轮缩放</div>

  <div class="badge-demo">几何：<b>示意街区</b>（待图纸配准） · 数据：<b>演示时序</b> 30 天</div>
  <div class="toast" id="toast"></div>
</div><div class="model-playback"><button class="playbtn" :disabled="!api" @click="play" :aria-label="playing?'暂停':'播放'" :title="playing?'暂停':'播放'">
      <svg v-if="!playing" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5.2v13.6c0 .5.5.8.9.5l10.2-6.8a.6.6 0 0 0 0-1L8.9 4.7c-.4-.3-.9 0-.9.5z" fill="currentColor"/></svg>
      <svg v-else viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="6.5" y="5" width="3.6" height="14" rx="1" fill="currentColor"/><rect x="13.9" y="5" width="3.6" height="14" rx="1" fill="currentColor"/></svg>
    </button><label> <input type="range" aria-label="" min="0" :max="Math.max(count-1,0)" :value="index" @input="seek" /></label><span>{{times[index]}}</span><button :disabled="!api||api.firstAlarm<0" @click="pause();api?.setIndex(api.firstAlarm)">定位演示异常</button></div></div></template>
