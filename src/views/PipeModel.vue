<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue'
import '../model/scene.css'
const root=ref<HTMLElement>(),error=ref(''),loading=ref(true),index=ref(0),count=ref(0),times=ref<string[]>([]),playing=ref(false)
let api:ReturnType<typeof import('../model/scene').mountScene>|undefined
let timer:ReturnType<typeof setInterval>|undefined,disposed=false
function pause(){clearInterval(timer);playing.value=false}
function play(){if(playing.value){pause();return}playing.value=true;timer=setInterval(()=>api?.setIndex((index.value+1)%count.value),500)}
function seek(e:Event){pause();api?.setIndex(Number((e.target as HTMLInputElement).value))}
onMounted(async()=>{try{const {mountScene}=await import('../model/scene');if(disposed)return;api=mountScene(root.value!,i=>index.value=i);count.value=api.count;times.value=api.times}catch(e){error.value='模型加载失败，请重新打开页面。';console.error(e)}finally{loading.value=false}})
onBeforeUnmount(()=>{disposed=true;pause();api?.dispose()})
</script>
<template><div class="model-page"><div class="page-actions"><div><h2>管网模型</h2><p class="muted">示意街区 · 演示时序 · 未联动真实检测；场景选择不改变本机业务对象。</p></div></div><p v-if="loading" role="status">正在加载管网模型…</p><p v-if="error" role="alert">{{error}} <button @click="$router.go(0)">重新加载</button></p><div ref="root" v-show="!error" class="pipe-model-scene">
  <canvas id="c"></canvas>
  <div class="grid-ov" id="gridOv"></div>

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
    <div class="card" id="kpiCard"><h4>运行指标 · 固定快照</h4></div>
  </div>

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
</div><div class="model-playback"><button :disabled="!api" @click="play">{{playing?'暂停':'播放'}}</button><label>演示时间 <input type="range" aria-label="演示时间" min="0" :max="Math.max(count-1,0)" :value="index" @input="seek" /></label><span>{{times[index]}}</span><button :disabled="!api||api.firstAlarm<0" @click="pause();api?.setIndex(api.firstAlarm)">定位演示异常</button></div></div></template>
