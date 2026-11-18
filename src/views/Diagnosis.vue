<script setup lang="ts">
import {computed,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {useWorkspace} from '../stores/workspace'
import Panel from '../components/Panel.vue'
import DiagnosisReport from '../components/DiagnosisReport.vue'
const store=useWorkspace(),route=useRoute(),router=useRouter(),source=ref('')
const records=computed(()=>store.state.reports.filter(r=>r.context.segment.id===store.context?.segment.id))
const reportId=computed(()=>String(route.params.id??'').startsWith('REP-')?String(route.params.id):'')
const detections=computed(()=>store.state.detections.filter(d=>d.status==='success'&&d.context.segment.id===store.context?.segment.id))
function create(){if(source.value)router.push('/diagnosis/'+store.createReport(source.value))}
</script>
<template><div class="page-stack"><div class="page-actions"><h2>检测报告</h2><RouterLink to="/detections">返回数据监测</RouterLink></div><Panel title="生成检测报告"><label>来源检测任务<select v-model="source"><option value="">请选择已完成检测</option><option v-for="d in detections" :key="d.id" :value="d.id">{{d.name}}</option></select></label><button class="primary" :disabled="!source" @click="create">生成报告</button></Panel><DiagnosisReport v-if="reportId" :report-id="reportId" @created="router.push('/diagnosis/'+$event)"/><Panel title="报告历史与归档"><div class="table-wrap"><table><thead><tr><th>报告</th><th>版本</th><th>归档状态</th><th>操作</th></tr></thead><tbody><tr v-for="r in records" :key="r.id"><td>{{r.title}}</td><td>{{r.version}}</td><td>{{r.archivedAt?'已归档':'未归档'}}</td><td><RouterLink :to="'/diagnosis/'+r.id">查看报告</RouterLink></td></tr></tbody></table><p v-if="!records.length" class="empty">暂无报告，请选择检测任务生成。</p></div></Panel></div></template>
