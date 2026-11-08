<script setup lang="ts">
import {computed} from 'vue'
import {useIntegration} from '../stores/integration'
import Overview from './Overview.vue'
import Networks from './Networks.vue'
import Detections from './Detections.vue'
import Diagnosis from './Diagnosis.vue'
import LocalOverview from './local/LocalOverview.vue'
import LocalNetworks from './local/LocalNetworks.vue'
import LocalMonitoring from './local/LocalMonitoring.vue'
import LocalDiagnosis from './local/LocalDiagnosis.vue'
const props=defineProps<{page:'overview'|'networks'|'detections'|'diagnosis'}>(),service=useIntegration()
const view=computed(()=>({overview:service.local?LocalOverview:Overview,networks:service.local?LocalNetworks:Networks,detections:service.local?LocalMonitoring:Detections,diagnosis:service.local?LocalDiagnosis:Diagnosis})[props.page])
</script>
<template><component :is="view" /></template>
