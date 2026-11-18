<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref,watch} from 'vue'
import {init,use,type EChartsType} from 'echarts/core'
import {LineChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,MarkAreaComponent,AriaComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
use([LineChart,GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,MarkAreaComponent,AriaComponent,CanvasRenderer])
const props=defineProps<{series:{name:string;unit:string;color:string;data:[string,number|null][]}[];focus?:{start:string;end:string};events?:{id:string;start:string;end:string}[]}>()
const emit=defineEmits<{select:[id:string]}>(),host=ref<HTMLDivElement>();let chart:EChartsType|undefined,resize:ResizeObserver|undefined
function render(target=chart,full=false){if(!target)return;const units=[...new Set(props.series.map(s=>s.unit))],css=getComputedStyle(document.documentElement),color=(v:string)=>css.getPropertyValue(v).trim()
 target.setOption({animation:false,aria:{enabled:true},tooltip:{trigger:'axis',renderMode:'richText',backgroundColor:color('--surface'),textStyle:{color:color('--text')}},legend:{type:'scroll',top:0,textStyle:{color:color('--text')}},grid:{left:55,right:units.length>2?115:55,top:65,bottom:70},xAxis:{type:'time',axisLabel:{color:color('--muted'),hideOverlap:true},axisLine:{lineStyle:{color:color('--border')}}},yAxis:units.map((u,i)=>({type:'value',name:u,scale:true,position:i?'right':'left',offset:i>1?60:0,axisLabel:{color:color('--muted')},splitLine:{show:i===0,lineStyle:{color:color('--border')}}})),dataZoom:[{type:'inside',startValue:!full&&props.focus?Date.parse(props.focus.start)-1800000:undefined,endValue:!full&&props.focus?Date.parse(props.focus.end)+1800000:undefined},{type:'slider',bottom:8,height:20}],series:props.series.map((s,i)=>({name:s.name,type:'line',showSymbol:false,connectNulls:false,yAxisIndex:units.indexOf(s.unit),lineStyle:{color:s.color,width:2,type:s.name==='阈值'?'dashed':'solid'},itemStyle:{color:s.color},data:s.data.map(([t,v])=>[Date.parse(t),v]),markArea:i===0?{silent:false,itemStyle:{color:color('--danger-soft')},label:{show:false},data:props.events?.map(e=>[{name:e.id,xAxis:Date.parse(e.start)},{xAxis:Date.parse(e.end)+1}])}:undefined}))},true)
}
onMounted(()=>{if(!host.value)return;chart=init(host.value);render();chart.on('click',p=>{if(typeof p.name==='string'&&props.events?.some(e=>e.id===p.name))emit('select',p.name)});resize=new ResizeObserver(()=>chart?.resize());resize.observe(host.value)})
watch(()=>[props.series,props.focus,props.events],()=>render(),{deep:true,flush:'post'});onBeforeUnmount(()=>{resize?.disconnect();chart?.dispose()})
defineExpose({image:()=>{const element=document.createElement('div');element.style.cssText='position:fixed;left:-10000px;top:0;width:1400px;height:560px';document.body.append(element);const output=init(element);try{render(output,true);return output.getDataURL({type:'png',pixelRatio:1.5,backgroundColor:'#ffffff'})}finally{output.dispose();element.remove()}}})
</script>
<template><div ref="host" class="local-chart" role="img" aria-label="本机数据时序曲线，可切换图例、悬浮查看和缩放" :data-focused-event="focus?.start" /></template>
