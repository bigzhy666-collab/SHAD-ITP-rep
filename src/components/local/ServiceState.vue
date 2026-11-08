<script setup lang="ts">
import {useIntegration} from '../../stores/integration'
const service=useIntegration()
</script>
<template><div v-if="!service.ready" class="local-service-state" :role="service.error?'alert':'status'"><h3>{{service.connection==='connecting'?'正在连接本机服务':'本机服务尚未连接'}}</h3><p>{{service.error||'启动本地后端后，可导入本站数据并执行检测。现有演示记录不会作为真实结果显示。'}}</p><button class="primary" :disabled="service.connection==='connecting'" @click="service.connect">{{service.connection==='connecting'?'连接中…':'重新连接本机服务'}}</button></div><slot v-else /></template>
