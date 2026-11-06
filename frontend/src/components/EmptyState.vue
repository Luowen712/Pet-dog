<script setup lang="ts">
withDefaults(defineProps<{ title: string; hint?: string }>(), { hint: 'EMPTY' })
</script>

<template>
  <div class="empty">
    <div class="screen" aria-hidden="true">
      <span class="eye" />
      <span class="eye" />
    </div>
    <p class="title">{{ title }}</p>
    <span class="hint mono">{{ hint }}</span>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 46px 24px;
  text-align: center;
}

.screen {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 64px;
  height: 24px;
  border: 1px solid var(--hair);
  border-radius: 3px;
  background: rgba(20, 20, 20, 0.02);
}

.eye {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: rgba(20, 20, 20, 0.18);
}

.title {
  font-size: 12.5px;
  color: var(--dim);
}

.hint {
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}
</style>
