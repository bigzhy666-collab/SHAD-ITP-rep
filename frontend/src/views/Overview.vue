<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref} from 'vue'

const sceneRoot=ref<HTMLElement>()
const index=ref(0)
let api:any=undefined
let disposed=false
const FIELDS=['outdoor_temperature','p_net_supply_temperature','p_net_return_temperature',
  'p_net_meter_heat_power','p_net_meter_flow','p_hc1_return_temperature','s_hc1_supply_temperature','s_hc1_supply_temperature_setpoint']

async function getJson(url:string){
  const r=await fetch(url);const b=await r.json().catch(()=>({}))
  if(!r.ok||b.error)throw new Error(b?.error?.message||String(r.status))
  return b.data
}

/* 把导入数据喂给编译版场景：setSeries({站名:{times,values}}) */
async function feed(){
  const seg=localStorage.getItem('shad-local-segment')||'seg-1'
  const stations=(await getJson(`/api/stations?segmentId=${seg}&page=1&pageSize=500`)).items||[]
  const series:Record<string,{times:string[];values:Record<string,number[]>}>={}
  for(const st of stations){
    let ds:any
    try{ds=((await getJson(`/api/datasets?stationId=${st.id}&page=1&pageSize=50`)).items||[]).find((d:any)=>d.status==='ready')}catch{continue}
    if(!ds)continue
    const rows:any[]=[]
    for(let page=1;page<=4;page++){
      const r=await getJson(`/api/datasets/${ds.id}/samples?start=${encodeURIComponent(ds.start)}&end=${encodeURIComponent(ds.end)}&fields=${FIELDS.join(',')}&page=${page}&pageSize=500`)
      const items=r.items||[]
      rows.push(...items)
      if(items.length<500)break
    }
    if(!rows.length)continue
    const values:Record<string,number[]>={}
    FIELDS.forEach(f=>{values[f]=rows.map(r=>typeof r.values?.[f]==='number'?r.values[f]:NaN)})
    series[st.name]={times:rows.map(r=>r.timestamp),values}
  }
  if(api&&Object.keys(series).length){
    api.setSeries?.(series)
    api.setIndex(0)
  }
}

/* 播放条：24 秒走完 + 收起/展开 */
const PB=24000
let playing=false,raf=0,t0=0,from=0
function pbEls(){
  return {
    btn:document.querySelector('.playbtn') as HTMLElement|null,
    range:document.querySelector('.pb-track input[type="range"]') as HTMLInputElement|null,
    time:document.querySelector('.pb-time') as HTMLElement|null,
  }
}
function pbTotal(){return Math.max(1,(api?.times?.length??1440)-1)}
function pbSet(i:number){
  const v=Math.max(0,Math.min(pbTotal(),i))
  api?.setIndex(v)
  const {range,time}=pbEls()
  if(range){
    range.value=String(v)
    const pct=pbTotal()?Math.round(v/pbTotal()*100):0
    range.style.backgroundColor='transparent'
    range.style.backgroundImage=`linear-gradient(90deg,#2563EB 0 ${pct}%,#d7dde6 ${pct}% 100%)`
    range.style.backgroundSize='100% 3px'
    range.style.backgroundRepeat='no-repeat'
    range.style.backgroundPosition='center'
  }
  if(time&&api?.times?.[v]!=null)time.textContent=api.times[v]
}
function pbStop(){
  playing=false
  if(raf)cancelAnimationFrame(raf)
  raf=0
  const {btn}=pbEls()
  if(btn){btn.setAttribute('aria-label','播放');btn.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5.2v13.6c0 .5.5.8.9.5l10.2-6.8a.6.6 0 0 0 0-1L8.9 4.7c-.4-.3-.9 0-.9.5z" fill="currentColor"></path></svg>'}
}
function pbTick(ts:number){
  if(!playing)return
  if(!t0)t0=ts
  const k=Math.min(1,(ts-t0)/PB)
  pbSet(Math.round(from+(pbTotal()-from)*k))
  if(k>=1){pbStop();return}
  raf=requestAnimationFrame(pbTick)
}
function pbToggle(){
  if(playing){pbStop();return}
  const {btn,range}=pbEls()
  playing=true
  from=range?Number(range.value):0
  if(from>=pbTotal())from=0
  t0=0
  if(btn){btn.setAttribute('aria-label','暂停');btn.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M7 5h3.2v14H7zM13.8 5H17v14h-3.2z" fill="currentColor"></path></svg>'}
  raf=requestAnimationFrame(pbTick)
}
function bindChrome(){
  // 能源站不参与“选中”：模块选中后就撤销面板与标题
  const scene=document.querySelector('.pipe-model-scene')
  if(scene){
    scene.addEventListener('click',()=>{
      setTimeout(()=>{
        const name=document.getElementById('infoName')?.textContent||''
        if(!name.includes('能源站'))return
        const info=document.getElementById('info')
        info?.classList.remove('show')
        if(info)info.style.display='none'
        const h4=document.querySelector('#kpiCard h4')
        if(h4)h4.textContent='运行指标 · 未选择换热站'
        const meta=document.getElementById('kpiMeta')
        if(meta)meta.textContent='点击场景中的换热站查看该站读数'
      },0)
    },true)
  }

  const {btn,range}=pbEls()
  if(range){
    // 强制细轨：某些样式表会让原生高度生效，这里用内联样式兜底
    range.style.setProperty('height','3px','important')
    range.style.setProperty('appearance','none')
    range.style.setProperty('-webkit-appearance','none')
    range.style.setProperty('border-radius','2px')
  }
  if(btn)btn.onclick=()=>pbToggle()
  if(range)range.oninput=()=>{if(playing)pbStop();pbSet(Number(range.value))}
  pbSet(range?Number(range.value):0)

  // 左侧指标卡收起/展开（只收卡片，图例不动）
  const pt=document.querySelector('.panels-toggle') as HTMLElement|null
  if(pt)pt.onclick=()=>{
    const expanded=pt.getAttribute('aria-expanded')!=='false'
    pt.setAttribute('aria-expanded',String(!expanded))
    const card=document.getElementById('kpiCard')
    if(card)card.style.display=expanded?'none':''
    pt.style.left=expanded?'16px':'228px'
    const svg=pt.querySelector('svg');if(svg)(svg as SVGElement).style.transform=expanded?'rotate(180deg)':''
  }

  // 进度条收起/展开（就是这个按钮）
  const pbt=document.querySelector('.playback-toggle') as HTMLElement|null
  const bar=document.querySelector('.model-playback') as HTMLElement|null
  if(pbt&&bar)pbt.onclick=()=>{
    const expanded=pbt.getAttribute('aria-expanded')!=='false'
    pbt.setAttribute('aria-expanded',String(!expanded))
    pbt.setAttribute('aria-label',expanded?'显示演示进度条':'隐藏演示进度条')
    pbt.setAttribute('title',expanded?'显示演示进度条':'隐藏演示进度条')
    bar.style.display=expanded?'none':''
    const svg=pbt.querySelector('svg');if(svg)(svg as SVGElement).style.transform=expanded?'rotate(180deg)':''
  }
}

onMounted(async()=>{
  // 编译版场景模块：原始字节 + Blob 导入，保证与 v8.9 完全一致
  const code=await (await fetch('/assets/scene-CMY4nqBr.js')).text()
  const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}))
  const mod=await import(/* @vite-ignore */ url)
  if(disposed)return
  api=mod.mountScene(sceneRoot.value,(i:number)=>{index.value=i})
  try{await feed()}catch{}
  bindChrome()
})

onBeforeUnmount(()=>{disposed=true;pbStop();api?.dispose()})
</script>

<template>
<div class="page-stack local-page"><div class="model-page is-embedded"><!----><!----><!----><div class="pipe-model-scene" ref="sceneRoot"><canvas id="c" width="1143" height="558"></canvas><header class="top"><div class="pick"><select id="entSel" aria-label="选择企业"></select><span class="slash">/</span><select id="netSel" aria-label="选择管网"></select><span class="slash">/</span><select id="segSel" aria-label="选择管段"></select></div><div class="spacer"></div><div class="seg" id="modeSeg"><button data-mode="ground" class="on">地面</button><button data-mode="under">地下</button><button data-mode="clear">透明地面</button></div><button class="tbtn" id="btnLayers">图层</button><button class="tbtn" id="btnReset">复位视角</button></header><div class="model-panels"><div class="left" tabindex="0" aria-label="运行指标，可滚动查看"><div class="card" id="kpiCard"></div></div></div><button class="panels-toggle" type="button" aria-expanded="true" aria-label="隐藏运行指标与图例" title="隐藏运行指标与图例"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6.5 9 12l5.5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path></svg></button><div class="legend-dock" id="legend" aria-label="图例"><div class="row"><i style="--c:var(--p1);"></i>一次网供水</div><div class="row"><i class="dashed" style="--c:var(--p1r);"></i>一次网回水</div><div class="row"><i style="--c:var(--p2);"></i>二次网供水</div><div class="row"><i class="dashed" style="--c:var(--p2r);"></i>二次网回水</div><div class="row"><i style="background:#E23B3B;"></i>异常管段</div><div class="row" style="margin-top:3px;padding-top:5px;border-top:1px solid var(--line);"><span class="sw" style="background:#EDEFF2;border:1px solid #cfd6de;"></span>建筑 <span class="sw" style="background:#E4E1D8;margin-left:8px;"></span>道路 </div></div><aside class="info" id="info" style="display:none;" aria-hidden="true"><div class="hd"><span class="tag" id="infoTag">管线</span><button class="x" id="infoClose">×</button></div><h3 id="infoName">—</h3><div class="sub" id="infoSub">—</div><dl id="infoDl"></dl><div class="state ok" id="infoState">正常运行</div></aside><div class="hint" id="hint">点击站点居中并拉近 · 拖动旋转 · 右键平移 · 滚轮缩放</div><div class="badge-demo">几何：<b>示意街区</b>（待图纸配准） · 读数：<b>本机导入优先</b>，未导入则为无 · 异常标注依据导入数据（二次供水 &gt; 80 ℃）</div><div class="toast" id="toast"></div><div class="alarm-overlay"><button class="station-target" type="button" aria-label="聚焦5#能源站" aria-pressed="false" title="点击居中并拉近：5#能源站" style="left: 550.051px; top: 135.616px;"></button><button class="station-target" type="button" aria-label="聚焦6#换热站" aria-pressed="false" title="点击居中并拉近：6#换热站" style="left: 784.398px; top: 307.736px;"></button><button class="station-target" type="button" aria-label="聚焦5#换热站" aria-pressed="false" title="点击居中并拉近：5#换热站" style="left: 586.374px; top: 315.452px;"></button><button class="station-target" type="button" aria-label="聚焦4#换热站" aria-pressed="false" title="点击居中并拉近：4#换热站" style="left: 368.784px; top: 323.932px;"></button><button class="station-target" type="button" aria-label="聚焦3#换热站" aria-pressed="false" title="点击居中并拉近：3#换热站" style="left: 738.024px; top: 192.079px;"></button><button class="station-target" type="button" aria-label="聚焦2#换热站" aria-pressed="false" title="点击居中并拉近：2#换热站" style="left: 576.028px; top: 197.225px;"></button><button class="station-target" type="button" aria-label="聚焦1#换热站" aria-pressed="false" title="点击居中并拉近：1#换热站" style="left: 398.853px; top: 202.854px;"></button></div></div><div class="model-playback"><button class="playbtn" aria-label="播放" title="播放"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5.2v13.6c0 .5.5.8.9.5l10.2-6.8a.6.6 0 0 0 0-1L8.9 4.7c-.4-.3-.9 0-.9.5z" fill="currentColor"></path></svg></button><div class="pb-track"><input type="range" aria-label="演示时间" min="0" max="1439" value="1120"></div><span class="pb-time">11-26 08:00</span><button class="pb-locate" disabled>定位异常</button></div><button class="playback-toggle" type="button" aria-expanded="true" aria-label="隐藏演示进度条" title="隐藏演示进度条"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path></svg></button></div><div class="overview-grid"><section class="panel overview-panel"><header class="panel-heading"><h2>本机运行状态</h2><div class="panel-tools"></div></header><div class="panel-body"><dl class="detail-list"><div><dt>服务版本</dt><dd>0.6.0</dd></div><div><dt>当前对象</dt><dd>1号二次供热管段</dd></div><div><dt>异常检测</dt><dd>已启用</dd></div><div><dt>报告本机存档</dt><dd>已启用</dd></div></dl></div></section><section class="panel overview-panel"><header class="panel-heading"><h2>当前管段检测记录</h2><div class="panel-tools"><a href="/detections" class="">进入数据监测</a></div></header><div class="panel-body"><!----><div class="table-wrap"><table><thead><tr><th>任务</th><th>站点</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead><tbody></tbody></table><!----></div></div></section></div></div>
</template>
