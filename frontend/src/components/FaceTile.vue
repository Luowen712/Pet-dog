<script setup lang="ts">
import { computed } from 'vue'
import { FACES, FACE_BY_ID } from '@/constants/faces'

const props = defineProps<{ face: number }>()
const def = computed(() => FACE_BY_ID.get(props.face) ?? FACES[0])
</script>

<template>
  <svg class="face" viewBox="0 0 128 32" role="img" :aria-label="def.name">
    <rect class="screen" x="0" y="0" width="128" height="32" rx="4" />
    <g class="pixel">
      <template v-if="def.eyes === 'round'">
        <circle cx="44" cy="12" r="4.6" class="solid" />
        <circle cx="84" cy="12" r="4.6" class="solid" />
      </template>
      <template v-else-if="def.eyes === 'arc'">
        <path d="M36 15 Q44 5.5 52 15" />
        <path d="M76 15 Q84 5.5 92 15" />
      </template>
      <template v-else-if="def.eyes === 'line'">
        <line x1="37" y1="13" x2="51" y2="13" />
        <line x1="77" y1="13" x2="91" y2="13" />
      </template>
      <template v-else-if="def.eyes === 'slant'">
        <line x1="37" y1="8" x2="51" y2="16" />
        <line x1="77" y1="16" x2="91" y2="8" />
      </template>
      <template v-else-if="def.eyes === 'big'">
        <circle cx="44" cy="12" r="7" />
        <circle cx="44" cy="12" r="2.6" class="solid" />
        <circle cx="84" cy="12" r="7" />
        <circle cx="84" cy="12" r="2.6" class="solid" />
      </template>
      <template v-else>
        <path
          class="solid"
          d="M44 5.5 L46.6 11 L52 13 L46.6 15 L44 20.5 L41.4 15 L36 13 L41.4 11 Z"
        />
        <path
          class="solid"
          d="M84 5.5 L86.6 11 L92 13 L86.6 15 L84 20.5 L81.4 15 L76 13 L81.4 11 Z"
        />
      </template>

      <template v-if="def.mouth === 'smile'">
        <path d="M55 20 Q64 28.5 73 20" />
      </template>
      <template v-else-if="def.mouth === 'frown'">
        <path d="M55 27 Q64 19.5 73 27" />
      </template>
      <template v-else-if="def.mouth === 'o'">
        <ellipse cx="64" cy="24" rx="3.6" ry="4.4" />
      </template>
      <template v-else-if="def.mouth === 'cat'">
        <path d="M57 22 Q60.5 26.5 64 22 Q67.5 26.5 71 22" />
      </template>
      <template v-else>
        <line x1="57" y1="24" x2="71" y2="24" />
      </template>
    </g>
    <g v-if="def.blush" class="blush">
      <ellipse cx="30" cy="20" rx="4" ry="2.4" />
      <ellipse cx="98" cy="20" rx="4" ry="2.4" />
    </g>
  </svg>
</template>

<style scoped>
.face {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 2px;
  border: 1px solid rgba(20, 20, 20, 0.55);
}

.screen {
  fill: #0a0f1a;
}

.pixel {
  fill: none;
  stroke: #7cf0c0;
  stroke-width: 3.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.pixel .solid {
  fill: #7cf0c0;
  stroke: none;
}

.blush ellipse {
  fill: #f47b8f;
  opacity: 0.55;
}
</style>
