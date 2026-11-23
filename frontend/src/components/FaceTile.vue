<script setup lang="ts">
import { computed } from 'vue'
import { FACES, FACE_BY_ID } from '@/constants/faces'

const props = defineProps<{ face: number }>()
const def = computed(() => FACE_BY_ID.get(props.face) ?? FACES[0])
</script>

<template>
  <div class="oled-wrap">
    <svg class="face" viewBox="0 0 128 32" role="img" :aria-label="def.name">
      <rect class="screen" x="0" y="0" width="128" height="32" rx="4" />
      <g class="pixel">
        <template v-if="def.eyes === 'round'">
          <circle cx="44" cy="12" r="4.6" class="solid" />
          <circle cx="84" cy="12" r="4.6" class="solid" />
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
        <template v-else-if="def.eyes === 'capsule'">
          <rect class="solid" x="36" y="4.5" width="15" height="20" rx="7.5" />
          <rect class="solid" x="77" y="4.5" width="15" height="20" rx="7.5" />
        </template>
        <template v-else-if="def.eyes === 'chevron'">
          <path d="M38 6 L50 13 L38 20" />
          <path d="M90 6 L78 13 L90 20" />
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
        <template v-else-if="def.mouth === 'omega'">
          <path d="M55 22.5 Q59.5 27.5 64 22.5 Q68.5 27.5 73 22.5" />
        </template>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.oled-wrap {
  position: relative;
  width: 100%;
  border-radius: var(--radius-sm);
  border: 1px solid var(--oled-screen-border);
  background: var(--oled-bg);
  overflow: hidden;
  box-shadow: inset 0 0 16px rgba(0, 0, 0, 0.72);
}

.oled-wrap::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    rgba(255, 255, 255, 0.03) 0px,
    rgba(255, 255, 255, 0.03) 1px,
    transparent 1px,
    transparent 3px
  );
}

.face {
  display: block;
  width: 100%;
  height: auto;
}

.screen {
  fill: var(--oled-bg);
}

.pixel {
  fill: none;
  stroke: var(--oled-glow);
  stroke-width: 3.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 0 4px rgba(100, 240, 184, 0.48));
}

.pixel .solid {
  fill: var(--oled-glow);
  stroke: none;
}
</style>
