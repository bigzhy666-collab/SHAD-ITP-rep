<script setup lang="ts">defineProps<{ title?: string; tone?: string }>()</script>
<template><section :class="['panel',tone]"><header v-if="title" class="panel-heading"><h2>{{ title }}</h2><div class="panel-tools"><slot name="tools" /></div></header><div class="panel-body"><slot /></div></section></template>
