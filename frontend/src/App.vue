<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import ParticleBackdrop from '@/components/ParticleBackdrop.vue'
import { initTheme } from '@/utils/theme'

initTheme()

function onPointerMove(event: PointerEvent): void {
  const target = event.target as HTMLElement | null
  const card = target?.closest('.card') as HTMLElement | null
  if (!card) return
  const rect = card.getBoundingClientRect()
  card.style.setProperty('--mx', `${event.clientX - rect.left}px`)
  card.style.setProperty('--my', `${event.clientY - rect.top}px`)
}

onMounted(() => {
  window.addEventListener('pointermove', onPointerMove, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onPointerMove)
})
</script>

<template>
  <ParticleBackdrop />
  <router-view />
</template>
