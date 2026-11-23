<script setup lang="ts">
withDefaults(defineProps<{ title: string; hint?: string }>(), { hint: '' })
</script>

<template>
  <div class="empty">
    <div class="screen" aria-hidden="true">
      <span class="eye" />
      <span class="eye" />
    </div>
    <p class="title">{{ title }}</p>
    <span v-if="hint" class="hint">{{ hint }}</span>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 38px 20px;
  text-align: center;
}

.screen {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 68px;
  height: 26px;
  border: 1px solid var(--oled-screen-border);
  border-radius: var(--radius-xs);
  background: var(--oled-bg);
}

.eye {
  width: 4.5px;
  height: 4.5px;
  border-radius: 50%;
  background: var(--oled-glow);
  opacity: 0.72;
}

.title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-2);
}

.hint {
  font-size: 12px;
  color: var(--dim);
}
</style>
