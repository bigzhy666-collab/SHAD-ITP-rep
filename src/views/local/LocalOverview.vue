<script setup lang="ts">
import {onBeforeUnmount,ref,watch} from 'vue'
import {useIntegration} from '../../stores/integration'
import {useWorkspace} from '../../stores/workspace'
import {allPages,errorText,localApi} from '../../services/local/api'
import type {Task} from '../../services/local/types'
import {taskLabel} from '../../services/local/fields'
import {time} from '../../utils'
import Panel from '../../components/Panel.vue'
import ServiceState from '../../components/local/ServiceState.vue'
const service=useIntegration(),workspace=useWorkspace(),tasks=ref<Task[]>([]),loading=ref(false),error=ref('');let controller:AbortController|undefined
watch([()=>service.ready,()=>service.revision,()=>workspace.context?.segment.id],async()=>{controller?.abort();controller=new AbortController();const c=controller;tasks.value=[];error.value='';if(!service.ready||!workspace.context)return;loading.value=true
 try{tasks.value=await allPages(p=>localApi.detections(workspace.context!.segment.id,p,c.signal))}catch(e){if(!c.signal.aborted)error.value=errorText(e)}finally{if(!c.signal.aborted)loading.value=false}
},{immediate:true});onBeforeUnmount(()=>controller?.abort())
</script>
<template><div class="page-stack local-page"><div class="page-actions"><div><h2>总览</h2><p class="muted">查看当前管段的本机检测记录与接入状态。</p></div><RouterLink to="/networks" class="primary">关联站点与导入数据</RouterLink></div><ServiceState><Panel title="本机运行状态"><dl class="detail-list"><div><dt>服务版本</dt><dd>{{service.runtime?.serviceVersion}}</dd></div><div><dt>当前对象</dt><dd>{{workspace.context?.segment.name??'未选择'}}</dd></div><div><dt>异常检测</dt><dd>{{service.runtime?.capabilities.anomalyDetection?'已启用':'尚未启用'}}</dd></div><div><dt>原因诊断</dt><dd>{{service.runtime?.capabilities.causeDiagnosis?'已启用，待按任务查看':'尚未接入'}}</dd></div><div><dt>报告本机存档</dt><dd>{{service.runtime?.capabilities.reportPersistence?'已启用':'尚未接入'}}</dd></div></dl><p class="muted">此处仅显示本机后端返回的信息。真实设备连接状态不由前端模拟。</p></Panel><Panel title="当前管段检测记录"><template #tools><RouterLink to="/detections">进入数据监测</RouterLink></template><p v-if="loading" role="status">正在读取检测记录…</p><p v-if="error" class="error" role="alert">{{error}} <button @click="service.refresh">重试读取</button></p><div v-else class="table-wrap"><table><thead><tr><th>任务</th><th>站点</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="t in tasks" :key="t.id"><td>{{t.name}}</td><td>{{t.contextSnapshot.station.name}}</td><td>{{time(t.createdAt)}}</td><td>{{taskLabel[t.status]}}</td><td><RouterLink :to="'/detections/'+encodeURIComponent(t.id)">查看检测</RouterLink></td></tr><tr v-if="!loading&&!tasks.length"><td colspan="5" class="empty">暂无真实检测任务。请先关联站点、导入数据并创建检测。</td></tr></tbody></table></div></Panel></ServiceState></div></template>
