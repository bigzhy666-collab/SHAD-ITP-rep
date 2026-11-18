<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useWorkspace} from '../../stores/workspace'
import {errorText,localApi} from '../../services/local/api'
import type {Organization,Organizations} from '../../services/local/types'
import Panel from '../Panel.vue'
const workspace=useWorkspace(),kind=ref<keyof Organizations>('enterprises'),editing=ref<Organization>(),name=ref(''),code=ref(''),parent=ref(''),active=ref(true),busy=ref(false),error=ref(''),feedback=ref(''),search=ref('')
const labels={enterprises:'企业',networks:'供热管网',segments:'管段'}
const rows=computed(()=>workspace.organizations[kind.value].filter(r=>(r.name+r.code).includes(search.value)))
const parents=computed(()=>kind.value==='networks'?workspace.organizations.enterprises:workspace.organizations.networks)
function clear(){editing.value=undefined;name.value='';code.value='';parent.value='';active.value=true;error.value=''}
watch(kind,clear)
function edit(row:Organization){editing.value={...row};name.value=row.name;code.value=row.code;active.value=row.active;parent.value=row.enterpriseId??row.networkId??'';error.value='';feedback.value=''}
async function save(){if(busy.value)return;busy.value=true;error.value='';feedback.value='';try{
 if(editing.value)await localApi.updateOrganization(kind.value,editing.value.id,{name:name.value.trim(),code:code.value.trim(),active:active.value,expectedRevision:editing.value.revision})
 else await localApi.createOrganization(kind.value,{name:name.value.trim(),code:code.value.trim(),...(kind.value==='enterprises'?{}:kind.value==='networks'?{enterpriseId:parent.value}:{networkId:parent.value})})
 clear();await workspace.reloadOrganizations();feedback.value=workspace.organizationError?'已保存，列表刷新失败，请重试加载。':'已保存到本机。'
 }catch(e){error.value=errorText(e)}finally{busy.value=false}}
</script>
<template><Panel title="组织维护"><div class="local-form-grid"><label>管理层级<select v-model="kind" :disabled="busy" aria-label="组织管理层级"><option v-for="(label,key) in labels" :key="key" :value="key">{{label}}</option></select></label><label>搜索名称或编码<input v-model="search" aria-label="搜索组织"/></label><button :disabled="busy" @click="clear">新增{{labels[kind]}}</button><button :disabled="busy||workspace.organizationLoading" @click="workspace.reloadOrganizations">刷新组织</button></div>
<form class="local-form-grid mt" @submit.prevent="save"><label>{{labels[kind]}}名称<input v-model="name" aria-label="组织名称" maxlength="200" required :disabled="busy"/></label><label>编码<input v-model="code" aria-label="组织编码" maxlength="100" pattern="[A-Za-z0-9_.-]+" required :disabled="busy"/></label><label v-if="kind!=='enterprises'">所属{{kind==='networks'?'企业':'管网'}}<select v-model="parent" aria-label="组织上级" required :disabled="busy||!!editing"><option value="">请选择上级</option><option v-for="r in parents" :key="r.id" :value="r.id">{{r.name}}{{r.active?'':'（已停用）'}}</option></select></label><label v-if="editing">状态<select v-model="active" aria-label="组织状态" :disabled="busy"><option :value="true">启用</option><option :value="false">停用</option></select></label><button class="primary" :disabled="busy||!name.trim()||!code.trim()||(kind!=='enterprises'&&!parent)">{{busy?'保存中…':editing?'保存组织修改':'创建组织'}}</button></form>
<p class="muted mt">编码使用字母、数字、点、下划线或短横线。已有对象不更换上级，避免改变站点归属。停用不会删除历史；停用上级后，下属对象暂停创建新检测。</p><p v-if="error" class="error" role="alert">{{error}} 当前输入已保留，可刷新组织后重新选择记录核对。</p><p v-if="feedback" role="status">{{feedback}}</p>
<div class="table-wrap mt"><table><thead><tr><th>名称</th><th>编码</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td>{{r.name}}</td><td>{{r.code}}</td><td>{{r.active?'启用':'停用'}}</td><td><button :disabled="busy" :aria-label="'编辑组织 '+r.name" @click="edit(r)">编辑</button></td></tr><tr v-if="!rows.length"><td colspan="4" class="empty">暂无匹配组织，请调整搜索或新增。</td></tr></tbody></table></div></Panel></template>
