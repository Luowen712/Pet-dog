<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 27 })
</script>

<template>
  <span class="mark" :style="`--s:${size}px`" aria-hidden="true">
    <span class="ring" />
    <span class="eye eye-l" />
    <span class="eye eye-r" />
  </span>
</template>

<style scoped>
.mark {
  position: relative;
  display: inline-block;
  width: var(--s);
  height: var(--s);
  flex-shrink: 0;
}

.ring {
  position: absolute;
  inset: 0;
  padding: calc(var(--s) * 0.092);
  border-radius: calc(var(--s) * 0.3);
  background: var(--grad);
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  mask-composite: exclude;
}

.eye {
  position: absolute;
  top: calc(var(--s) * 0.44);
  width: calc(var(--s) * 0.1);
  height: calc(var(--s) * 0.1);
  border-radius: 50%;
  background: var(--ink);
}

.eye-l {
  left: calc(var(--s) * 0.3);
}

.eye-r {
  right: calc(var(--s) * 0.3);
}
</style>
