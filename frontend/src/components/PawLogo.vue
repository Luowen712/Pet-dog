<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 34 })
</script>

<template>
  <svg
    class="paw-logo"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    role="img"
    aria-label="Pet-dog"
  >
    <rect width="64" height="64" rx="14" fill="#2f6fed" />
    <g fill="#ffffff">
      <ellipse cx="24" cy="24" rx="6" ry="8" transform="rotate(-18 24 24)" />
      <ellipse cx="40" cy="24" rx="6" ry="8" transform="rotate(18 40 24)" />
      <ellipse cx="15" cy="36" rx="5" ry="6" transform="rotate(-28 15 36)" />
      <ellipse cx="49" cy="36" rx="5" ry="6" transform="rotate(28 49 36)" />
      <path d="M32 34c7 0 12 5.5 12 11 0 5-4.4 8-12 8s-12-3-12-8c0-5.5 5-11 12-11z" />
    </g>
  </svg>
</template>

<style scoped>
.paw-logo {
  display: block;
  border-radius: 9px;
  flex-shrink: 0;
}
</style>
