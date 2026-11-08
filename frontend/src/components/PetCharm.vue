<script setup lang="ts">
import { useId } from 'vue'

withDefaults(defineProps<{ online?: boolean }>(), { online: true })

const uid = useId()
const gradId = `charm-grad-${uid}`
const glowId = `charm-glow-${uid}`
</script>

<template>
  <svg
    class="charm"
    :class="{ offline: !online }"
    viewBox="0 0 44 60"
    role="img"
    aria-label="电子桌宠挂件"
  >
    <defs>
      <linearGradient :id="gradId" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#ffb347" />
        <stop offset="0.55" stop-color="#ff5a5f" />
        <stop offset="1" stop-color="#ff3d8b" />
      </linearGradient>
      <filter :id="glowId" x="-90%" y="-90%" width="280%" height="280%">
        <feGaussianBlur stdDeviation="1.2" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>

    <!-- 钥匙扣与挂绳 -->
    <circle cx="22" cy="6" r="4" fill="none" :stroke="`url(#${gradId})`" stroke-width="1.8" />
    <path d="M22 10v5" stroke="rgba(20,20,20,.45)" stroke-width="1" stroke-dasharray="1 2" />

    <g class="pendant">
      <!-- 尾巴 -->
      <g class="tail-group">
        <path
          d="M15 41C11 41 8.5 38 9.5 34.5"
          fill="none"
          stroke="#141414"
          stroke-width="1.5"
          stroke-linecap="round"
        />
      </g>

      <!-- 身子 -->
      <rect x="14" y="36" width="16" height="11" rx="5.5" fill="#f7f4ee" stroke="#141414" stroke-width="1.1" />
      <rect x="16.5" y="46" width="4" height="4" rx="2" fill="#f1ede5" stroke="#141414" stroke-width="1" />
      <rect x="23.5" y="46" width="4" height="4" rx="2" fill="#f1ede5" stroke="#141414" stroke-width="1" />
      <circle cx="17" cy="41.5" r="1" fill="#ff8a3d" />
      <circle cx="20" cy="41.5" r="1" fill="#ff5a5f" />
      <circle cx="23" cy="41.5" r="1" fill="#ff3d8b" />

      <!-- 头 -->
      <circle cx="10.5" cy="16" r="2.6" fill="#f7f4ee" stroke="#141414" stroke-width="1" />
      <circle cx="33.5" cy="16" r="2.6" fill="#f7f4ee" stroke="#141414" stroke-width="1" />
      <rect x="8" y="15" width="28" height="21" rx="9.5" fill="#f7f4ee" stroke="#141414" stroke-width="1.2" />
      <rect x="12" y="19" width="20" height="13" rx="4.5" fill="#141414" />

      <g class="eyes">
        <circle cx="18" cy="25.5" r="1.8" fill="#ffb347" :filter="`url(#${glowId})`" />
        <circle cx="26" cy="25.5" r="1.8" fill="#ff5a5f" :filter="`url(#${glowId})`" />
      </g>

      <ellipse cx="14" cy="33.4" rx="2" ry="1" fill="#ff5a5f" opacity=".4" />
      <ellipse cx="30" cy="33.4" rx="2" ry="1" fill="#ff5a5f" opacity=".4" />
    </g>
  </svg>
</template>

<style scoped>
.charm {
  display: block;
  width: 44px;
  height: auto;
  flex-shrink: 0;
  overflow: visible;
}

.charm.offline {
  opacity: 0.45;
  filter: grayscale(0.5);
}

.pendant,
.tail-group,
.eyes {
  transform-box: view-box;
}

.pendant {
  transform-origin: 22px 10px;
  animation: swing 4.2s ease-in-out infinite;
}

.tail-group {
  transform-origin: 15px 41px;
  animation: wag 2.6s ease-in-out infinite;
}

.eyes {
  transform-origin: 22px 25.5px;
  animation: blink 6s ease-in-out infinite;
}

.charm:hover .pendant {
  animation-duration: 1.1s;
}

.charm:hover .tail-group {
  animation: wag 0.5s ease-in-out infinite;
}

@keyframes swing {
  0%,
  100% {
    transform: rotate(-4deg);
  }
  50% {
    transform: rotate(4deg);
  }
}

@keyframes wag {
  0%,
  100% {
    transform: rotate(-8deg);
  }
  50% {
    transform: rotate(12deg);
  }
}

@keyframes blink {
  0%,
  91%,
  100% {
    transform: scaleY(1);
  }
  95% {
    transform: scaleY(0.15);
  }
}
</style>
