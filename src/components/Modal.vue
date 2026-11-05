<script setup lang="ts">
import { nextTick,onBeforeUnmount,onMounted,ref } from 'vue'
import { X } from 'lucide-vue-next'
defineProps<{title:string}>();const emit=defineEmits<{close:[]}>();const el=ref<HTMLElement>();let prior:Element|null
function key(e:KeyboardEvent){if(e.key==='Escape')emit('close');if(e.key==='Tab'){const n=el.value?.querySelectorAll<HTMLElement>('button:not(:disabled),input,select,textarea,[tabindex="0"]');const a=n?.[0],b=n?.[n.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();b?.focus()}else if(!e.shiftKey&&document.activeElement===b){e.preventDefault();a?.focus()}}}
onMounted(async()=>{prior=document.activeElement;document.body.style.overflow='hidden';document.addEventListener('keydown',key);await nextTick();el.value?.querySelector<HTMLElement>('button')?.focus()});onBeforeUnmount(()=>{document.body.style.overflow='';document.removeEventListener('keydown',key);if(prior instanceof HTMLElement)prior.focus()})
</script>
<template><Teleport to="body"><div class="modal-backdrop" @click.self="emit('close')"><section ref="el" class="modal" role="dialog" aria-modal="true" :aria-label="title"><header><h2>{{title}}</h2><button class="icon-button" aria-label="关闭弹窗" @click="emit('close')"><X :size="20" /></button></header><div class="modal-content"><slot /></div></section></div></Teleport></template>
